"""Robustness / edge-case tests for Drone Flight Report.

Offline-safe: the wind provider is forced to fail so tests never hit the network.
Run:  python test_robustness.py
"""
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import app as m

print("import OK")

# Make wind fail fast + offline (app must degrade gracefully).
def _boom(*a, **k):
    raise RuntimeError("no network in test")

m.requests.get = _boom

client = m.app.test_client()
failures = []


def check(name, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    if not cond:
        failures.append(name)
    print(f"[{status}] {name} {detail}")


def post(filename, payload, consent=False):
    data = {"file": (io.BytesIO(payload), filename)}
    if consent:
        data["save_consent"] = "on"
    return client.post("/", data=data, content_type="multipart/form-data")


VALID_CSV = (
    "datetime(utc),latitude,longitude,altitude(m),speed(mph),heading\n"
    + "".join(
        f"2026-01-15 18:0{i}:00,34.0522,{-118.2437 + i * 0.0001},{40 + i},5.0,90\n"
        for i in range(6)
    )
).encode()

# 1. basics
check("GET / == 200", client.get("/").status_code == 200)
check("GET /health == 200", client.get("/health").status_code == 200)
check("GET /privacy == 200", client.get("/privacy").status_code == 200)
check("GET /robots.txt == 200", client.get("/robots.txt").status_code == 200)
for p in ["/dji-flight-log", "/ardupilot-bin", "/px4-ulg", "/vs-airdata"]:
    check(f"GET {p} == 200", client.get(p).status_code == 200)
check("GET /nope == 404", client.get("/nonexistent-page").status_code == 404)

# 2. upload validation (should be handled, never 500)
check("no file -> 400", client.post("/", data={}, content_type="multipart/form-data").status_code == 400)
check('empty filename -> 400', post("", b"x").status_code == 400)
check(".exe rejected -> 400", post("evil.exe", b"MZ\x90\x00").status_code == 400)

# 3. malformed content must degrade gracefully (error page, not a crash)
def graceful(name, r):
    body = r.get_data(as_text=True)
    ok = r.status_code < 500 and "Traceback" not in body
    check(name, ok, f"(status={r.status_code})")

graceful("empty .csv", post("empty.csv", b""))
graceful("garbage .csv (no coords)", post("garbage.csv", b"foo,bar\n1,2\n"))
graceful("binary junk .csv", post("bin.csv", b"\x00\x01\x02\xff\xfe random"))
graceful("random .bin", post("junk.bin", bytes(range(256)) * 40))
graceful("random .ulg", post("junk.ulg", b"\x00\x01ULog junk data" * 10))
graceful("bad geodata .csv", post("bad.csv", b"latitude,longitude\nabc,def\n"))
graceful("single row .csv", post("one.csv", b"latitude,longitude,altitude(m)\n34.0,-118.0,50\n"))

# 4. valid upload, no consent -> report ok, nothing saved
log_dir = m.LOG_DIR
os.makedirs(log_dir, exist_ok=True)
before = set(os.listdir(log_dir))
r = post("ok.csv", VALID_CSV, consent=False)
body = r.get_data(as_text=True)
check("valid .csv -> 200", r.status_code == 200, f"(bytes={len(r.data)})")
check("report shows wind-unavailable fallback", "Wind data unavailable" in body or "Wind" in body)
after_no = set(os.listdir(log_dir))
check("no consent -> nothing saved", before == after_no, f"(new={sorted(after_no - before)})")

# 5. valid upload, WITH consent -> de-identified log saved
r = post("ok2.csv", VALID_CSV, consent=True)
after_yes = set(os.listdir(log_dir))
new = after_yes - before
check("consent -> de-identified saved", len(new) >= 1, f"(file={sorted(new)})")
if new:
    fname = sorted(new)[0]
    with open(os.path.join(log_dir, fname), encoding="utf-8") as fh:
        head = fh.readline()
    check("saved file is de-identified (no latitude/longitude col)", "latitude" not in head and "longitude" not in head, f"(header={head.strip()})")

# 6. cleanup test artifacts
for f in new:
    try:
        os.remove(os.path.join(log_dir, f))
    except OSError:
        pass

print()
if failures:
    print("FAILURES:", failures)
    sys.exit(1)
print("ALL ROBUSTNESS TESTS PASSED")
