"""Wiring test: tray menu entry "Open panel…" opens the panel inside the real main_gui().
Run:  dbus-run-session -- xvfb-run -a python3 tests/topbar_wiring_test.py"""
import importlib.util, pathlib, sys
import gi
gi.require_version("Gtk", "3.0")
gi.require_version("AyatanaAppIndicator3", "0.1")
from gi.repository import Gtk
root = pathlib.Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("lamp_indicator", root / "topbar" / "lamp_indicator.py")
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)

items = []
orig_append = Gtk.Menu.append
Gtk.Menu.append = lambda self, i: (items.append(i), orig_append(self, i))[1]
result = {}

def pump():
    for _ in range(100):
        while Gtk.events_pending():
            Gtk.main_iteration()

def fake_main():
    labels = [i.get_label() for i in items if hasattr(i, "get_label")]
    result["has_open_panel"] = "Open panel…" in labels
    next(i for i in items if getattr(i, "get_label", lambda: None)() == "Open panel…").activate()
    pump()
    tops = [w for w in Gtk.Window.list_toplevels() if w.get_title() == "LAMP projects" and w.get_visible()]
    result["panel_visible"] = len(tops) == 1
    if tops:
        buttons = []
        def walk(w):
            if isinstance(w, Gtk.Button): buttons.append(w.get_label())
            if isinstance(w, Gtk.Container): [walk(c) for c in w.get_children()]
        walk(tops[0])
        result["buttons"] = buttons

Gtk.main = fake_main
m.main_gui()
ok = result.get("has_open_panel") and result.get("panel_visible") and "Stop all" in result.get("buttons", [])
print("PASS: tray 'Open panel…' opens the panel" if ok else f"FAIL: {result}")
sys.exit(0 if ok else 1)
