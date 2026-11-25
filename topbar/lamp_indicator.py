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
# Default host is localhost: fazp only accepts that exact host. Each project's HTTP port also answers
# TLS (haproxy "front" container), so Chrome's http->https upgrade of localhost links works.
# LAMP_HOST in .env overrides it (127.0.0.1 is never upgraded by Chrome but fazp rejects it).
DEFAULT_HOST = "localhost"


def host_from_env(env):
    return env.get("LAMP_HOST") or DEFAULT_HOST


def current_host():
    """Read LAMP_HOST from .env every call, so editing .env applies without restarting the app."""
    try:
        return host_from_env(parse_env((REPO / ".env").read_text()))
    except OSError:
        return DEFAULT_HOST


def project_url(port, host=None):
    return f"http://{host or current_host()}:{port}"


def pma_url():
    return project_url("8080")




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
        if name.startswith("lamp-") and not name.endswith("-front") and name not in ("lamp-mysql8", "lamp-phpmyadmin"):
            st = state.strip()
            # exited/created/dead/restarting etc. all mean 'not up': Start must be offered
            res[name[5:]] = st if st in ("running", "paused") else "stopped"
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


def parse_timer(out):
    """`lamp timer status` output -> ('disabled'|'idle'|'on', seconds_left)."""
    parts = (out or "").split()
    if parts[:1] == ["disabled"]:
        return ("disabled", 0)
    if len(parts) == 2 and parts[0] == "on" and parts[1].isdigit():
        return ("on", int(parts[1]))
    return ("idle", 0)


def fmt_left(sec):
    m = max(0, sec) // 60
    return f"{m // 60}h{m % 60:02d}" if m >= 60 else f"{m}min"


def timer_label(tm):
    kind, left = tm
    if kind == "disabled":
        return "⏱ Auto-stop timer: OFF (projects stay up)"
    if kind == "on":
        return f"⏱ Auto-stop in {fmt_left(left)}"
    return "⏱ Auto-stop timer: on (starts with a project)"


def timer_buttons(tm):
    """(toggle label, extra-button enabled). Toggle: Disable when on/idle, Enable when disabled."""
    kind, _ = tm
    return ("Enable" if kind == "disabled" else "Disable", kind == "on")


def shared_state(running_names):
    return "running" if {"lamp-mysql8", "lamp-phpmyadmin"} & set(running_names) else "stopped"


# ---------- docker access ----------
ICON = {"running": "●", "paused": "⏸", "stopped": "○"}


def action_flags(st, busy):
    """Which buttons are enabled for a project in state st (running/paused/stopped); busy = verb or None."""
    idle = not busy
    return {
        "open": st == "running" and idle,
        "start": st == "stopped" and idle,
        "pause": st == "running" and idle,
        "resume": st == "paused" and idle,
        "restart": st in ("running", "paused") and idle,
        "stop": st in ("running", "paused") and idle,
    }


def status_label(name, st, stats, busy):
    if busy:
        return f"⏳ {name} — {busy}…"
    return f"{ICON.get(st, '○')} {name}   {stats}".rstrip()


