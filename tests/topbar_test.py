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
check("parse_stats", m.parse_stats("lamp-fazp\t0.31%\t15MiB / 30.24GiB\nlamp-mysql8\t1.20%\t412.5MiB / 30.24GiB\n"),
      {"lamp-fazp": ("0.31%", "15MiB"), "lamp-mysql8": ("1.20%", "412.5MiB")})
check("fmt_stats", m.fmt_stats(("0.31%", "15MiB")), "0.3% CPU · 15 MiB")
check("fmt_stats none", m.fmt_stats(None), "")
check("shared_state", m.shared_state({"lamp-mysql8", "lamp-phpmyadmin"}), "running")
check("shared_state stopped", m.shared_state(set()), "stopped")
sys.exit(1 if fails else 0)
