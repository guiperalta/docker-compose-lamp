import importlib.util, pathlib, sys, tempfile
root = pathlib.Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("lamp_indicator", root / "topbar" / "lamp_indicator.py")
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
fails = 0
def check(name, got, want):
    global fails
    ok = got == want
    print(("PASS: " if ok else "FAIL: ") + name + ("" if ok else f"  got={got!r} want={want!r}"))
    fails += not ok

check("parse_env", m.parse_env('A=1\n# c\nB="x y"\n\nC=\n'), {"A": "1", "B": "x y", "C": ""})

with tempfile.TemporaryDirectory() as d:
    p = pathlib.Path(d)
    (p / "fazp.env").write_text("PROJECT_NAME=fazp\nHTTP_PORT=8083\n")
    (p / "escrybe.env").write_text("PROJECT_NAME=escrybe\nHTTP_PORT=8081\n")
    check("load_projects sorted", m.load_projects(p), [
        {"name": "escrybe", "port": "8081"}, {"name": "fazp", "port": "8083"}])

check("parse_ps", m.parse_ps("lamp-fazp\trunning\nlamp-escrybe\tpaused\nother\trunning\n"),
      {"fazp": "running", "escrybe": "paused"})
check("parse_ps exited/created/dead -> stopped", m.parse_ps("lamp-a\texited\nlamp-b\tcreated\nlamp-c\tdead\n"), {"a": "stopped", "b": "stopped", "c": "stopped"})
check("parse_ps ignores -front containers", m.parse_ps("lamp-fazp\trunning\nlamp-fazp-front\trunning\n"), {"fazp": "running"})
check("parse_stats", m.parse_stats("lamp-fazp\t0.31%\t15MiB / 30.24GiB\nlamp-mysql8\t1.20%\t412.5MiB / 30.24GiB\n"),
      {"lamp-fazp": ("0.31%", "15MiB"), "lamp-mysql8": ("1.20%", "412.5MiB")})
check("fmt_stats", m.fmt_stats(("0.31%", "15MiB")), "0.3% CPU · 15 MiB")
check("fmt_stats none", m.fmt_stats(None), "")
check("shared_state", m.shared_state({"lamp-mysql8", "lamp-phpmyadmin"}), "running")
check("shared_state stopped", m.shared_state(set()), "stopped")

# --- regression: Stop crashed the machine. An idle callback that returns True re-runs forever
# (100k+ calls/200ms), each spawning docker subprocesses. One-shot callbacks must return False.
calls = []
check("once returns False and calls fn once", (m.once(lambda: calls.append(1))(), calls), (False, [1]))
check("once returns False even if fn returns True", m.once(lambda: True)(), False)

try:
    import gi
    from gi.repository import GLib
    n = [0]
    loop = GLib.MainLoop()
    GLib.idle_add(m.once(lambda: n.__setitem__(0, n[0] + 1) or True))
    GLib.timeout_add(150, loop.quit); loop.run()
    check("idle_add(once(fn)) runs exactly once under real GLib", n[0], 1)
except ImportError:
    print("SKIP: GLib not available")

import re
src = (root / "topbar" / "lamp_indicator.py").read_text()
bad = [l.strip() for l in src.splitlines() if "GLib.idle_add(request_refresh" in l]
check("no bare idle_add(request_refresh) (it returns True)", bad, [])

# Chrome upgrades http://localhost links opened from other apps to https (SSL error on our plain-HTTP
# ports). IP addresses are never upgraded, so the app must open 127.0.0.1.
check("project_url uses localhost by default", m.project_url("8081", None) if False else m.project_url("8081", m.DEFAULT_HOST), "http://localhost:8081")
check("project_url host override", m.project_url("8081", "127.0.0.1"), "http://127.0.0.1:8081")
check("host_from_env default", m.host_from_env({}), "localhost")
check("host_from_env LAMP_HOST", m.host_from_env({"LAMP_HOST": "127.0.0.1"}), "127.0.0.1")
check("host_from_env empty value falls back", m.host_from_env({"LAMP_HOST": ""}), "localhost")
check("pma_url", m.pma_url(), "http://" + m.current_host() + ":8080")
check("no hardcoded http://localhost left in app", "http://localhost" in (root / "topbar" / "lamp_indicator.py").read_text(), False)

# --- shared button rules (tray menu and panel use the same ones)
f = m.action_flags
check("flags stopped", f("stopped", None), {"open": False, "start": True, "pause": False, "resume": False, "restart": False, "stop": False})
check("flags running", f("running", None), {"open": True, "start": False, "pause": True, "resume": False, "restart": True, "stop": True})
check("flags paused", f("paused", None), {"open": False, "start": False, "pause": False, "resume": True, "restart": True, "stop": True})
check("flags busy disables all", any(f("running", "stopping").values()), False)
check("status_label running", m.status_label("fazp", "running", "0.3% CPU · 15 MiB", None), "● fazp   0.3% CPU · 15 MiB")
check("status_label paused", m.status_label("fazp", "paused", "", None), "⏸ fazp")
check("status_label busy", m.status_label("fazp", "running", "x", "stopping"), "⏳ fazp — stopping…")
sys.exit(1 if fails else 0)