class Panel:
    """Small always-on-top control window. Stays open after Start/Stop/Pause/Restart/Stop all;
    only the "Open in browser" buttons close it (also Esc / the window X).
    Gtk and the action callbacks are injected so it can be tested under a virtual display."""

    def __init__(self, Gtk, projects, actions):
        self.Gtk, self.actions = Gtk, actions
        self.rows, self.names = {}, None
        w = self.window = Gtk.Window(title="LAMP projects")
        w.set_keep_above(True)
        w.set_resizable(False)
        w.set_border_width(12)
        w.set_position(Gtk.WindowPosition.MOUSE)
        w.connect("delete-event", lambda win, ev: win.hide_on_delete())
        w.connect("key-press-event", self._on_key)
        self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        w.add(self.box)
        self._build(projects)

    def _on_key(self, win, event):
        if event.keyval == 0xFF1B:  # GDK_KEY_Escape
            win.hide()
            return True
        return False

    def _button(self, label, cb):
        b = self.Gtk.Button(label=label)
        b.connect("clicked", lambda *_: cb())
        return b

    def _build(self, projects):
        Gtk = self.Gtk
        for c in self.box.get_children():
            self.box.remove(c)
        self.rows = {}
        for p in projects:
            n, port = p["name"], p["port"]
            row = Gtk.Box(spacing=6)
            label = Gtk.Label(xalign=0)
            label.set_width_chars(38)
            row.pack_start(label, True, True, 0)
            r = {"label": label, "st": "stopped"}
            r["open"] = self._button("Open in browser", lambda n=n, port=port: self._open(project_url(port)))
            r["start"] = self._button("Start", lambda n=n: self.actions.do(n, "starting", [str(LAMP), "up", n]))
            r["toggle"] = self._button("Pause", lambda n=n: self._toggle(n))
            r["restart"] = self._button("Restart", lambda n=n: self.actions.do(n, "restarting", [str(LAMP), "restart", n]))
            r["stop"] = self._button("Stop", lambda n=n: self.actions.do(n, "stopping", [str(LAMP), "down", n]))
            for k in ("open", "start", "toggle", "restart", "stop"):
                row.pack_start(r[k], False, False, 0)
            self.box.pack_start(row, False, False, 0)
            self.rows[n] = r
        self.box.pack_start(Gtk.Separator(), False, False, 2)
        srow = Gtk.Box(spacing=6)
        self.shared_label = Gtk.Label(xalign=0)
        self.shared_label.set_width_chars(38)
        srow.pack_start(self.shared_label, True, True, 0)
        srow.pack_start(self._button("Open phpMyAdmin", lambda: self._open(pma_url())), False, False, 0)
        self.stop_all = self._button("Stop all", lambda: self.actions.do("_all", "stopping all", [str(LAMP), "down-all"]))
        srow.pack_start(self.stop_all, False, False, 0)
        self.box.pack_start(srow, False, False, 0)
        trow = Gtk.Box(spacing=6)
        self.timer_label = Gtk.Label(xalign=0)
        self.timer_label.set_width_chars(38)
        trow.pack_start(self.timer_label, True, True, 0)
        self.timer_extend = self._button("+1h", lambda: self.actions.do("_timer", "re-arming timer", [str(LAMP), "timer", "on"]))
        self.timer_toggle = self._button("Disable", self._toggle_timer)
        trow.pack_start(self.timer_extend, False, False, 0)
        trow.pack_start(self.timer_toggle, False, False, 0)
        self.box.pack_start(trow, False, False, 0)
        self.timer = ("idle", 0)
        self.names = [p["name"] for p in projects]
        self.box.show_all()

    def _open(self, url):
        self.actions.open_url(url)
        self.window.hide()

    def _toggle_timer(self):
        if self.timer[0] == "disabled":
            self.actions.do("_timer", "enabling timer", [str(LAMP), "timer", "on"])
        else:
            self.actions.do("_timer", "disabling timer", [str(LAMP), "timer", "off"])

    def _toggle(self, n):
        if self.rows[n]["st"] == "paused":
            self.actions.do(n, "resuming", ["docker", "unpause", f"lamp-{n}"])
        else:
            self.actions.do(n, "pausing", ["docker", "pause", f"lamp-{n}"])

    def update(self, snap, busy, projects):
        if [p["name"] for p in projects] != self.names:
            self._build(projects)
        for p in projects:
            n = p["name"]
            r = self.rows[n]
            st = snap["states"].get(n, "stopped")
            b = busy.get(n) or busy.get("_all")
            stats = fmt_stats(snap["stats"].get(f"lamp-{n}")) if st == "running" else ""
            r["st"] = st
            r["label"].set_text(status_label(n, st, stats, b))
            flags = action_flags(st, b)
            for k in ("open", "start", "restart", "stop"):
                r[k].set_sensitive(flags[k])
            r["toggle"].set_label("Resume" if st == "paused" else "Pause")
            r["toggle"].set_sensitive(flags["resume"] if st == "paused" else flags["pause"])
        parts = [fmt_stats(snap["stats"].get(c)) for c in ("lamp-mysql8", "lamp-phpmyadmin")]
        self.shared_label.set_text(f"{'●' if snap['shared'] == 'running' else '○'} MySQL + phpMyAdmin   "
                                   + " | ".join(x for x in parts if x))
        self.stop_all.set_sensitive(not busy.get("_all"))
        self.timer = snap.get("timer", ("idle", 0))
        label, extend_ok = timer_buttons(self.timer)
        tb = busy.get("_timer")
        self.timer_label.set_text(f"⏳ {tb}…" if tb else timer_label(self.timer))
        self.timer_toggle.set_label(label)
        self.timer_toggle.set_sensitive(not tb)
        self.timer_extend.set_sensitive(extend_ok and not tb)

    def show(self):
        self.window.show_all()
        self.window.present()

    def hide(self):
        self.window.hide()


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
    return {"states": states, "stats": stats, "shared": shared_state(all_running),
            "timer": parse_timer(_run([str(LAMP), "timer", "status"], timeout=5))}


