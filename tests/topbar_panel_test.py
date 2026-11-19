"""GUI test of the control panel under a virtual display:  xvfb-run -a python3 tests/topbar_panel_test.py"""
import importlib.util, pathlib, sys
import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk
root = pathlib.Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("lamp_indicator", root / "topbar" / "lamp_indicator.py")
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
fails = 0
def check(name, got, want):
    global fails
    ok = got == want
    print(("PASS: " if ok else "FAIL: ") + name + ("" if ok else f"  got={got!r} want={want!r}"))
    fails += not ok

calls = []
class Actions:
    def do(self, project, verb, cmd): calls.append(("do", project, verb, cmd))
    def open_url(self, url): calls.append(("open", url))
projects = [{"name": "escrybe", "port": "8081"}, {"name": "fazp", "port": "8083"}]
snap = {"states": {"escrybe": "running", "fazp": "stopped"},
        "stats": {"lamp-escrybe": ("0.3%", "15MiB")}, "shared": "running"}
p = m.Panel(Gtk, projects, Actions())
p.update(snap, {}, projects)
p.show()
r = p.rows
check("panel visible after show", p.window.get_visible(), True)
check("running: stop enabled", r["escrybe"]["stop"].get_sensitive(), True)
check("running: start disabled", r["escrybe"]["start"].get_sensitive(), False)
check("stopped: start enabled", r["fazp"]["start"].get_sensitive(), True)
check("stopped: open disabled", r["fazp"]["open"].get_sensitive(), False)
check("running: toggle says Pause", r["escrybe"]["toggle"].get_label(), "Pause")
check("name label has stats", "0.3% CPU" in r["escrybe"]["label"].get_text(), True)

# the window must STAY OPEN after an action
r["escrybe"]["stop"].clicked()
check("stop calls lamp down", calls[-1], ("do", "escrybe", "stopping", [str(m.LAMP), "down", "escrybe"]))
check("window stays open after Stop", p.window.get_visible(), True)
r["fazp"]["start"].clicked()
check("start calls lamp up", calls[-1], ("do", "fazp", "starting", [str(m.LAMP), "up", "fazp"]))
check("window stays open after Start", p.window.get_visible(), True)
r["escrybe"]["toggle"].clicked()
check("Pause calls docker pause", calls[-1], ("do", "escrybe", "pausing", ["docker", "pause", "lamp-escrybe"]))
check("window stays open after Pause", p.window.get_visible(), True)

# paused: toggle becomes Resume
p.update({"states": {"escrybe": "paused", "fazp": "stopped"}, "stats": {}, "shared": "running"}, {}, projects)
check("paused: toggle says Resume", r["escrybe"]["toggle"].get_label(), "Resume")
r["escrybe"]["toggle"].clicked()
check("Resume calls docker unpause", calls[-1], ("do", "escrybe", "resuming", ["docker", "unpause", "lamp-escrybe"]))

# busy disables everything and shows the verb
p.update(snap, {"escrybe": "stopping"}, projects)
check("busy: stop disabled", r["escrybe"]["stop"].get_sensitive(), False)
check("busy: label shows verb", "stopping" in r["escrybe"]["label"].get_text(), True)

# only Open in browser closes the window
p.update(snap, {}, projects)
r["escrybe"]["open"].clicked()
check("open calls url", calls[-1], ("open", "http://localhost:8081"))
check("window closes after Open", p.window.get_visible(), False)

# project list change rebuilds rows
p.show()
p.update(snap, {}, projects + [{"name": "lps", "port": "8082"}])
check("rows rebuilt for new project", "lps" in p.rows, True)
check("window still visible after rebuild", p.window.get_visible(), True)

# Stop all keeps window open too
n = len(calls); p.stop_all.clicked()
check("stop all calls lamp down-all", calls[n], ("do", "_all", "stopping all", [str(m.LAMP), "down-all"]))
check("window stays open after Stop all", p.window.get_visible(), True)
sys.exit(1 if fails else 0)
