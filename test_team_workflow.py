"""Focused checks for the team-pilot acquisition and report workflow."""

import io
import json
import os
import tempfile
import re
import base64
import zlib

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

        home = client.get("/").get_data(as_text=True)
        check(
            "homepage presents report choices and analyzer",
            "Drop your flight log here" in home
            and 'id="try-report"' in home
            and home.count('class="offer-card"') == 4
            and 'href="/start/performance"' in home
            and 'href="/start/incident"' in home
            and 'href="/start/wind"' in home
            and 'href="/start/team"' in home
            and 'id="faq"' in home,
        )
        check(
            "quick upload is standard and does not ask for a second report choice",
            'name="report_type" value="standard"' in home
            and 'id="reportType"' not in home,
        )
        check(
            "homepage delegates detailed content to subpages",
            'id="teams"' not in home
            and 'id="wind-reference"' not in home
            and 'id="guides"' not in home
            and home.count('class="faq-item"') == 3,
        )
        check(
            "homepage exposes multi-page navigation",
            'href="/for-teams"' in home
            and 'href="/solutions/flight-test-teams"' in home
            and 'href="/solutions/drone-service-reporting"' in home
            and 'href="/solutions/research-flight-data"' in home
            and 'href="/evidence-and-limits"' in home,
        )
        check(
            "homepage navigation marks home active",
            'href="/" aria-current="page">Home</a>' in home,
        )

        solution_paths = (
            "/reports/flight-performance",
            "/reports/wind-analysis",
            "/solutions/flight-test-teams",
            "/solutions/drone-service-reporting",
            "/solutions/research-flight-data",
            "/platform/team-log-workflow",
            "/evidence-and-limits",
        )
        for path in solution_paths:
            response = client.get(path)
            check("GET %s" % path, response.status_code == 200)

        for slug, required_field in (
            ("performance", 'name="client_reference"'),
            ("incident", 'name="incident_symptom"'),
            ("wind", 'name="wind_question"'),
            ("team", 'name="organization"'),
        ):
            response = client.get("/start/" + slug)
            form = response.get_data(as_text=True)
            check("GET /start/%s" % slug, response.status_code == 200)
            check("distinct %s upload fields" % slug,
                  required_field in form and 'action="/start/%s"' % slug in form)
            check("%s keeps CSS inside style tags" % slug,
                  bool(re.search(r'</style>\s*<style>\s*body\{', form)))
        check("unknown report form is 404", client.get("/start/unknown").status_code == 404)

        workflow_page = client.get(
            "/platform/team-log-workflow"
        ).get_data(as_text=True)
        check(
            "team workflow does not claim live accounts",
            "are not live self-service features" in workflow_page,
        )
        check("workflow page links to team pilot", 'href="/for-teams"' in workflow_page)
        check(
            "navigation placeholders are fully rendered",
            "%%SITE_NAV" not in home and "%%SITE_NAV" not in workflow_page,
        )

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

    def pdf_contains(filename, heading):
        with open(os.path.join(m.GENERATED_DIR, filename), "rb") as handle:
            pdf = handle.read()
        for stream in re.findall(rb"stream\r?\n(.*?)endstream", pdf, re.S):
            try:
                content = zlib.decompress(base64.a85decode(stream.strip(), adobe=True))
            except (ValueError, zlib.error, OverflowError):
                continue
            if heading.encode("ascii") in content:
                return True
        return False

    for slug, heading, focus, specialist in (
        ("performance", "Flight Performance Report", "DATA QUALITY", "Flight performance at a glance"),
        ("incident", "Incident Evidence Draft", "EVIDENCE STILL NEEDED", "Incident evidence worksheet"),
        ("wind", "Wind Context Report", "AVAILABLE HEIGHT LEVELS", "Wind source assessment"),
        ("team", "Team Handoff Draft", "HUMAN REVIEW HANDOFF", "Client handoff worksheet"),
    ):
        sample_path = os.path.join(
            os.path.dirname(__file__), "samples", "synthetic-report-tests", slug + ".csv"
        )
        with open(sample_path, "rb") as sample_file:
            sample_payload = sample_file.read()
        response = client.post(
            "/start/" + slug,
            data={
                "file": (io.BytesIO(sample_payload), slug + ".csv"),
                "report_type": "standard",  # the URL must select the template
                "organization": "Example Flight Lab",
                "project": "Campaign 7",
                "incident_symptom": "Pilot saw drift",
                "wind_question": "Was model wind available?",
            },
            content_type="multipart/form-data",
        )
        page = response.get_data(as_text=True)
        filenames = re.findall(r"/download_report/(flight_report_[a-f0-9]+\.pdf)", page)
        check("POST /start/%s" % slug, response.status_code == 200 and bool(filenames))
        if filenames:
            check("%s has its own PDF cover" % slug, pdf_contains(filenames[0], heading))
            check("%s has its own report section" % slug, pdf_contains(filenames[0], focus))
            check("%s has a distinct working page" % slug, pdf_contains(filenames[0], specialist))
    check(
        "satellite view offers 3D globe and overzoomed 2D tiles",
        'id="cesiumMap"' in report
        and 'new Cesium.Viewer' in report
        and 'maxNativeZoom: 17, maxZoom: 22' in report
        and 'id="flight3d"' not in report
        and 'id="timelineSlider"' in report,
    )
    check(
        "timeline controls bind events and charts",
        'data-sample-index=' in report
        and 'chart.addEventListener("click"' in report,
    )

    telemetry = m.pd.DataFrame([
        {"latitude": 34.0, "longitude": -118.0, "elapsed_seconds": 0,
         "relative_altitude_m": 10, "altitude_m": 110, "speed_mps": 1,
         "wind_speed_mps": 3, "wind_direction_deg": 90},
        {"latitude": 34.1, "longitude": -118.1, "elapsed_seconds": 2,
         "relative_altitude_m": None, "altitude_m": 120, "speed_mps": 2},
        {"latitude": 34.2, "longitude": -118.2, "elapsed_seconds": 9,
         "relative_altitude_m": 30, "altitude_m": 130, "speed_mps": 4},
    ])
    payload = m.build_telemetry_payload(telemetry, {
        "speed": 5, "direction": 180, "source": "weather model"
    }, max_points=3)
    check("last telemetry sample uses its own values", payload["nodes"][-1]["speed_mps"] == 4)
    check("missing relative altitude stays missing", payload["nodes"][1]["altitude_m"] is None)
    check("elapsed time stays on the shared axis", payload["series"]["x"] == [0, 2, 9])
    check("logged wind provenance stays distinct", payload["nodes"][0]["wind_source"].startswith("logged wind"))
    check("model wind provenance stays distinct", payload["nodes"][1]["wind_source"].startswith("regional model"))
    public_context = m.extract_report_context({
        "report_type": "incident", "review_status": "approved", "service_plan": "team"
    })
    check("public upload cannot claim approval", public_context["review_status"] == "draft")
    check("public upload cannot claim a paid plan", public_context["service_plan"] == "free")
    sparse = m.build_telemetry_payload(
        m.pd.concat([telemetry, m.pd.DataFrame([{
            "latitude": 34.3, "longitude": -118.3, "elapsed_seconds": 12,
            "relative_altitude_m": 40, "speed_mps": 7,
        }])], ignore_index=True),
        {}, max_points=2,
    )
    check("unsampled final node has its own telemetry", sparse["nodes"][-1]["speed_mps"] == 7)

    privacy = client.get("/privacy").get_data(as_text=True)
    check("privacy covers pilot enquiries", "180 days" in privacy)
    sitemap = client.get("/sitemap.xml").get_data(as_text=True)
    check("sitemap includes team landing page", "/for-teams" in sitemap)
    check(
        "sitemap includes solution pages",
        "/solutions/flight-test-teams" in sitemap
        and "/evidence-and-limits" in sitemap,
    )
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