def print_status():
    snap = snapshot()
    for p in load_projects():
        st = snap["states"].get(p["name"], "stopped")
        print(f'{p["name"]:<14}{st:<10}{fmt_stats(snap["stats"].get("lamp-" + p["name"])):<26}{project_url(p["port"])}')
    ms = [snap["stats"].get("lamp-mysql8"), snap["stats"].get("lamp-phpmyadmin")]
    print(f'{"shared":<14}{snap["shared"]:<10}{" | ".join(fmt_stats(x) for x in ms if x)}')
    print(timer_label(snap["timer"]))


# ---------- GUI ----------
def main_gui():
    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("AyatanaAppIndicator3", "0.1")
    from gi.repository import AyatanaAppIndicator3 as AppIndicator, GLib, Gtk

    busy = {}          # project -> verb being run ("starting", "stopping"...)
    widgets = {}       # project -> dict of menu items
    state = {"snap": {"states": {}, "stats": {}, "shared": "stopped", "timer": ("idle", 0)}, "names": None, "projects": []}

    panel_ref = {}

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

    class PanelActions:
        def do(self, project, verb, cmd):
            do(project, verb, cmd)

        def open_url(self, url):
            open_url(url)

    def open_panel():
        if "panel" not in panel_ref:
            panel_ref["panel"] = Panel(Gtk, state["projects"], PanelActions())
        panel_ref["panel"].update(state["snap"], busy, state["projects"])
        panel_ref["panel"].show()

    def toggle_timer():
        if state["snap"].get("timer", ("idle", 0))[0] == "disabled":
            do("_timer", "enabling timer", [str(LAMP), "timer", "on"])
        else:
            do("_timer", "disabling timer", [str(LAMP), "timer", "off"])

    def item(label, cb):
        it = Gtk.MenuItem(label=label)
        it.connect("activate", lambda *_: cb())
        return it

    def build_menu():
        for c in menu.get_children():
            menu.remove(c)
        widgets.clear()
        projects = load_projects()
        state["projects"] = projects
        menu.append(item("Open panel…", open_panel))
        menu.append(Gtk.SeparatorMenuItem())
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
        shsub.append(item("Open phpMyAdmin", lambda: open_url(pma_url())))
        sh.set_submenu(shsub)
        menu.append(sh)
        widgets["_shared"] = {"head": sh}
        menu.append(item("Stop all", lambda: do("_all", "stopping all", [str(LAMP), "down-all"])))
        menu.append(Gtk.SeparatorMenuItem())
        th = Gtk.MenuItem(label="⏱ Auto-stop timer")
        tsub = Gtk.Menu()
        widgets["_timer"] = {"head": th, "toggle": item("Disable", toggle_timer),
                             "extend": item("Restart 1h", lambda: do("_timer", "re-arming timer", [str(LAMP), "timer", "on"]))}
        tsub.append(widgets["_timer"]["toggle"])
        tsub.append(widgets["_timer"]["extend"])
        th.set_submenu(tsub)
        menu.append(th)
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
            w["head"].set_label(status_label(n, st, stats, b))
            for k, on in action_flags(st, b).items():
                w[k].set_sensitive(on)
        sh = widgets.get("_shared")
        if sh:
            parts = [fmt_stats(snap["stats"].get(c)) for c in ("lamp-mysql8", "lamp-phpmyadmin")]
            sh["head"].set_label(f"{'●' if snap['shared'] == 'running' else '○'} MySQL + phpMyAdmin   "
                                 + " | ".join(x for x in parts if x))
        tw = widgets.get("_timer")
        if tw:
            tm = snap.get("timer", ("idle", 0))
            tw["head"].set_label(timer_label(tm))
            lab, ext = timer_buttons(tm)
            tw["toggle"].set_label(lab)
            tw["extend"].set_sensitive(ext)
        pn = panel_ref.get("panel")
        if pn is not None and pn.window.get_visible():
            pn.update(snap, busy, state["projects"])
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
