#!/usr/bin/env python3
"""Ubuntu top-bar indicator for the lamp projects (GNOME + AppIndicator).

Shows each project's state and CPU/RAM; start / pause / restart / stop; open in browser.
Talks to the host docker CLI and ./lamp directly. No server, no docker socket exposure.
`--status` prints the same info in the terminal (no GUI needed).
"""
import os, pathlib, subprocess, sys, threading

REPO = pathlib.Path(__file__).resolve().parent.parent
LAMP = REPO / "lamp"
PROJECTS_DIR = REPO / "projects"
REFRESH_SECONDS = 5
# 127.0.0.1, not the name localhost: Chrome upgrades localhost links opened from other apps to https,
# which breaks our plain-HTTP ports (ERR_SSL_PROTOCOL_ERROR). IPs are never upgraded.
PMA_URL = "http://127.0.0.1:8080"


def project_url(port):
    return f"http://127.0.0.1:{port}"


# ---------- pure helpers (unit-tested in tests/topbar_test.py) ----------
def parse_env(text):
    out = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def load_projects(projects_dir=PROJECTS_DIR):
    res = []
    for f in sorted(pathlib.Path(projects_dir).glob("*.env")):
        env = parse_env(f.read_text())
        res.append({"name": f.stem, "port": env.get("HTTP_PORT", "")})
    return res


def parse_ps(output):
    """`docker ps -a` lines 'name<TAB>state' -> {project: state} for lamp-<project> web containers."""
    res = {}
    for line in output.splitlines():
        if "\t" not in line:
            continue
        name, state = line.split("\t", 1)
        if name.startswith("lamp-") and name not in ("lamp-mysql8", "lamp-phpmyadmin"):
            res[name[5:]] = state.strip()
    return res


def parse_stats(output):
    """'name<TAB>cpu<TAB>mem / limit' -> {name: (cpu, mem)}"""
    res = {}
    for line in output.splitlines():
        parts = line.split("\t")
        if len(parts) == 3:
            res[parts[0]] = (parts[1].strip(), parts[2].split("/")[0].strip())
    return res


def fmt_stats(s):
    if not s:
        return ""
    cpu, mem = s
    try:
        cpu = f"{float(cpu.rstrip('%')):.1f}%"
    except ValueError:
        pass
    for unit in ("KiB", "MiB", "GiB", "B"):
        if mem.endswith(unit) and unit != "B" or (unit == "B" and mem.endswith("B")):
            mem = mem[: -len(unit)] + " " + unit
            break
    return f"{cpu} CPU · {mem}"


def shared_state(running_names):
    return "running" if {"lamp-mysql8", "lamp-phpmyadmin"} & set(running_names) else "stopped"


# ---------- docker access ----------
def once(fn):
    """Wrap fn as a one-shot GLib idle callback. GLib re-runs an idle callback that returns a
    truthy value forever, so always return False. (Returning True here crashed the machine.)"""
    def wrapper(*_):
        fn()
        return False
    return wrapper


def _run(cmd, timeout=15):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout
    except Exception:
        return ""


def snapshot():
    ps = _run(["docker", "ps", "-a", "--filter", "name=lamp-", "--format", "{{.Names}}\t{{.State}}"])
    states = parse_ps(ps)
    all_running = {l.split("\t")[0] for l in ps.splitlines() if l.endswith("\trunning") or l.endswith("\tpaused")}
    stats = parse_stats(_run(["docker", "stats", "--no-stream", "--format",
                              "{{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}"], timeout=20))
    return {"states": states, "stats": stats, "shared": shared_state(all_running)}


def print_status():
    snap = snapshot()
    for p in load_projects():
        st = snap["states"].get(p["name"], "stopped")
        print(f'{p["name"]:<14}{st:<10}{fmt_stats(snap["stats"].get("lamp-" + p["name"])):<26}{project_url(p["port"])}')
    ms = [snap["stats"].get("lamp-mysql8"), snap["stats"].get("lamp-phpmyadmin")]
    print(f'{"shared":<14}{snap["shared"]:<10}{" | ".join(fmt_stats(x) for x in ms if x)}')


