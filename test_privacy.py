"""Privacy tests: temp-file deletion, anonymisation, and consent logic.

Offline-safe: the wind provider is forced to fail so no network is used.
Run:  python test_privacy.py
      (or the VS Code "Run Python File" button)

What is verified
----------------
1. The uploaded file is deleted after processing - on success AND on failure.
2. Consent is strict: only the exact value "on" saves anything.
3. The saved "de-identified" log contains no latitude/longitude, no UTC
   timestamp and no absolute coordinates - only a relative trajectory.
4. The original filename never leaks into the report page or the PDF.
5. The retention policy actually deletes expired files and keeps fresh ones.
"""
import io
import os
import re
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import app as m

print("import OK")

# ---------------------------------------------------------------------------
# Offline: never touch Open-Meteo / NASA POWER during tests.
# ---------------------------------------------------------------------------
def _boom(*a, **k):
    raise RuntimeError("no network in test")


m.requests.get = _boom

# ---------------------------------------------------------------------------
# Isolate the test run from the real generated/ and data/logs/ folders.
# ---------------------------------------------------------------------------
TEST_ROOT = tempfile.mkdtemp(prefix="dfr_privacy_")
m.GENERATED_DIR = os.path.join(TEST_ROOT, "generated")
m.LOG_DIR = os.path.join(TEST_ROOT, "logs")
os.makedirs(m.GENERATED_DIR, exist_ok=True)
os.makedirs(m.LOG_DIR, exist_ok=True)

client = m.app.test_client()
failures = []


