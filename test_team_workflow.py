"""Focused checks for the team-pilot acquisition and report workflow."""

import io
import json
import os
import tempfile

import app as m


def _offline(*args, **kwargs):
    raise RuntimeError("network disabled in test")


m.requests.get = _offline
client = m.app.test_client()
failures = []


def check(name, condition):
    print(("PASS" if condition else "FAIL") + " - " + name)
    if not condition:
        failures.append(name)


before_generated = set(os.listdir(m.GENERATED_DIR))
original_pilot_file = m.PILOT_REQUESTS_FILE

try:
    with tempfile.TemporaryDirectory() as temp_dir:
        m.PILOT_REQUESTS_FILE = os.path.join(
            temp_dir, "pilot_requests.jsonl"
        )

        response = client.get("/for-teams")
        page = response.get_data(as_text=True)
        check("GET /for-teams", response.status_code == 200)
        check("S1 is described as available", "available now" in page)
        check("S2 is described as pilot scope", "pilot scope" in page)
        check("P/D separation is explicit", "separate from the product P" in page)

        response = client.post(
            "/for-teams",
            data={
                "name": "Test User",
                "email": "not-an-email",
                "workflow": "flight_test",
                "monthly_flights": "1-10",
                "message": "A sufficiently detailed recurring workflow.",
                "contact_consent": "yes",
            },
        )
        check("invalid pilot email rejected", response.status_code == 400)

        response = client.post(
            "/for-teams",
            data={
                "name": "Test User",
                "email": "test@example.com",
                "organization": "Example Flight Lab",
                "role": "Flight-test lead",
                "workflow": "flight_test",
                "formats": "PX4 .ulg and ArduPilot .bin",
                "monthly_flights": "11-50",
                "message": (
                    "We manually review logs, copy charts and prepare a PDF "
                    "for an engineering approver after every test flight."
                ),
                "contact_consent": "yes",
            },
        )
        check("valid pilot request accepted", response.status_code == 200)
        check("pilot request stored", os.path.exists(m.PILOT_REQUESTS_FILE))
        if os.path.exists(m.PILOT_REQUESTS_FILE):
            with open(m.PILOT_REQUESTS_FILE, encoding="utf-8") as handle:
                record = json.loads(handle.readline())
            check("pilot record excludes IP", "ip" not in record)
            check("pilot workflow stored", record.get("workflow") == "flight_test")

    csv_payload = (
        "datetime(utc),latitude,longitude,altitude(m),speed(mph),heading\n"
        + "".join(
            "2026-01-15 18:0{}:00,34.0522,{},{},5.0,90\n".format(
                i, -118.2437 + i * 0.0001, 40 + i
            )
            for i in range(6)
        )
    ).encode("utf-8")
    response = client.post(
        "/",
        data={
            "file": (io.BytesIO(csv_payload), "team-test.csv"),
            "organization": "Example Flight Lab",
            "project": "Regression Campaign 7",
            "aircraft": "PX4 Test Article A",
            "pilot": "Internal Operator",
            "client_reference": "WO-2026-17",
        },
        content_type="multipart/form-data",
    )
    report = response.get_data(as_text=True)
    check("professional upload succeeds", response.status_code == 200)
    check("organization appears in report", "Example Flight Lab" in report)
    check("project appears in report", "Regression Campaign 7" in report)
    check("client reference appears in report", "WO-2026-17" in report)

    privacy = client.get("/privacy").get_data(as_text=True)
    check("privacy covers pilot enquiries", "180 days" in privacy)
    sitemap = client.get("/sitemap.xml").get_data(as_text=True)
    check("sitemap includes team landing page", "/for-teams" in sitemap)
finally:
    m.PILOT_REQUESTS_FILE = original_pilot_file
    after_generated = set(os.listdir(m.GENERATED_DIR))
    for name in after_generated - before_generated:
        try:
            os.remove(os.path.join(m.GENERATED_DIR, name))
        except OSError:
            pass


if failures:
    raise SystemExit("Team workflow failures: " + ", ".join(failures))

print("ALL TEAM WORKFLOW TESTS PASSED")