# ---------- GUI ----------
def main_gui():
    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("AyatanaAppIndicator3", "0.1")
    from gi.repository import AyatanaAppIndicator3 as AppIndicator, GLib, Gtk

    ICON = {"running": "●", "paused": "⏸", "stopped": "○"}
    busy = {}          # project -> verb being run ("starting", "stopping"...)
    widgets = {}       # project -> dict of menu items
    state = {"snap": {"states": {}, "stats": {}, "shared": "stopped"}, "names": None}

    ind = AppIndicator.Indicator.new("lamp-indicator", "network-server-symbolic",
                                     AppIndicator.IndicatorCategory.APPLICATION_STATUS)
    ind.set_status(AppIndicator.IndicatorStatus.ACTIVE)
    menu = Gtk.Menu()
    ind.set_menu(menu)

    def notify(msg):
        subprocess.Popen(["notify-send", "-i", "network-server", "LAMP", msg],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def do(project, verb, cmd):
        def work():
            busy[project] = verb
            GLib.idle_add(refresh_labels)
            r = subprocess.run(cmd, capture_output=True, text=True)
            busy.pop(project, None)
            if r.returncode != 0:
                GLib.idle_add(notify, f"{project}: {verb} failed\n{(r.stderr or r.stdout).strip()[-200:]}")
            GLib.idle_add(once(refresh_async))
        threading.Thread(target=work, daemon=True).start()

    def open_url(url):
        subprocess.Popen(["xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def item(label, cb):
        it = Gtk.MenuItem(label=label)
        it.connect("activate", lambda *_: cb())
        return it

    def build_menu():
        for c in menu.get_children():
            menu.remove(c)
        widgets.clear()
        projects = load_projects()
        for p in projects:
            n = p["name"]
            head = Gtk.MenuItem(label=n)
            sub = Gtk.Menu()
            w = {"head": head}
            w["open"] = item("Open in browser", lambda n=n, p=p: open_url(project_url(p['port'])))
            w["start"] = item("Start", lambda n=n: do(n, "starting", [str(LAMP), "up", n]))
            w["pause"] = item("Pause", lambda n=n: do(n, "pausing", ["docker", "pause", f"lamp-{n}"]))
            w["resume"] = item("Resume", lambda n=n: do(n, "resuming", ["docker", "unpause", f"lamp-{n}"]))
            w["restart"] = item("Restart", lambda n=n: do(n, "restarting", [str(LAMP), "restart", n]))
            w["stop"] = item("Stop", lambda n=n: do(n, "stopping", [str(LAMP), "down", n]))
            for k in ("open", "start", "pause", "resume", "restart", "stop"):
                sub.append(w[k])
            head.set_submenu(sub)
            menu.append(head)
            widgets[n] = w
        menu.append(Gtk.SeparatorMenuItem())
        sh = Gtk.MenuItem(label="Shared: …")
        shsub = Gtk.Menu()
        shsub.append(item("Open phpMyAdmin", lambda: open_url(PMA_URL)))
        sh.set_submenu(shsub)
        menu.append(sh)
        widgets["_shared"] = {"head": sh}
        menu.append(item("Stop all", lambda: do("_all", "stopping all", [str(LAMP), "down-all"])))
        menu.append(Gtk.SeparatorMenuItem())
        menu.append(item("Quit", Gtk.main_quit))
        menu.show_all()
        state["names"] = [p["name"] for p in projects]

    def refresh_labels():
        snap = state["snap"]
        running = 0
        for n in state["names"] or []:
            w = widgets.get(n)
            if not w:
                continue
            st = snap["states"].get(n, "stopped")
            running += st == "running"
            b = busy.get(n) or busy.get("_all")
            stats = fmt_stats(snap["stats"].get(f"lamp-{n}")) if st == "running" else ""
            w["head"].set_label(f"⏳ {n} — {b}…" if b else f"{ICON.get(st, '○')} {n}   {stats}".rstrip())
            idle = not b
            w["open"].set_sensitive(st == "running" and idle)
            w["start"].set_sensitive(st == "stopped" and idle)
            w["pause"].set_sensitive(st == "running" and idle)
            w["resume"].set_sensitive(st == "paused" and idle)
            w["restart"].set_sensitive(st in ("running", "paused") and idle)
            w["stop"].set_sensitive(st in ("running", "paused") and idle)
        sh = widgets.get("_shared")
        if sh:
            parts = [fmt_stats(snap["stats"].get(c)) for c in ("lamp-mysql8", "lamp-phpmyadmin")]
            sh["head"].set_label(f"{'●' if snap['shared'] == 'running' else '○'} MySQL + phpMyAdmin   "
                                 + " | ".join(x for x in parts if x))
        ind.set_label(str(running) if running else "", "")
        ind.set_icon_full("network-server-symbolic" if running else "network-offline-symbolic", "LAMP")
        return False

    def refresh_async():
        """Fetch docker state in a thread, apply on the GTK thread. Never overlaps itself."""
        if state.get("refreshing"):
            return
        state["refreshing"] = True
        def work():
            try:
                snap = snapshot()
            except Exception:
                snap = None
            def apply():
                state["refreshing"] = False
                if snap is None:
                    return
                if state["names"] != [p["name"] for p in load_projects()]:
                    build_menu()
                state["snap"] = snap
                refresh_labels()
            GLib.idle_add(once(apply))
        threading.Thread(target=work, daemon=True).start()

    def request_refresh():
        """Timer callback only (GLib.timeout_add_seconds): True keeps the timer alive."""
        refresh_async()
        return True

    build_menu()
    refresh_async()
    GLib.timeout_add_seconds(REFRESH_SECONDS, request_refresh)
    Gtk.main()


if __name__ == "__main__":
    if "--status" in sys.argv:
        print_status()
    else:
        try:
            main_gui()
        except (ImportError, ValueError) as e:
            sys.exit(f"top-bar indicator not supported here: {e}\n"
                     "Install: sudo apt install gir1.2-ayatanaappindicator3-0.1 gnome-shell-extension-appindicator")