def check(name, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    if not cond:
        failures.append(name)
    print("[%s] %s %s" % (status, name, detail))


def post(filename, payload, consent=None, extra=None):
    data = {"file": (io.BytesIO(payload), filename)}
    if consent is not None:
        data["save_consent"] = consent
    if extra:
        data.update(extra)
    return client.post("/", data=data, content_type="multipart/form-data")


VALID_CSV = (
    "datetime(utc),latitude,longitude,altitude(m),speed(mph),heading\n"
    + "".join(
        "2026-01-15 18:%02d:00,34.052%03d,%.6f,%d,5.0,90\n"
        % (i, i, -118.2437 + i * 0.0001, 40 + i)
        for i in range(12)
    )
).encode("utf-8")

GARBAGE = b"this,is,not,a,flight,log\n1,2,3,4,5,6\n"


def log_files():
    return sorted(
        name for name in os.listdir(m.LOG_DIR)
        if name.endswith(".csv")
    )


# ---------------------------------------------------------------------------
# 1. Temp file deletion on success
# ---------------------------------------------------------------------------
import tempfile as _tempfile

_real_ntf = _tempfile.NamedTemporaryFile
_seen = {}


def _spy_ntf(*args, **kwargs):
    handle = _real_ntf(*args, **kwargs)
    _seen["path"] = handle.name
    return handle


m.tempfile.NamedTemporaryFile = _spy_ntf

r = post("clean_flight.csv", VALID_CSV)
check("upload_returns_200", r.status_code == 200, "status=%s" % r.status_code)
check(
    "temp_file_path_recorded",
    bool(_seen.get("path")),
    _seen.get("path", ""),
)
check(
    "temp_file_deleted_after_success",
    not os.path.exists(_seen.get("path", "")),
    "still exists" if os.path.exists(_seen.get("path", "")) else "gone",
)

# ---------------------------------------------------------------------------
# 2. Temp file deletion on failure (bad log)
# ---------------------------------------------------------------------------
_seen.clear()
r = post("garbage.csv", GARBAGE)
check("bad_upload_rejected", r.status_code == 400, "status=%s" % r.status_code)
check(
    "temp_file_deleted_after_failure",
    not os.path.exists(_seen.get("path", "")),
    "still exists" if os.path.exists(_seen.get("path", "")) else "gone",
)

m.tempfile.NamedTemporaryFile = _real_ntf

# ---------------------------------------------------------------------------
# 3. Consent is opt-in and strict
# ---------------------------------------------------------------------------
before = log_files()

post("no_consent.csv", VALID_CSV)
check("no_consent_saves_nothing", log_files() == before, "%d files" % len(log_files()))

post("truthy_consent.csv", VALID_CSV, consent="true")
check(
    "consent_true_is_not_enough",
    log_files() == before,
    "only the exact value 'on' may save data",
)

r_consent = post("yes_consent.csv", VALID_CSV, consent="on")
after = log_files()
added = [name for name in after if name not in before]
check("consent_on_saves_one_file", len(added) == 1, str(added))

# ---------------------------------------------------------------------------
# 4. The saved file is really de-identified
# ---------------------------------------------------------------------------
saved_path = os.path.join(m.LOG_DIR, added[0]) if added else None

check(
    "deidentified_filename",
    bool(added) and added[0].startswith("deidentified_"),
    added[0] if added else "no file",
)

if saved_path and os.path.exists(saved_path):
    with open(saved_path, "r", encoding="utf-8") as fh:
        text = fh.read()

    header = text.splitlines()[0].split(",")
    check(
        "no_lat_lon_columns",
        "latitude" not in header and "longitude" not in header,
        str(header),
    )
    check(
        "no_timestamp_column",
        not any("time" in column.lower() for column in header),
        str(header),
    )
    check(
        "requires_relative_xy",
        "x_m" in header and "y_m" in header,
        str(header),
    )
    check(
        "altitude_is_relative",
        "altitude_above_start_m" in header and "altitude_m" not in header,
        str(header),
    )
    check(
        "no_absolute_coordinates_in_text",
        "34.05" not in text and "118.24" not in text,
        "raw coordinates must not appear",
    )

    first_row = text.splitlines()[1].split(",")
    check(
        "trajectory_starts_at_origin",
        abs(float(first_row[header.index("x_m")])) < 1e-6
        and abs(float(first_row[header.index("y_m")])) < 1e-6,
        "first point must be (0, 0)",
    )

    altitude_values = []
    for line in text.splitlines()[1:]:
        if not line.strip():
            continue
        try:
            altitude_values.append(
                float(line.split(",")[header.index("altitude_above_start_m")])
            )
        except ValueError:
            pass

    check(
        "altitude_starts_near_zero",
        bool(altitude_values) and abs(altitude_values[0]) < 1e-6,
        "first sample must be 0 m above take-off",
    )
    check(
        "altitude_is_not_sea_level",
        bool(altitude_values) and max(abs(v) for v in altitude_values) < 200.0,
        "max |height above start| = %.1f m"
        % (max((abs(v) for v in altitude_values), default=-1)),
    )

    values = [
        abs(float(line.split(",")[header.index("x_m")]))
        for line in text.splitlines()[1:]
        if line.strip()
    ]
    check(
        "trajectory_is_relative_and_small",
        max(values) < 5000.0 if values else False,
        "max |x| = %.1f m" % (max(values) if values else -1),
    )

# ---------------------------------------------------------------------------
# 5. The original filename must not leak into the page or the PDF
# ---------------------------------------------------------------------------
SECRET_NAME = "CLIENT_ACME_2026_secret.csv"
for name in os.listdir(m.GENERATED_DIR):
    os.remove(os.path.join(m.GENERATED_DIR, name))

r = post(SECRET_NAME, VALID_CSV)
body = r.data.decode("utf-8", "ignore")
check(
    "filename_not_in_report_page",
    "CLIENT_ACME" not in body and "secret.csv" not in body,
    "uploaded filename must not be echoed",
)

pdfs = [
    os.path.join(m.GENERATED_DIR, n)
    for n in os.listdir(m.GENERATED_DIR)
    if n.endswith(".pdf")
]
if pdfs:
    with open(pdfs[0], "rb") as fh:
        pdf_bytes = fh.read()
    check(
        "filename_not_in_pdf",
        b"CLIENT_ACME" not in pdf_bytes,
        "%d pdf checked" % len(pdfs),
    )
else:
    check("filename_not_in_pdf", False, "no PDF generated")

# ---------------------------------------------------------------------------
# 6. User-initiated deletion (/delete-data)
# ---------------------------------------------------------------------------
token = added[0][len("deidentified_"):-len(".csv")] if added else ""
report_body = r_consent.data.decode("utf-8", "ignore")

check(
    "data_token_shown_on_report",
    bool(token) and token in report_body,
    token,
)

if not added:
    # The consent upload above failed; create a target so deletion is still tested.
    post("consent_for_delete.csv", VALID_CSV, consent="on")
    candidates = log_files()
    token = candidates[-1][len("deidentified_"):-len(".csv")] if candidates else ""

def _do_delete(value):
    return client.post("/delete-data", data={"token": value})

r_page = client.get("/delete-data")
check(
    "delete_page_renders",
    r_page.status_code == 200
    and "Delete your shared data" in r_page.data.decode("utf-8", "ignore"),
    "status=%s" % r_page.status_code,
)

r_del = _do_delete(token)
check("delete_returns_200", r_del.status_code == 200, "status=%s" % r_del.status_code)
check(
    "delete_removes_file",
    not os.path.exists(os.path.join(m.LOG_DIR, "deidentified_%s.csv" % token)),
    "file still present",
)
check(
    "delete_confirmation_text",
    "Deleted" in r_del.data.decode("utf-8", "ignore"),
    "user must see confirmation",
)

r_again = _do_delete(token)
check(
    "second_delete_reports_not_found",
    "Not found" in r_again.data.decode("utf-8", "ignore"),
    "already deleted",
)

r_bad = _do_delete("does-not-exist-123")
check(
    "unknown_token_is_safe",
    "Not found" in r_bad.data.decode("utf-8", "ignore"),
    "must not reveal anything",
)

r_traversal = _do_delete("../../app.py")
check(
    "path_traversal_blocked",
    "Not found" in r_traversal.data.decode("utf-8", "ignore")
    and os.path.exists(os.path.join(HERE, "app.py")),
    "token must not be used as a path",
)

# ---------------------------------------------------------------------------
# 7. Retention policy
# ---------------------------------------------------------------------------
old_log = os.path.join(m.LOG_DIR, "deidentified_old.csv")
with open(old_log, "w", encoding="utf-8") as fh:
    fh.write("x_m,y_m\n0,0\n")
old_age = time.time() - (m.RETENTION_HOURS["logs"] + 2) * 3600
os.utime(old_log, (old_age, old_age))

fresh_log = os.path.join(m.LOG_DIR, "deidentified_fresh.csv")
with open(fresh_log, "w", encoding="utf-8") as fh:
    fh.write("x_m,y_m\n0,0\n")

old_pdf = os.path.join(m.GENERATED_DIR, "old_report.pdf")
with open(old_pdf, "wb") as fh:
    fh.write(b"%PDF-1.4\n")
old_pdf_age = time.time() - (m.RETENTION_HOURS["generated"] + 2) * 3600
os.utime(old_pdf, (old_pdf_age, old_pdf_age))

m.enforce_retention()

check("retention_deletes_expired_logs", not os.path.exists(old_log))
check("retention_keeps_fresh_logs", os.path.exists(fresh_log))
check("retention_deletes_expired_pdfs", not os.path.exists(old_pdf))

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
shutil.rmtree(TEST_ROOT, ignore_errors=True)

print("")
if failures:
    print("FAILED (%d): %s" % (len(failures), ", ".join(failures)))
    sys.exit(1)

print("All privacy checks passed.")
