import os
import re
import math
import json
import uuid
import secrets
import tempfile
import time
from datetime import datetime, timedelta

import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.ticker import FormatStrFormatter
import numpy as np
import pandas as pd
import requests

from flask import (
    Flask,
    request,
    render_template_string,
    send_file,
    Response,
    jsonify,
)
from werkzeug.utils import secure_filename

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader

from pymavlink import mavutil
from pymavlink import DFReader
from pyulog import ULog


# =========================================================
# Flask
# =========================================================

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

GENERATED_DIR = os.path.join(BASE_DIR, "generated")
DATA_DIR = os.path.join(BASE_DIR, "data")
LOG_DIR = os.path.join(DATA_DIR, "logs")
CACHE_DIR = os.path.join(DATA_DIR, "cache")
SITE_URL = "https://drone-flight-report.com"
PILOT_REQUESTS_FILE = os.path.join(DATA_DIR, "pilot_requests.jsonl")
PILOT_LEAD_RETENTION_DAYS = 180

os.makedirs(GENERATED_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(CACHE_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)

# Optional 天地图 key. When set, the report offers the official Chinese
# satellite basemap (CGCS2000, aligned with BeiDou/WGS-84) in addition to
# the keyless Esri and 高德 layers.
TIANDITU_KEY = os.environ.get("TIANDITU_KEY", "").strip()

# IndexNow key. Public by design: it is served at /<key>.txt so search engines
# can prove we control the host. Override with the INDEXNOW_KEY env var.
INDEXNOW_KEY = os.environ.get(
    "INDEXNOW_KEY",
    "227dce2d9bae4cb3a113c6c392e85b1f",
).strip()


# Canonical internal flight-data schema. Format-specific parsers must map into this schema.
CANONICAL_COLUMNS = [
    "timestamp_utc",
    "elapsed_seconds",
    "latitude",
    "longitude",
    "altitude_m",
    "relative_altitude_m",
    "speed_mps",
    "heading_deg",
    "gps_satellites",
    "gps_quality",
]


# =========================================================
# HTML
# =========================================================

HTML = r"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport"
      content="width=device-width, initial-scale=1.0">

<title>Drone Flight Report — Free Drone Flight Log Analyzer (DJI, ArduPilot, PX4)</title>

<meta name="description" content="Free online drone flight log analyzer. Upload a DJI, ArduPilot (.bin) or PX4 (.ulg) log and get a flight-track map, statistics, wind reference, flight-health check and a downloadable PDF report. No sign-up, privacy-first.">
<meta name="keywords" content="drone flight log analyzer, UAV flight log viewer, DJI flight log, ArduPilot bin log analysis, PX4 ulg log, drone flight report PDF, drone telemetry analysis, free drone log tool">
<meta name="robots" content="index, follow">
<link rel="canonical" href="https://drone-flight-report.com/">

<meta property="og:type" content="website">
<meta property="og:site_name" content="Drone Flight Report">
<meta property="og:title" content="Drone Flight Report — Free Drone Flight Log Analyzer">
<meta property="og:description" content="Upload DJI / ArduPilot / PX4 flight logs and get a trajectory map, statistics, wind reference, flight-health check and a PDF report. Free, no sign-up, privacy-first.">
<meta property="og:url" content="https://drone-flight-report.com/">

<meta name="twitter:card" content="summary">
<meta name="twitter:title" content="Drone Flight Report — Free Drone Flight Log Analyzer">
<meta name="twitter:description" content="Upload DJI / ArduPilot / PX4 logs to get a flight track, stats, wind reference, health check and a PDF report.">

<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "SoftwareApplication",
  "name": "Drone Flight Report",
  "url": "https://drone-flight-report.com/",
  "applicationCategory": "UtilitiesApplication",
  "operatingSystem": "Web",
  "description": "Free online analyzer for drone flight logs (DJI, ArduPilot, PX4). Generates a flight-track map, statistics, wind reference, flight-health check and a downloadable PDF report.",
  "offers": {
    "@type": "Offer",
    "price": "0",
    "priceCurrency": "USD"
  },
  "featureList": [
    "Cross-vendor: DJI CSV/TXT, ArduPilot .bin, PX4 .ulg",
    "Flight trajectory map",
    "Distance / altitude / duration statistics",
    "Regional wind reference",
    "Flight-health check",
    "Downloadable PDF report",
    "No sign-up required",
    "Privacy-first: raw log deleted after processing"
  ]
}
</script>

<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "FAQPage",
  "mainEntity": [
    {
      "@type": "Question",
      "name": "Which flight log formats can I upload?",
      "acceptedAnswer": {
        "@type": "Answer",
        "text": "DJI logs exported as CSV or TXT, ArduPilot DataFlash logs in .bin, and PX4 logs in .ulg. The format and the columns are detected automatically, so you do not need to map fields or pick a template before uploading."
      }
    },
    {
      "@type": "Question",
      "name": "Is my flight log stored on your server?",
      "acceptedAnswer": {
        "@type": "Answer",
        "text": "No. Your log is parsed in memory to build the report, and the temporary file is deleted after processing. There is no account, so nothing is linked to your identity. A de-identified sample is kept only if you deliberately tick the sharing box."
      }
    },
    {
      "@type": "Question",
      "name": "Do I need an account or a payment?",
      "acceptedAnswer": {
        "@type": "Answer",
        "text": "No. There is no sign-up, no email capture and no payment. Upload a log, read the report in the browser, and download the PDF if you want to keep it."
      }
    },
    {
      "@type": "Question",
      "name": "Where does the wind reference come from?",
      "acceptedAnswer": {
        "@type": "Answer",
        "text": "Wind values are a regional historical reference for the coordinates and date of your flight, taken from the Open-Meteo historical weather API. They are hourly reanalysis values on a coarse grid, not a measurement taken by your aircraft, so treat them as context rather than telemetry."
      }
    },
    {
      "@type": "Question",
      "name": "What is included in the PDF report?",
      "acceptedAnswer": {
        "@type": "Answer",
        "text": "The PDF contains the trajectory map, distance, altitude and duration statistics, the wind reference, a flight-health score with the issues that were detected, and the flight timeline. It is generated from exactly the same data as the on-screen report."
      }
    },
    {
      "@type": "Question",
      "name": "Does it work on a phone or a tablet?",
      "acceptedAnswer": {
        "@type": "Answer",
        "text": "Yes. The analyzer runs in any modern browser and the upload page and report are responsive. Very large logs are still easier to handle on a desktop, but phone uploads work for typical DJI and ArduPilot files."
      }
    }
  ]
}
</script>

<style>

* {box-sizing: border-box;
}

body {
    margin: 0;
    min-height: 100vh;

    font-family:
        Inter,
        -apple-system,
        BlinkMacSystemFont,
        "Segoe UI",
        sans-serif;

    background:
        radial-gradient(
            circle at top left,
            #172554 0,
            #020617 40%,
            #000 100%
        );

    color: #f8fafc;
}

.container {
    width: min(1100px, 92%);
    margin: 0 auto;
    padding: 60px 0;
}

.hero {
    text-align: center;
    margin-bottom: 40px;
}

.hero h1 {
    font-size: 48px;
    margin: 0 0 15px;
    letter-spacing: -1px;
}

.hero p {
    color: #94a3b8;
    font-size: 18px;
    line-height: 1.6;
}

.card {
    background: rgba(15, 23, 42, 0.78);
    border: 1px solid rgba(148, 163, 184, 0.18);
    border-radius: 22px;
    padding: 30px;
    backdrop-filter: blur(18px);

    box-shadow:
        0 20px 70px rgba(0,0,0,0.35);
}

.upload-box {
    border: 2px solid rgba(148, 163, 184, 0.35);
    border-radius: 18px;
    padding: 45px 25px;
    text-align: center;
    cursor: pointer;

    transition:
        border-color .2s,
        background .2s;
}

.upload-box:hover {
    border-color: #60a5fa;
    background: rgba(59,130,246,0.05);
}

.upload-box input {
    display: none;
}

.upload-title {
    font-size: 22px;
    font-weight: 600;
    margin-bottom: 10px;
}

.upload-subtitle {
    color: #94a3b8;
}

.actions {
    margin-top: 25px;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 16px;
    flex-wrap: wrap;
    width: 100%;
}

button,
.demo-btn {
    border: none;
    border-radius: 12px;
    padding: 13px 24px;
    font-size: 16px;
    font-weight: 600;
    cursor: pointer;
    text-decoration: none;

    transition:
        transform .15s,
        opacity .15s;
}

button:hover,
.demo-btn:hover {
    transform: translateY(-1px);
}

.primary {
    background: #2563eb;
    color: white;
}

.secondary {
    background: #334155;
    color: white;
}

button:disabled {
    opacity: .4;
    cursor: not-allowed;
}

.file-name {
    margin-top: 15px;
    color: #60a5fa;
    min-height: 22px;
}

.consent {
    margin-top: 22px;
    color: #94a3b8;
    font-size: 14px;
    line-height: 1.5;
}

.date-row {
    margin-top: 16px;
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 10px 14px;
    color: #94a3b8;
    font-size: 14px;
}

.date-row label {
    font-weight: 600;
    color: #cbd5e1;
}

.date-row input[type="date"] {
    background: rgba(15, 23, 42, 0.8);
    border: 1px solid rgba(148, 163, 184, 0.28);
    border-radius: 10px;
    padding: 9px 12px;
    color: #e2e8f0;
    font-size: 14px;
    color-scheme: dark;
}

.date-row input[type="date"]:focus {
    outline: none;
    border-color: #60a5fa;
}

.date-hint {
    flex: 1 1 260px;
    font-size: 13px;
    line-height: 1.5;
    color: #64748b;
}

.status {
    margin-top: 25px;
    padding: 15px;
    border-radius: 12px;
    display: none;
}

.status.success {
    display: block;
    background: rgba(34,197,94,.12);
    border: 1px solid rgba(34,197,94,.25);
}

.status.error {
    display: block;
    background: rgba(239,68,68,.12);
    border: 1px solid rgba(239,68,68,.25);
}

.features {
    margin-top: 40px;

    display: grid;
    grid-template-columns:
        repeat(auto-fit, minmax(220px, 1fr));

    gap: 18px;
}

.feature {
    background: rgba(15,23,42,.55);
    border: 1px solid rgba(148,163,184,.12);
    border-radius: 16px;
    padding: 20px;
}

.feature h3 {
    margin-top: 0;
}

.feature p {
    color: #94a3b8;
    line-height: 1.6;
}

.professional-details {
    margin-top: 22px;
    border: 1px solid rgba(148, 163, 184, 0.18);
    border-radius: 14px;
    padding: 16px 18px;
    background: rgba(2, 6, 23, 0.38);
}

.professional-details summary {
    cursor: pointer;
    font-weight: 700;
    color: #bfdbfe;
}

.professional-grid {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 13px;
    margin-top: 16px;
}

.professional-grid label {
    color: #cbd5e1;
    font-size: 13px;
}

.professional-grid input {
    display: block;
    width: 100%;
    margin-top: 6px;
    padding: 10px 11px;
    border: 1px solid rgba(148, 163, 184, 0.28);
    border-radius: 9px;
    background: #0f172a;
    color: #e2e8f0;
}

.team-callout {
    display: grid;
    grid-template-columns: 1.5fr 1fr;
    gap: 24px;
    align-items: center;
}

.team-callout ul {
    color: #cbd5e1;
    line-height: 1.8;
    padding-left: 20px;
}

/* ---- Long-form SEO sections ---- */

.section {
    margin-top: 28px;
}

.section h2 {
    font-size: 26px;
    letter-spacing: -0.4px;
    margin: 0 0 16px;
}

.section p {
    color: #94a3b8;
    font-size: 15px;
    line-height: 1.8;
    margin: 0 0 14px;
}

.section p:last-child {
    margin-bottom: 0;
}

.steps {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 18px;
    margin: 4px 0 20px;
}

.step {
    background: rgba(2, 6, 23, 0.55);
    border: 1px solid rgba(148, 163, 184, 0.16);
    border-radius: 16px;
    padding: 20px 18px;
}

.step .step-num {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 26px;
    height: 26px;
    border-radius: 50%;
    background: rgba(37, 99, 235, 0.25);
    color: #93c5fd;
    font-size: 13px;
    font-weight: 700;
    margin-bottom: 10px;
}

.step h3 {
    margin: 0 0 8px;
    font-size: 16px;
}

.step p {
    margin: 0;
    font-size: 14px;
    line-height: 1.65;
}

.faq-grid {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 16px;
    margin-top: 4px;
}

.faq-item {
    background: rgba(2, 6, 23, 0.55);
    border: 1px solid rgba(148, 163, 184, 0.14);
    border-radius: 16px;
    padding: 20px 20px 18px;
}

.faq-item h3 {
    margin: 0 0 8px;
    font-size: 16px;
    line-height: 1.45;
}

.faq-item p {
    margin: 0;
    font-size: 14px;
    line-height: 1.7;
}

@media (max-width: 820px) {
    .steps,
    .faq-grid,
    .professional-grid,
    .team-callout {
        grid-template-columns: 1fr;
    }
}

footer {
    margin-top: 56px;
    padding-top: 28px;
    border-top: 1px solid rgba(148, 163, 184, 0.14);
    text-align: left;
    color: #64748b;
    font-size: 14px;
}

.footer-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 26px;
}

.footer-grid h4 {
    margin: 0 0 10px;
    font-size: 13px;
    text-transform: uppercase;
    letter-spacing: 0.6px;
    color: #94a3b8;
}

.footer-grid a {
    display: block;
    color: #60a5fa;
    text-decoration: none;
    line-height: 2;
}

.footer-base {
    margin: 26px 0 0;
    padding-top: 18px;
    border-top: 1px solid rgba(148, 163, 184, 0.1);
    font-size: 13px;
    line-height: 1.8;
}

.footer-base a {
    color: #60a5fa;
    text-decoration: none;
}
.upload-box {
    position: relative;
    display: block;
    width: 100%;
    box-sizing: border-box;

    border: 2px solid rgba(148, 163, 184, 0.35) !important;
    border-radius: 18px !important;

    padding: 35px 25px !important;
    text-align: center;

    background: rgba(15, 23, 42, 0.45);
    overflow: hidden;
}
.upload-box::before,
.upload-box::after {
    content: none !important;
    display: none !important;
}
</style>
</head>

<body>

<div class="container">

    <section class="hero">

        <h1>Drone Flight Report</h1>

        <p>
            Free online analyzer for drone flight logs.
            Upload a <strong>DJI</strong>, <strong>ArduPilot (.bin)</strong>
            or <strong>PX4 (.ulg)</strong> log and instantly get a
            flight-track map, statistics, a regional wind reference,
            a flight-health check and a downloadable PDF report.
        </p >

        <p style="margin-top:14px;color:#94a3b8;font-size:14px;line-height:1.7;">
            &#10003; Works across DJI, ArduPilot &amp; PX4
            &nbsp;&middot;&nbsp; &#10003; Runs in your browser, no sign-up
            &nbsp;&middot;&nbsp; &#10003; Free &amp; privacy-first
        </p >

    </section>


    <section class="card">

        <form
            id="uploadForm"
            action="/"
            method="POST"
            enctype="multipart/form-data"
        >

            <label class="upload-box">

                <input
                    id="fileInput"
                    type="file"
                    name="file"
                    accept=".csv,.txt,.bin,.ulg"
                    required
                >

                <div class="upload-title">
                    Drop your flight log here
                </div>

                <div class="upload-subtitle">
                    CSV / TXT / BIN / ULG
                </div>

                <div
                    id="fileName"
                    class="file-name"
                ></div>

            </label>


            
        <p class="small" style="text-align:center;margin:18px 0 0;color:#94a3b8;">
            Buying a used drone?
            &middot; Checking a flight that felt wrong?
            &middot; Sending a report to a client?
            <br>
            Start with the log &mdash; free, no sign-up, file deleted after processing.
        </p>

        <div class="consent">

                <label>

                    <input
                        type="checkbox"
                        name="save_consent"
                        id="saveConsent"
                    >

                    Share a de-identified version of my flight data
                    to help improve this service.

                </label>

            </div>


            <div class="date-row">

                <label for="flightDate">
                    Flight date
                </label>

                <input
                    id="flightDate"
                    type="date"
                    name="flight_date"
                    min="2000-01-01"
                >

                <span class="date-hint">
                    Optional. Only needed when the log has no GPS time -
                    it lets the wind reference run. Leave empty to use the
                    date stored in the file.
                </span>

            </div>


            <div class="actions">

                <button
                    id="uploadBtn"
                    class="primary"
                    type="submit"
                
                    >
                    Generate Report
                </button>

                <a
                    class="demo-btn secondary"
                    href="/demo"
                >
                    Try Demo
                </a >

                <a
                    class="demo-btn secondary"
                    href="/for-teams"
                >
                    For Teams
                </a >

            </div>

            <details class="professional-details">
                <summary>Add professional report details (optional)</summary>
                <p class="date-hint" style="margin:10px 0 0;">
                    These labels appear in the browser report and PDF. They are
                    not added to the shared de-identified dataset.
                </p>
                <div class="professional-grid">
                    <label>Organization
                        <input name="organization" maxlength="100"
                               placeholder="Your company or team">
                    </label>
                    <label>Project or mission
                        <input name="project" maxlength="120"
                               placeholder="Test campaign or client mission">
                    </label>
                    <label>Aircraft
                        <input name="aircraft" maxlength="100"
                               placeholder="Airframe, tail number or asset ID">
                    </label>
                    <label>Pilot or operator
                        <input name="pilot" maxlength="100"
                               placeholder="Optional internal label">
                    </label>
                    <label>Client reference
                        <input name="client_reference" maxlength="120"
                               placeholder="Work order or report reference">
                    </label>
                </div>
            </details>

        </form>


        <div id="status" class="status"></div>

    </section>

    <section class="card section team-callout" id="teams">
        <div>
            <h2>Turn flight logs into consistent, client-ready reports</h2>
            <p>
                Add organization, project, aircraft, pilot and client-reference
                details to each report. Built for flight-test teams, drone
                service providers and research groups that need a repeatable
                reporting workflow.
            </p>
            <a class="demo-btn primary" href="/for-teams">
                Explore team reporting
            </a>
        </div>
        <ul>
            <li>Professional single-flight reports available now</li>
            <li>Consistent PDF reports across supported log formats</li>
            <li>Need batch reporting, templates or approvals? Join the team pilot</li>
        </ul>
    </section>


    <section class="features">

        <div class="feature">

            <h3>Flight Track</h3>

            <p>
                Automatically detect latitude,
                longitude and altitude fields.
            </p >

        </div>


        <div class="feature">

            <h3>Flight Statistics</h3>

            <p>
                Distance, altitude, duration
                and trajectory statistics.
            </p >

        </div>


        <div class="feature">

            <h3>Wind Reference</h3>

            <p>
                Add regional wind information
                to your flight trajectory.
            </p >

        </div>


        <div class="feature">

            <h3>PDF Report</h3>

            <p>
                Generate a downloadable
                flight analysis report.
            </p >

        </div>

    </section>


    <section class="card section" id="how-it-works">

        <h2>How it works</h2>

        <div class="steps">

            <div class="step">
                <div class="step-num">1</div>
                <h3>Drop your log file</h3>
                <p>
                    Choose the file your app or flight controller saved:
                    a DJI CSV/TXT export, an ArduPilot .bin, or a PX4 .ulg.
                    Nothing has to be installed.
                </p>
            </div>

            <div class="step">
                <div class="step-num">2</div>
                <h3>We normalise the columns</h3>
                <p>
                    The tool detects the vendor, maps time, latitude,
                    longitude, altitude and speed onto one schema, validates
                    the GPS fixes, and discards the broken rows instead of
                    drawing garbage.
                </p>
            </div>

            <div class="step">
                <div class="step-num">3</div>
                <h3>Read the report</h3>
                <p>
                    You get an interactive satellite map with the full
                    trajectory, distance and altitude statistics, a
                    flight-health score, a regional wind reference, and a
                    PDF you can keep or send to a client.
                </p>
            </div>

        </div>

        <p>
            The whole analysis runs on the uploaded file only. There is no
            account to create, no fleet to set up, and no dashboard to learn.
            A typical DJI log takes a few seconds: the page shows the parsed
            point count, the detected date, and any warnings before the map
            appears. If a log is truncated or the GPS drops out mid-flight,
            the report says so explicitly instead of hiding it, because the
            most useful thing a flight log can tell a pilot is where the data
            stopped being trustworthy.
        </p>

    </section>


    <section class="card section" id="wind-reference">

        <h2>Wind reference</h2>

        <p>
            A flight log records where the aircraft went, but not the air it
            was pushing through. To give the numbers context, this tool looks
            up the historical weather for the coordinates and date of the
            flight and attaches a wind reference to the report: speed, the
            direction it came from, and how that compares with the direction
            the aircraft was actually flying.
        </p>

        <p>
            The source is the Open-Meteo historical weather API, which serves
            hourly reanalysis data on a regional grid. That means two honest
            limits: the value is an hourly average rather than a gust reading, and
            the grid cell is kilometres wide rather than the few metres around
            your aircraft. A headwind on the outbound leg and a tailwind on
            the return is exactly the kind of pattern this reference is meant
            to explain, and it is also why two flights on the same day can
            drain a battery very differently. Read it as context, not as
            telemetry: it is not a substitute for an anemometer or for the
            aircraft's own estimate.
        </p>

        <p class="small" style="color:#64748b;font-size:13px;line-height:1.7;margin-bottom:0;">
            Wind values are a regional historical reference derived from a
            third-party weather model. They are provided for context only and
            must not be used for navigation, airworthiness or safety-critical
            decisions.
        </p>

    </section>


    <section class="card section" id="faq">

        <h2>Frequently asked questions</h2>

        <div class="faq-grid">

            <div class="faq-item">
                <h3>Which flight log formats can I upload?</h3>
                <p>
                    DJI logs exported as CSV or TXT, ArduPilot DataFlash logs
                    in .bin, and PX4 logs in .ulg. The format and the columns
                    are detected automatically, so you do not need to map
                    fields or pick a template before uploading.
                </p>
            </div>

            <div class="faq-item">
                <h3>Is my flight log stored on your server?</h3>
                <p>
                    No. Your log is parsed in memory to build the report, and
                    the temporary file is deleted after processing. There is no
                    account, so nothing is linked to your identity. A
                    de-identified sample is kept only if you deliberately tick
                    the sharing box.
                </p>
            </div>

            <div class="faq-item">
                <h3>Do I need an account or a payment?</h3>
                <p>
                    No. There is no sign-up, no email capture and no payment.
                    Upload a log, read the report in the browser, and download
                    the PDF if you want to keep it.
                </p>
            </div>

            <div class="faq-item">
                <h3>Where does the wind reference come from?</h3>
                <p>
                    Wind values are a regional historical reference for the
                    coordinates and date of your flight, taken from the
                    Open-Meteo historical weather API. They are hourly
                    reanalysis values on a coarse grid, not a measurement taken
                    by your aircraft, so treat them as context rather than
                    telemetry.
                </p>
            </div>

            <div class="faq-item">
                <h3>What is included in the PDF report?</h3>
                <p>
                    The PDF contains the trajectory map, distance, altitude and
                    duration statistics, the wind reference, a flight-health
                    score with the issues that were detected, and the flight
                    timeline. It is generated from exactly the same data as the
                    on-screen report.
                </p>
            </div>

            <div class="faq-item">
                <h3>Does it work on a phone or a tablet?</h3>
                <p>
                    Yes. The analyzer runs in any modern browser and the upload
                    page and report are responsive. Very large logs are still
                    easier to handle on a desktop, but phone uploads work for
                    typical DJI and ArduPilot files.
                </p>
            </div>

        </div>

    </section>


    <section class="card" id="guides" style="margin-top:30px;">

        <h2>Flight log guides &amp; tools</h2>

        <p class="small">
            Dedicated pages for each file format, DJI model and comparison.
            Every guide opens the same free analyzer.
        </p>

        <h3>By file format</h3>
        <ul style="columns:2 260px;column-gap:28px;line-height:2;padding-left:20px;">
            <li><a href="/drone-flight-log-viewer" style="color:#60a5fa;text-decoration:none;">Drone flight log viewer</a></li>
            <li><a href="/drone-flight-log-to-pdf" style="color:#60a5fa;text-decoration:none;">Flight log to PDF report</a></li>
            <li><a href="/dji-flight-log" style="color:#60a5fa;text-decoration:none;">DJI flight log analyzer</a></li>
            <li><a href="/ardupilot-bin" style="color:#60a5fa;text-decoration:none;">ArduPilot .bin analyzer</a></li>
            <li><a href="/ardupilot-bin-viewer" style="color:#60a5fa;text-decoration:none;">ArduPilot .bin viewer</a></li>
            <li><a href="/px4-ulg" style="color:#60a5fa;text-decoration:none;">PX4 .ulg analyzer</a></li>
            <li><a href="/px4-ulg-viewer" style="color:#60a5fa;text-decoration:none;">PX4 .ulg viewer</a></li>
            <li><a href="/how-to-read-drone-flight-log" style="color:#60a5fa;text-decoration:none;">How to read a flight log</a></li>
        </ul>

        <h3>By DJI model</h3>
        <ul style="columns:2 260px;column-gap:28px;line-height:2;padding-left:20px;">
            <li><a href="/dji-mini-3-flight-log" style="color:#60a5fa;text-decoration:none;">DJI Mini 3 flight log</a></li>
            <li><a href="/dji-air-3-flight-log" style="color:#60a5fa;text-decoration:none;">DJI Air 3 flight log</a></li>
            <li><a href="/dji-mavic-3-flight-log" style="color:#60a5fa;text-decoration:none;">DJI Mavic 3 flight log</a></li>
            <li><a href="/dji-neo-flight-log" style="color:#60a5fa;text-decoration:none;">DJI Neo flight log</a></li>
        </ul>

        <h3>Comparisons</h3>
        <ul style="columns:2 260px;column-gap:28px;line-height:2;padding-left:20px;">
            <li><a href="/vs-airdata" style="color:#60a5fa;text-decoration:none;">vs AirData</a></li>
            <li><a href="/vs-flight-reader" style="color:#60a5fa;text-decoration:none;">vs Flight Reader</a></li>
            <li><a href="/vs-px4-review" style="color:#60a5fa;text-decoration:none;">vs PX4 Flight Review</a></li>
            <li><a href="/used-drone-battery-check" style="color:#60a5fa;text-decoration:none;">Checking a used drone</a></li>
        </ul>

    </section>


    <section
        class="card"
        style="margin-top:22px;font-size:14px;color:#94a3b8;line-height:1.7;"
    >

        <h3 style="margin:0 0 12px;color:#e2e8f0;">
            Privacy &amp; Data Retention
        </h3>

        <p style="margin:6px 0;">
            Your original flight log is processed only to generate
            your report and is deleted after processing.
        </p>

        <p style="margin:6px 0;">
            If you opt in to sharing, only a de-identified version
            (relative trajectory; no raw GPS or UTC time) may be
            retained for up to 30 days.
        </p>

        <p style="margin:6px 0;">
            Generated PDF and image files are automatically removed
            after a limited retention period.
        </p>

        <p style="margin:6px 0;">
            Wind information is a regional historical weather
            reference, not a local real-time measurement.
        </p>

    </section>

    <footer>

        <div class="footer-grid">

            <div>
                <h4>Formats</h4>
                <a href="/drone-flight-log-viewer">Drone flight log viewer</a>
                <a href="/drone-flight-log-to-pdf">Flight log to PDF</a>
                <a href="/dji-flight-log">DJI log analyzer</a>
                <a href="/ardupilot-bin">ArduPilot .bin</a>
                <a href="/px4-ulg">PX4 .ulg</a>
                <a href="/how-to-read-drone-flight-log">How to read a log</a>
            </div>

            <div>
                <h4>DJI models</h4>
                <a href="/dji-mini-3-flight-log">DJI Mini 3</a>
                <a href="/dji-air-3-flight-log">DJI Air 3</a>
                <a href="/dji-mavic-3-flight-log">DJI Mavic 3</a>
                <a href="/dji-neo-flight-log">DJI Neo</a>
            </div>

            <div>
                <h4>Compare</h4>
                <a href="/vs-airdata">vs AirData</a>
                <a href="/vs-flight-reader">vs Flight Reader</a>
                <a href="/vs-px4-review">vs PX4 Flight Review</a>
            </div>

            <div>
                <h4>Site</h4>
                <a href="/about">About</a>
                <a href="/methodology">Methodology</a>
                <a href="/sample-report">Sample report</a>
                <a href="/for-teams">For teams</a>
                <a href="/privacy">Privacy</a>
                <a href="/contact">Contact</a>
            </div>

        </div>

        <p class="footer-base">
            Drone Flight Report &middot; Free &middot; no sign-up &middot;
            privacy-first. Your raw log is deleted after processing.
    <br>
    &copy; 2026 Drone Flight Report &middot; All rights reserved.
    <br>
    <span style="font-size:12px;color:#475569;">
        Not affiliated with DJI, Autel Robotics, ArduPilot or PX4.
        Product names are trademarks of their respective owners.
    </span>
        </p>

    </footer>

</div>


<script>

const fileInput =
    document.getElementById("fileInput");

const fileName =
    document.getElementById("fileName");

const uploadBtn =
    document.getElementById("uploadBtn");

const uploadForm =
    document.getElementById("uploadForm");

const statusBox =
    document.getElementById("status");


fileInput.addEventListener(
    "change",
    function() {

        if (fileInput.files.length > 0) {

            fileName.textContent =
                fileInput.files[0].name;

            uploadBtn.disabled = false;

        } else {

            fileName.textContent = "";

            uploadBtn.disabled = true;

        }

    }
);


uploadForm.addEventListener(
    "submit",
    function() {

        uploadBtn.disabled = true;

        uploadBtn.textContent =
            "Generating...";

        statusBox.className = "status";

        statusBox.textContent = "";

    }
);

</script>

</body>
</html>
"""
# ============================================================
# Field name normalization
# ============================================================

def normalize_column_name(name):
    """
    Convert different column names into a comparable normalized form.
    """
    if name is None:
        return ""

    name = str(name).strip().lower()
    name = name.replace("°", "")

    name = re.sub(
        r"[^a-z0-9]+",
        "",
        name
    )

    return name


LAT_NAMES = {
    "lat",
    "latitude",
    "latitudedeg",
    "gpslat",
    "gpslatitude",
    "latitude_deg",
}

LON_NAMES = {
    "lon",
    "lng",
    "longitude",
    "longitudedeg",
    "gpslon",
    "gpslng",
    "gpslongitude",
    "longitude_deg",
}

DATETIME_NAMES = {
    "datetimeutc",
    "datetime",
    "dateutc",
    "utcdate",
    "timestamputc",
    "utctime",
    "timestamp",
    "time",
    "timeutc",
    "gpstime",
    "epoch",
    "epochtime",
    "utctimestamp",
}


def find_column(df, candidates, *, allow_substring=True):
    """Find a source column using normalized exact names first."""
    normalized = {col: normalize_column_name(col) for col in df.columns}
    candidate_set = {normalize_column_name(x) for x in candidates}

    for col, norm in normalized.items():
        if norm in candidate_set:
            return col

    if allow_substring:
        for col, norm in normalized.items():
            for candidate in candidate_set:
                if candidate and candidate in norm:
                    return col

    return None


def parse_altitude_column(df, altitude_col):
    """Convert an altitude source column to meters."""
    if altitude_col is None:
        return pd.Series(np.nan, index=df.index, dtype=float)

    normalized = normalize_column_name(altitude_col)
    altitude = pd.to_numeric(df[altitude_col], errors="coerce")

    if "feet" in normalized or normalized.endswith("ft"):
        return altitude / 3.28084

    return altitude


def find_lat_lon_alt_datetime(df):
    """Detect common GPS, altitude, UTC datetime and telemetry columns."""
    lat_col = find_column(df, LAT_NAMES)
    lon_col = find_column(df, LON_NAMES)
    datetime_col = find_column(df, DATETIME_NAMES, allow_substring=False)

    altitude_candidates = [
        "heightabovetakeofffeet", "heightabovetakeoffmeter", "heightabovetakeoffmeters",
        "heightabovegroundfeet", "heightabovegroundmeter", "heightabovegroundmeters",
        "relativealtitudefeet", "relativealtitudemeter", "relativealtitudemeters",
        "altitudefeet", "altitudemeter", "altitudemeters",
        "altitudeabovesealevelfeet", "altitudeabovesealevelmeter", "altitudeabovesealevelmeters",
        "altitude", "altitudem", "alt", "height", "heightm",
    ]
    altitude_col = find_column(df, altitude_candidates, allow_substring=True)

    elapsed_col = find_column(df, {"timemillisecond", "timems", "elapsedmilliseconds", "elapsedms"}, allow_substring=False)
    speed_col = find_column(df, {"speed", "speedmps", "speedms", "speedmpsground", "groundspeed", "speedkmh", "speedmph", "speedknots", "speedkt"}, allow_substring=True)
    heading_col = find_column(df, {"heading", "headingdeg", "headingtrue", "headingmagnetic", "course", "courseoverground", "yaw", "yawdeg", "track", "trackdeg"}, allow_substring=True)
    satellites_col = find_column(df, {"satellites", "gpssatellites", "nsats", "satellitesused"}, allow_substring=False)
    gps_quality_col = find_column(df, {"gpslevel", "gpsquality", "hdop", "fix", "fix_type", "fixtype"}, allow_substring=False)

    return {
        "latitude": lat_col,
        "longitude": lon_col,
        "altitude": altitude_col,
        "datetime": datetime_col,
        "elapsed": elapsed_col,
        "speed": speed_col,
        "heading": heading_col,
        "satellites": satellites_col,
        "gps_quality": gps_quality_col,
    }


def parse_csv_or_txt(path):
    """Read CSV/TXT telemetry using common encodings and separators."""
    encodings = ["utf-8-sig", "utf-8", "gb18030", "latin1"]
    separators = [",", "\t", ";"]
    last_error = None

    for encoding in encodings:
        for separator in separators:
            try:
                df = pd.read_csv(path, encoding=encoding, sep=separator)
                if len(df.columns) >= 2:
                    return df
            except Exception as exc:
                last_error = exc

    raise ValueError(f"Could not read CSV/TXT file: {last_error}")
GPS_FIX_OK = (2, 3, 4, 5, 6)
GPS_EPOCH = pd.Timestamp("1980-01-06", tz="UTC")
GPS_LEAP_SECONDS = 18


def _bin_attr(msg, *names):
    """Return the first attribute that exists on a DataFlash message."""
    for name in names:
        if hasattr(msg, name):
            value = getattr(msg, name)
            if value is not None:
                return value
    return None


def _bin_timestamp(msg):
    """UTC timestamp from GPS week + milliseconds, or None if untrustworthy.

    DFReader hands back GPS.GMS (ms into the GPS week) and GPS.GWk (week
    number). If the receiver never got UTC time these are 0, which used to
    produce a bogus 1980 date and an empty wind lookup.
    """
    week = _bin_attr(msg, "GWk", "Week")
    millis = _bin_attr(msg, "GMS")

    if week is None or millis is None:
        return None

    try:
        week = float(week)
        millis = float(millis)
    except (TypeError, ValueError):
        return None

    # GPS week 1000 is March 1999; anything lower is "no GPS time", not 1980.
    if not (1000 <= week <= 4000) or not (0 <= millis < 7 * 86400 * 1000):
        return None

    return (
        GPS_EPOCH
        + pd.to_timedelta(week, unit="W")
        + pd.to_timedelta(millis, unit="ms")
        - pd.Timedelta(seconds=GPS_LEAP_SECONDS)
    )


def _bin_row_from_gps(msg):
    """One canonical row from a GPS/GPS2 message, or None if unusable."""
    lat = float(_bin_attr(msg, "Lat"))
    lon = float(_bin_attr(msg, "Lng"))

    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    if abs(lat) < 1e-7 and abs(lon) < 1e-7:
        return None

    # A message without a fix carries Lat/Lng 0,0 (handled above) but also
    # Alt 0, NSats 0 and HDop 99.99. Keeping those rows creates phantom
    # altitude spikes and bogus "low satellites" warnings, so drop them.
    status = _bin_attr(msg, "Status")
    if status is not None:
        try:
            if int(status) not in GPS_FIX_OK:
                return None
        except (TypeError, ValueError):
            pass

    satellites = _bin_attr(msg, "NSats")
    if satellites is not None:
        try:
            if float(satellites) < 4:
                return None
        except (TypeError, ValueError):
            pass

    row = {
        "latitude": lat,
        "longitude": lon,
        "altitude_m": np.nan,
        "altitude_reference": "MSL",
    }

    # GPS.Alt is altitude above the WGS-84 ellipsoid in metres. DFReader has
    # already applied the centimetre scale factor declared in the FMT record,
    # so the value must NOT be divided again. Only a gross sanity check is
    # applied, for logs whose FMT record is missing unit letters.
    altitude = _bin_attr(msg, "Alt")
    if altitude is not None:
        try:
            altitude = float(altitude)
            if abs(altitude) > 60000:      # 60 km: impossible for a drone
                altitude /= 100.0          # raw centimetres, unscaled
            row["altitude_m"] = altitude
        except (TypeError, ValueError):
            pass

    timestamp = _bin_timestamp(msg)
    if timestamp is not None:
        row["timestamp_utc"] = timestamp

    time_us = _bin_attr(msg, "TimeUS")
    if time_us is not None:
        try:
            row["elapsed_seconds"] = float(time_us) / 1_000_000.0
        except (TypeError, ValueError):
            pass

    speed = _bin_attr(msg, "Spd")
    if speed is not None:
        try:
            row["speed_mps"] = float(speed)
        except (TypeError, ValueError):
            pass

    course = _bin_attr(msg, "GCrs")
    if course is not None:
        try:
            row["heading_deg"] = float(course)
        except (TypeError, ValueError):
            pass

    if satellites is not None:
        try:
            row["gps_satellites"] = float(satellites)
        except (TypeError, ValueError):
            pass

    hdop = _bin_attr(msg, "HDop")
    if hdop is not None:
        try:
            hdop = float(hdop)
            # 9999 is the ArduPilot "no fix" sentinel. Anything above 30 is
            # not a real dilution of precision, so leave it out rather than
            # reporting an HDOP of 100.
            if 0 < hdop <= 30:
                row["gps_quality"] = hdop
        except (TypeError, ValueError):
            pass

    return row


def _bin_row_from_pos(msg):
    """One canonical row from a POS (fused position) message."""
    lat = float(_bin_attr(msg, "Lat"))
    lon = float(_bin_attr(msg, "Lng"))

    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    if abs(lat) < 1e-7 and abs(lon) < 1e-7:
        return None

    row = {
        "latitude": lat,
        "longitude": lon,
        "altitude_m": np.nan,
        "altitude_reference": "MSL",
    }

    alt = _bin_attr(msg, "Alt")
    if alt is not None:
        try:
            row["altitude_m"] = float(alt)
        except (TypeError, ValueError):
            pass

    rel_home = _bin_attr(msg, "RelHomeAlt")
    if rel_home is not None:
        try:
            row["relative_altitude_m"] = float(rel_home)
        except (TypeError, ValueError):
            pass

    time_us = _bin_attr(msg, "TimeUS")
    if time_us is not None:
        try:
            row["elapsed_seconds"] = float(time_us) / 1_000_000.0
        except (TypeError, ValueError):
            pass

    speed = _bin_attr(msg, "Spd")
    if speed is not None:
        try:
            row["speed_mps"] = float(speed)
        except (TypeError, ValueError):
            pass

    return row


def parse_bin_log(path):
    """Parse an ArduPilot DataFlash .bin log.

    GPS/GPS2 is the preferred source. If the log never recorded a GPS
    message (indoor/bench logs, or a vehicle that never got a fix) the fused
    POS record is used instead, so the upload does not fail outright.
    """
    try:
        log = DFReader.DFReader_binary(path)
    except Exception as exc:
        raise ValueError(
            "This file could not be read as an ArduPilot DataFlash log "
            "(%s). If it is a DJI .DAT or a renamed text log, export it as "
            "CSV/TXT instead." % exc
        )

    gps_rows = []
    pos_rows = []

    while True:
        try:
            msg = log.recv_match(type=["GPS", "GPS2", "POS"], blocking=False)
        except Exception:
            break

        if msg is None:
            break

        kind = msg.get_type()

        try:
            row = _bin_row_from_pos(msg) if kind == "POS" else _bin_row_from_gps(msg)
        except Exception:
            row = None

        if row is None:
            continue

        if kind == "POS":
            pos_rows.append(row)
        else:
            gps_rows.append(row)

    rows = gps_rows or pos_rows

    if not rows:
        raise ValueError(
            "No usable position records were found in this .bin file. "
            "It contains neither a GPS/GPS2 fix nor a POS record, which "
            "usually means a bench log, a truncated copy, or a file that "
            "is not an ArduPilot DataFlash log."
        )

    df = pd.DataFrame(rows)

    # Logs whose FMT record omitted the centimetre unit letter come back 100x
    # too large. A drone cannot sit above 12 km for a whole flight.
    if df["altitude_m"].notna().any():
        if float(df["altitude_m"].abs().quantile(0.99)) > 12000:
            df["altitude_m"] = df["altitude_m"] / 100.0

    return df


def parse_ulg_log(path):
    """Parse PX4 ULog GPS data from common GPS topics."""

    ulog = ULog(path)

    dataset = None
    dataset_name = None

    # ---------------------------------------------------------
    # Find GPS dataset
    # ---------------------------------------------------------

    for name in [
        "vehicle_gps_position",
        "sensor_gps",
    ]:

        try:
            dataset = ulog.get_dataset(name)
            dataset_name = name
            break

        except Exception:
            continue

    if dataset is None:

        raise ValueError(
            "ULG file does not contain a supported GPS dataset."
        )

    data = dataset.data

    # ---------------------------------------------------------
    # Latitude / longitude
    # ---------------------------------------------------------

    if (
        "latitude_deg" in data
        and
        "longitude_deg" in data
    ):

        lat = pd.Series(
            data["latitude_deg"]
        )

        lon = pd.Series(
            data["longitude_deg"]
        )

    elif (
        "lat" in data
        and
        "lon" in data
    ):

        lat = (
            pd.Series(data["lat"])
            / 1e7
        )

        lon = (
            pd.Series(data["lon"])
            / 1e7
        )

    else:

        raise ValueError(
            "ULG GPS dataset does not contain "
            "supported latitude/longitude fields."
        )

    # ---------------------------------------------------------
    # Altitude
    # ---------------------------------------------------------

    if "altitude_msl_m" in data:

        altitude = pd.Series(
            data["altitude_msl_m"]
        )

    elif "alt" in data:

        # PX4 vehicle_gps_position.alt
        # is millimeters above mean sea level.
        altitude = (
            pd.Series(data["alt"])
            / 1000.0
        )

    elif "altitude" in data:

        altitude = pd.Series(
            data["altitude"]
        )

    else:

        altitude = pd.Series(
            np.nan,
            index=lat.index
        )

    # ---------------------------------------------------------
    # Base result
    # ---------------------------------------------------------

    result = pd.DataFrame({

        "latitude":
            lat,

        "longitude":
            lon,

        "altitude_m":
            altitude,

    })

    # ---------------------------------------------------------
    # GPS UTC time
    # ---------------------------------------------------------

    if "time_gps_usec" in data:

        result["timestamp_utc"] = pd.to_datetime(
            data["time_gps_usec"],
            unit="us",
            utc=True,
            errors="coerce"
        )

    elif "time_utc_usec" in data:

        result["timestamp_utc"] = pd.to_datetime(
            data["time_utc_usec"],
            unit="us",
            utc=True,
            errors="coerce"
        )

    else:

        result["timestamp_utc"] = pd.NaT

    # ---------------------------------------------------------
    # Elapsed time
    # ---------------------------------------------------------

    if "timestamp_position" in data:

        result["elapsed_seconds"] = (
            pd.to_numeric(
                pd.Series(
                    data["timestamp_position"]
                ),
                errors="coerce"
            )
            / 1_000_000.0
        )

    elif "timestamp" in data:

        result["elapsed_seconds"] = (
            pd.to_numeric(
                pd.Series(
                    data["timestamp"]
                ),
                errors="coerce"
            )
            / 1_000_000.0
        )

    # ---------------------------------------------------------
    # Speed
    # ---------------------------------------------------------

    if "vel_m_s" in data:

        result["speed_mps"] = pd.to_numeric(
            pd.Series(
                data["vel_m_s"]
            ),
            errors="coerce"
        )

    elif "vel" in data:

        vel = np.asarray(
            data["vel"]
        )

        if (
            vel.ndim == 2
            and
            vel.shape[1] >= 2
        ):

            result["speed_mps"] = np.sqrt(
                vel[:, 0] ** 2
                +
                vel[:, 1] ** 2
            )

    # ---------------------------------------------------------
    # Heading / course
    # ---------------------------------------------------------

    if "cog_rad" in data:

        values = pd.to_numeric(
            pd.Series(
                data["cog_rad"]
            ),
            errors="coerce"
        )

        result["heading_deg"] = np.degrees(
            values
        )

    elif "heading" in data:

        result["heading_deg"] = pd.to_numeric(
            pd.Series(
                data["heading"]
            ),
            errors="coerce"
        )

    # ---------------------------------------------------------
    # GPS satellites
    # ---------------------------------------------------------

    if "satellites_used" in data:

        result["gps_satellites"] = pd.to_numeric(
            pd.Series(
                data["satellites_used"]
            ),
            errors="coerce"
        )

    # ---------------------------------------------------------
    # GPS quality / fix type
    # ---------------------------------------------------------

    if "fix_type" in data:

        result["gps_quality"] = pd.to_numeric(
            pd.Series(
                data["fix_type"]
            ),
            errors="coerce"
        )

    # ---------------------------------------------------------
    # Return canonical parser output
    # ---------------------------------------------------------

    return result



def normalize_flight_data(raw_df):
    """Convert any supported parser output into the canonical schema."""
    df = raw_df.copy()

    # ---------------------------------------------------------
    # 1. Always start from a clean canonical dataframe
    # ---------------------------------------------------------
    fields = find_lat_lon_alt_datetime(df)

    # Latitude / longitude
    if "latitude" in df.columns and "longitude" in df.columns:
        latitude = pd.to_numeric(df["latitude"], errors="coerce")
        longitude = pd.to_numeric(df["longitude"], errors="coerce")
    else:
        if fields["latitude"] is None or fields["longitude"] is None:
            raise ValueError(
                "Could not find latitude and longitude columns in the flight log."
            )

        latitude = pd.to_numeric(
            df[fields["latitude"]],
            errors="coerce"
        )
        longitude = pd.to_numeric(
            df[fields["longitude"]],
            errors="coerce"
        )

    out = pd.DataFrame(index=df.index)

    out["latitude"] = latitude
    out["longitude"] = longitude

    # ---------------------------------------------------------
    # 2. Altitude -> meters
    # ---------------------------------------------------------
    if "altitude_m" in df.columns:
        out["altitude_m"] = pd.to_numeric(
            df["altitude_m"],
            errors="coerce"
        )

    elif fields["altitude"] is not None:
        out["altitude_m"] = parse_altitude_column(
            df,
            fields["altitude"]
        )

    else:
        out["altitude_m"] = np.nan

    # ---------------------------------------------------------
    # 3. UTC datetime
    # DJI AirData:
    # datetime(utc) -> timestamp_utc
    # ---------------------------------------------------------
    if "timestamp_utc" in df.columns:
        out["timestamp_utc"] = pd.to_datetime(
            df["timestamp_utc"],
            errors="coerce",
            utc=True
        )

    elif fields["datetime"] is not None:

        raw_time = df[fields["datetime"]]
        numeric_time = pd.to_numeric(raw_time, errors="coerce")

        if (
            numeric_time.notna().sum() > 0
            and numeric_time.dropna().abs().median() > 1e8
        ):
            magnitude = numeric_time.dropna().abs().median()
            if magnitude > 1e17:
                unit = "ns"
            elif magnitude > 1e14:
                unit = "us"
            elif magnitude > 1e11:
                unit = "ms"
            else:
                unit = "s"
            out["timestamp_utc"] = pd.to_datetime(
                numeric_time,
                unit=unit,
                errors="coerce",
                utc=True
            )
        else:
            out["timestamp_utc"] = pd.to_datetime(
                raw_time,
                errors="coerce",
                utc=True
            )

    else:
        out["timestamp_utc"] = pd.NaT

    # ---------------------------------------------------------
    # 4. Elapsed time
    # DJI AirData:
    # time(millisecond) -> elapsed_seconds
    # ---------------------------------------------------------
    if "elapsed_seconds" in df.columns:
        out["elapsed_seconds"] = pd.to_numeric(
            df["elapsed_seconds"],
            errors="coerce"
        )

    elif fields["elapsed"] is not None:
        out["elapsed_seconds"] = (
            pd.to_numeric(
                df[fields["elapsed"]],
                errors="coerce"
            ) / 1000.0
        )

    else:
        out["elapsed_seconds"] = np.nan

    # ---------------------------------------------------------
    # 5. Speed -> m/s
    # ---------------------------------------------------------
    if "speed_mps" in df.columns:
        out["speed_mps"] = pd.to_numeric(
            df["speed_mps"],
            errors="coerce"
        )

    elif fields["speed"] is not None:

        speed = pd.to_numeric(
            df[fields["speed"]],
            errors="coerce"
        )

        norm = normalize_column_name(
            fields["speed"]
        )

        # mph -> m/s
        if "mph" in norm:
            speed = speed * 0.44704

        # km/h -> m/s
        elif "kmh" in norm:
            speed = speed / 3.6

        # knots -> m/s
        elif "knot" in norm or norm.endswith("kt"):
            speed = speed * 0.514444

        # m/s (or unknown) -> unchanged
        out["speed_mps"] = speed

    else:
        out["speed_mps"] = np.nan

    # ---------------------------------------------------------
    # 6. Other optional fields
    # ---------------------------------------------------------
    for key, target in [
        ("heading", "heading_deg"),
        ("satellites", "gps_satellites"),
        ("gps_quality", "gps_quality"),
    ]:

        if fields[key] is not None:

            out[target] = pd.to_numeric(
                df[fields[key]],
                errors="coerce"
            )

        elif target in df.columns:

            out[target] = pd.to_numeric(
                df[target],
                errors="coerce"
            )

        else:

            out[target] = np.nan

    # ---------------------------------------------------------
    # 7. Clean GPS coordinates
    # ---------------------------------------------------------
    out["latitude"] = pd.to_numeric(
        out["latitude"],
        errors="coerce"
    )

    out["longitude"] = pd.to_numeric(
        out["longitude"],
        errors="coerce"
    )

    out["altitude_m"] = pd.to_numeric(
        out["altitude_m"],
        errors="coerce"
    )

    # ---------------------------------------------------------
    # 7a. Relative altitude (metres above the first valid sample)
    # MSL altitude is what the log records; pilots think in height
    # above the take-off point. Keep both, never silently swap them.
    # ---------------------------------------------------------
    if "relative_altitude_m" in df.columns:
        out["relative_altitude_m"] = pd.to_numeric(
            df["relative_altitude_m"],
            errors="coerce"
        )
    else:
        base_altitude = out["altitude_m"].dropna()
        if len(base_altitude):
            out["relative_altitude_m"] = (
                out["altitude_m"] - float(base_altitude.iloc[0])
            )
        else:
            out["relative_altitude_m"] = np.nan

    if "altitude_reference" in df.columns:
        out["altitude_reference"] = df["altitude_reference"]

    # Some logs store lat/lon as integers scaled by 1e7 (e.g. PX4 / MAVLink).
    lat_median = out["latitude"].dropna().abs().median()
    lon_median = out["longitude"].dropna().abs().median()
    if pd.notna(lat_median) and lat_median > 180:
        out["latitude"] = out["latitude"] / 1e7
    if pd.notna(lon_median) and lon_median > 180:
        out["longitude"] = out["longitude"] / 1e7

    out = out[
        out["latitude"].between(-90, 90)
        & out["longitude"].between(-180, 180)
    ].copy()

    if out.empty:
        raise ValueError(
            "No valid GPS coordinates were found in the flight log."
        )

    # ---------------------------------------------------------
    # 8. Normalize timestamp
    # ---------------------------------------------------------
    out["timestamp_utc"] = pd.to_datetime(
        out["timestamp_utc"],
        errors="coerce",
        utc=True
    )

    if out["timestamp_utc"].notna().any():
        out = out.sort_values(
            "timestamp_utc",
            kind="stable"
        )

    out = out.reset_index(drop=True)

    # ---------------------------------------------------------
    # 9. Normalize elapsed time
    # ---------------------------------------------------------
    out["elapsed_seconds"] = pd.to_numeric(
        out["elapsed_seconds"],
        errors="coerce"
    )

    if out["elapsed_seconds"].isna().all():

        if out["timestamp_utc"].notna().any():

            first = (
                out["timestamp_utc"]
                .dropna()
                .iloc[0]
            )

            out["elapsed_seconds"] = (
                out["timestamp_utc"] - first
            ).dt.total_seconds()

        else:

            out["elapsed_seconds"] = np.arange(
                len(out),
                dtype=float
            )

    # ---------------------------------------------------------
    # 10. Ensure optional numeric columns exist
    # ---------------------------------------------------------
    for col in [
        "speed_mps",
        "heading_deg",
        "gps_satellites",
        "gps_quality",
    ]:

        if col not in out.columns:
            out[col] = np.nan

        out[col] = pd.to_numeric(
            out[col],
            errors="coerce"
        )

    # ---------------------------------------------------------
    # 11. Relative altitude
    # ---------------------------------------------------------
    if out["altitude_m"].notna().any():

        first_altitude = (
            out["altitude_m"]
            .dropna()
            .iloc[0]
        )

        out["relative_altitude_m"] = (
            out["altitude_m"] - first_altitude
        )

    else:

        out["relative_altitude_m"] = np.nan

    # ---------------------------------------------------------
    # 12. Keep only canonical internal schema
    # ---------------------------------------------------------
    return out[[
        "timestamp_utc",
        "elapsed_seconds",
        "latitude",
        "longitude",
        "altitude_m",
        "relative_altitude_m",
        "speed_mps",
        "heading_deg",
        "gps_satellites",
        "gps_quality",
    ]]


def parse_flight_log(path):
    """Dispatch a flight log to its format-specific parser and normalize it."""
    extension = os.path.splitext(path)[1].lower()
    if extension in {".csv", ".txt"}:
        raw = parse_csv_or_txt(path)
    elif extension == ".bin":
        raw = parse_bin_log(path)
    elif extension == ".ulg":
        raw = parse_ulg_log(path)
    else:
        raise ValueError("Unsupported file type. Supported formats: CSV, TXT, BIN, ULG.")
    return normalize_flight_data(raw)



def validate_flight_data(df):
    """Reject structurally invalid flight data before analysis or plotting."""
    if len(df) < 2:
        raise ValueError("The flight log contains fewer than two valid GPS points.")

    lat_span = float(df["latitude"].max() - df["latitude"].min())
    lon_span = float(df["longitude"].max() - df["longitude"].min())
    if lat_span < 1e-9 and lon_span < 1e-9:
        raise ValueError("GPS coordinates do not show a usable flight trajectory.")

    if not df["latitude"].between(-90, 90).all() or not df["longitude"].between(-180, 180).all():
        raise ValueError("The flight log contains invalid GPS coordinates.")

    if "elapsed_seconds" not in df.columns:
        raise ValueError("Flight time could not be reconstructed.")

    return df


# =========================================================
# Flight statistics
# =========================================================

def haversine_distance(
    lat1,
    lon1,
    lat2,
    lon2
):

    radius = 6371000.0

    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)

    dphi = math.radians(
        lat2 - lat1
    )

    dlambda = math.radians(
        lon2 - lon1
    )


    a = (
        math.sin(dphi / 2) ** 2
        +
        math.cos(phi1)
        *
        math.cos(phi2)
        *
        math.sin(dlambda / 2) ** 2
    )


    return (
        2
        *
        radius
        *
        math.asin(
            math.sqrt(a)
        )
    )


def calculate_distance(df):
    """Calculate total horizontal flight distance in meters."""
    if len(df) < 2:
        return 0.0
    lat = df["latitude"].to_numpy(dtype=float)
    lon = df["longitude"].to_numpy(dtype=float)
    total = 0.0
    for i in range(1, len(df)):
        total += haversine_distance(lat[i-1], lon[i-1], lat[i], lon[i])
    return float(total)


def calculate_statistics(df):
    """Calculate report-level flight statistics from canonical data."""
    altitude = pd.to_numeric(df["altitude_m"], errors="coerce")
    relative = (
        pd.to_numeric(df["relative_altitude_m"], errors="coerce")
        if "relative_altitude_m" in df.columns
        else None
    )
    elapsed = pd.to_numeric(df["elapsed_seconds"], errors="coerce")
    speed = pd.to_numeric(df["speed_mps"], errors="coerce")
    distance_m = calculate_distance(df)

    duration = float(elapsed.max() - elapsed.min()) if elapsed.notna().any() else None
    reference = "MSL"
    if "altitude_reference" in df.columns:
        values = df["altitude_reference"].dropna()
        if len(values):
            reference = str(values.iloc[0])

    return {
        "points": int(len(df)),
        "distance_m": distance_m,
        "distance_km": distance_m / 1000.0,
        "duration_s": duration,
        "max_altitude": float(altitude.max()) if altitude.notna().any() else None,
        "min_altitude": float(altitude.min()) if altitude.notna().any() else None,
        "mean_altitude": float(altitude.mean()) if altitude.notna().any() else None,
        "altitude_reference": reference,
        "max_relative_altitude": (
            float(relative.max())
            if relative is not None and relative.notna().any()
            else None
        ),
        "min_relative_altitude": (
            float(relative.min())
            if relative is not None and relative.notna().any()
            else None
        ),
        "vertical_range": (
            float(relative.max() - relative.min())
            if relative is not None and relative.notna().any()
            else None
        ),
        "max_speed_mps": float(speed.max()) if speed.notna().any() else None,
    }


def _numeric_column(df, name):
    """Return a numeric Series for `name`, or None if the column is absent."""
    if name in df.columns:
        return pd.to_numeric(df[name], errors="coerce")
    return None


def detect_flight_health(df):
    """
    Lightweight, deterministic flight-health screen.

    Deliberately NOT machine learning: simple statistics over the canonical
    schema, which the literature shows is competitive for sparse anomalies
    (see research/uav-flight-log-papers-2026-10-14.md). Returns a 0-100 score
    plus human-readable flags.
    """
    flags = []
    metrics = {"points": int(len(df))}

    # GPS quality
    sats = _numeric_column(df, "gps_satellites")
    if sats is not None and sats.notna().any():
        metrics["min_satellites"] = float(sats.min())
        metrics["mean_satellites"] = round(float(sats.mean()), 1)
        if sats.min() < 5:
            flags.append("Low GPS satellite count (min %d)." % int(sats.min()))

    quality = _numeric_column(df, "gps_quality")
    if quality is not None and quality.notna().any():
        metrics["max_gps_quality"] = float(quality.max())
        if quality.max() > 5:
            flags.append("Poor GPS quality (HDOP/fix up to %.1f)." % quality.max())

    # Timeline gaps
    elapsed = _numeric_column(df, "elapsed_seconds")
    if elapsed is not None:
        elapsed = elapsed.dropna()
        if len(elapsed) > 2:
            diffs = elapsed.diff().dropna()
            diffs = diffs[diffs > 0]
            if len(diffs) > 0:
                median = float(diffs.median())
                metrics["median_sample_interval_s"] = round(median, 3)
                if median > 0:
                    gaps = int((diffs > max(5.0 * median, 5.0)).sum())
                    metrics["gaps"] = gaps
                    if gaps:
                        flags.append("%d timeline gap(s) detected." % gaps)

    # Altitude spikes
    altitude = _numeric_column(df, "altitude_m")
    if altitude is not None and altitude.notna().sum() > 2:
        span = float(altitude.max() - altitude.min())
        threshold = max(span * 0.5, 5.0)
        spikes = int((altitude.diff().abs() > threshold).sum())
        metrics["altitude_spikes"] = spikes
        if spikes:
            flags.append("%d abrupt altitude change(s)." % spikes)

    # Speed sanity
    speed = _numeric_column(df, "speed_mps")
    if speed is not None and speed.notna().any():
        metrics["max_speed_mps"] = round(float(speed.max()), 1)
        if speed.max() > 45:
            flags.append("Unusually high speed (%.1f m/s)." % speed.max())

    score = max(0, min(100, 100 - 15 * len(flags)))
    verdict = "healthy" if score >= 85 else ("review" if score >= 60 else "attention")

    return {
        "score": score,
        "verdict": verdict,
        "flags": flags,
        "metrics": metrics,
    }


# =========================================================
# Flight date
# =========================================================

def get_flight_date(df):
    """Return the actual UTC flight date, or None when unavailable."""
    if "timestamp_utc" not in df.columns:
        return None
    values = pd.to_datetime(df["timestamp_utc"], errors="coerce", utc=True).dropna()
    if values.empty:
        return None
    return values.iloc[0].strftime("%Y-%m-%d")


def parse_flight_date_override(value):
    """Validate the optional flight-date form field, or return None.

    Logs without GPS time (no satellite time fix, bench logs, some ArduPilot
    logs after a long power-off) cannot produce a date on their own. Letting
    the user type it restores the wind reference without guessing.
    """
    if not value:
        return None

    value = value.strip()
    if not value:
        return None

    try:
        parsed = datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None

    if parsed.year < 2000 or parsed > datetime.utcnow().date():
        return None

    return parsed.isoformat()
# =========================================================
# Wind data
# =========================================================

def get_wind_data(
    latitude,
    longitude,
    date_str
):

    """
    Get regional reference wind.

    Priority:

        1. Open-Meteo archive
        2. Open-Meteo forecast
        3. NASA POWER

    Returns:

        {
            "speed": ...,
            "direction": ...,
            "source": ...
        }
    """


    # -----------------------------------------------------
    # Open-Meteo archive
    # -----------------------------------------------------

    try:

        url = (
            "https://archive-api.open-meteo.com/v1/archive"
        )


        params = {

            "latitude":
                latitude,

            "longitude":
                longitude,

            "start_date":
                date_str,

            "end_date":
                date_str,

            "hourly":
                "wind_speed_10m,wind_direction_10m",

            "timezone":
                "UTC",
        }


        response = requests.get(
            url,
            params=params,
            timeout=15
        )


        response.raise_for_status()


        data = response.json()


        hourly = data.get(
            "hourly",
            {}
        )


        speeds = hourly.get(
            "wind_speed_10m",
            []
        )


        directions = hourly.get(
            "wind_direction_10m",
            []
        )


        if speeds:

            speed_values = [
                float(x)
                for x in speeds
                if x is not None
            ]


            direction_values = [
                float(x)
                for x in directions
                if x is not None
            ]


            if speed_values:

                speed = sum(
                    speed_values
                ) / len(
                    speed_values
                )


                if direction_values:

                    direction = sum(
                        direction_values
                    ) / len(
                        direction_values
                    )

                else:

                    direction = None


                return {

                    "speed":
                        speed,

                    "direction":
                        direction,

                    "source":
                        "Open-Meteo Archive",
                }


    except Exception:

        pass


    # -----------------------------------------------------
    # Open-Meteo forecast fallback
    # -----------------------------------------------------

    try:

        url = (
            "https://api.open-meteo.com/v1/forecast"
        )


        params = {

            "latitude":
                latitude,

            "longitude":
                longitude,

            "hourly":
                "wind_speed_10m,wind_direction_10m",

            "forecast_days":
                1,

            "timezone":
                "UTC",
        }


        response = requests.get(
            url,
            params=params,
            timeout=15
        )


        response.raise_for_status()


        data = response.json()


        hourly = data.get(
            "hourly",
            {}
        )


        speeds = hourly.get(
            "wind_speed_10m",
            []
        )


        directions = hourly.get(
            "wind_direction_10m",
            []
        )


        speed_values = [
            float(x)
            for x in speeds
            if x is not None
        ]


        direction_values = [
            float(x)
            for x in directions
            if x is not None
        ]


        if speed_values:

            speed = sum(
                speed_values
            ) / len(
                speed_values
            )


            direction = (
                sum(direction_values)
                / len(direction_values)
                if direction_values
                else None
            )


            return {

                "speed":
                    speed,

                "direction":
                    direction,

                "source":
                    "Open-Meteo Forecast",
            }


    except Exception:

        pass


    # -----------------------------------------------------
    # NASA POWER fallback
    # -----------------------------------------------------

    try:

        url = (
            "https://power.larc.nasa.gov/api/temporal/daily/point"
        )


        params = {

            "parameters":
                "WS10M",

            "community":
                "RE",

            "longitude":
                longitude,

            "latitude":
                latitude,

            "start":
                date_str.replace(
                    "-",
                    ""
                ),

            "end":
                date_str.replace(
                    "-",
                    ""
                ),

            "format":
                "JSON",
        }


        response = requests.get(
            url,
            params=params,
            timeout=15
        )


        response.raise_for_status()


        data = response.json()


        values = (
            data
            .get("properties", {})
            .get("parameter", {})
            .get("WS10M", {})
        )


        if values:

            raw_value = next(
                iter(values.values())
            )


            speed = float(
                raw_value
            )


            return {

                "speed":
                    speed,

                "direction":
                    None,

                "source":
                    "NASA POWER",
            }


    except Exception:

        pass


    return {

        "speed":
            None,

        "direction":
            None,

        "source":
            "Unavailable",
    }


# =========================================================
# Wind direction -> U/V
# =========================================================

def wind_to_uv(
    speed,
    direction
):

    if (
        speed is None
        or direction is None
    ):

        return 0.0, 0.0


    radians = math.radians(
        direction
    )


    # Meteorological direction:
    # direction wind comes FROM.
    #
    # Convert into vector pointing TO.

    u = (
        -speed
        * math.sin(radians)
    )


    v = (
        -speed
        * math.cos(radians)
    )


    return u, v
def get_wind_field(df, flight_date, grid_size=7):
    """
    Generate a regional macro wind field around the flight path.

    Returns:
        {
            "speed": average wind speed,
            "direction": average wind direction,
            "source": data source,
            "grid": [
                {
                    "lat": ...,
                    "lon": ...,
                    "u": ...,
                    "v": ...,
                    "speed": ...,
                    "direction": ...
                }
            ]
        }
    """

    if not flight_date:
        return {"speed": None, "direction": None, "source": "Unavailable: flight date not available", "grid": []}

    try:
        lat_min = float(df["latitude"].min())
        lat_max = float(df["latitude"].max())
        lon_min = float(df["longitude"].min())
        lon_max = float(df["longitude"].max())

        # Add a little padding around the flight area
        lat_span = lat_max - lat_min
        lon_span = lon_max - lon_min

        if lat_span == 0:
            lat_span = 0.01

        if lon_span == 0:
            lon_span = 0.01

        lat_pad = max(lat_span * 0.15, 0.001)
        lon_pad = max(lon_span * 0.15, 0.001)

        lat_min -= lat_pad
        lat_max += lat_pad
        lon_min -= lon_pad
        lon_max += lon_pad

        # Create grid
        lat_values = [
            lat_min + (lat_max - lat_min) * i / (grid_size - 1)
            for i in range(grid_size)
        ]

        lon_values = [
            lon_min + (lon_max - lon_min) * i / (grid_size - 1)
            for i in range(grid_size)
        ]

        grid_points = []

        for lat in lat_values:
            for lon in lon_values:
                grid_points.append((lat, lon))

        # Multiple locations in ONE Open-Meteo request
        latitudes = ",".join(
            f"{lat:.6f}" for lat, lon in grid_points
        )

        longitudes = ",".join(
            f"{lon:.6f}" for lat, lon in grid_points
        )

        url = "https://archive-api.open-meteo.com/v1/archive"

        params = {
            "latitude": latitudes,
            "longitude": longitudes,
            "start_date": flight_date,
            "end_date": flight_date,
            "hourly": "wind_speed_10m,wind_direction_10m",
            "wind_speed_unit": "ms",
            "timezone": "UTC",
        }

        response = requests.get(
            url,
            params=params,
            timeout=30
        )

        response.raise_for_status()

        data = response.json()

        # Multiple coordinates return a list
        if not isinstance(data, list):
            data = [data]

        grid = []

        all_u = []
        all_v = []

        for i, location in enumerate(data):

            if i >= len(grid_points):
                break

            lat, lon = grid_points[i]

            hourly = location.get("hourly", {})

            speeds = hourly.get("wind_speed_10m", [])
            directions = hourly.get("wind_direction_10m", [])

            valid_u = []
            valid_v = []

            for speed, direction in zip(speeds, directions):

                if speed is None or direction is None:
                    continue

                speed = float(speed)
                direction = float(direction)

                # Open-Meteo direction means the direction
                # FROM which the wind is blowing.
                # Convert to the vector direction the wind is GOING.
                radians = math.radians(direction)

                u = -speed * math.sin(radians)
                v = -speed * math.cos(radians)

                valid_u.append(u)
                valid_v.append(v)

            if not valid_u:
                continue

            u_mean = sum(valid_u) / len(valid_u)
            v_mean = sum(valid_v) / len(valid_v)

            speed_mean = math.sqrt(
                u_mean ** 2 + v_mean ** 2
            )

            direction_mean = (
                math.degrees(
                    math.atan2(-u_mean, -v_mean)
                ) + 360
            ) % 360

            grid.append({
                "lat": lat,
                "lon": lon,
                "u": u_mean,
                "v": v_mean,
                "speed": speed_mean,
                "direction": direction_mean,
            })

            all_u.append(u_mean)
            all_v.append(v_mean)

        if not grid:
            raise ValueError(
                "No valid wind data returned."
            )

        # Regional average vector
        mean_u = sum(all_u) / len(all_u)
        mean_v = sum(all_v) / len(all_v)

        mean_speed = math.sqrt(
            mean_u ** 2 + mean_v ** 2
        )

        mean_direction = (
            math.degrees(
                math.atan2(-mean_u, -mean_v)
            ) + 360
        ) % 360

        return {
            "speed": mean_speed,
            "direction": mean_direction,
            "source": "Open-Meteo Historical Weather",
            "grid": grid,
        }

    except Exception as e:

        print(
            "Wind field error:",
            repr(e)
        )

        return {
            "speed": None,
            "direction": None,
            "source": "Unavailable",
            "grid": [],
        }

WIND_LEVELS_M = [10, 80, 120, 180]


def _open_meteo_wind_levels(lat, lon, date_str):
    """Daily-mean wind at several heights from Open-Meteo (vector direction)."""
    hourly = ",".join(
        "wind_speed_{0}m,wind_direction_{0}m".format(h) for h in WIND_LEVELS_M
    )
    response = requests.get(
        "https://archive-api.open-meteo.com/v1/archive",
        params={
            "latitude": lat,
            "longitude": lon,
            "start_date": date_str,
            "end_date": date_str,
            "hourly": hourly,
            "wind_speed_unit": "ms",
            "timezone": "UTC",
        },
        timeout=25,
    )
    response.raise_for_status()
    hourly_data = response.json().get("hourly", {})

    levels = {}
    for height in WIND_LEVELS_M:
        speeds = [
            x for x in hourly_data.get("wind_speed_{0}m".format(height), [])
            if x is not None
        ]
        directions = [
            x for x in hourly_data.get("wind_direction_{0}m".format(height), [])
            if x is not None
        ]
        if not speeds:
            continue
        scalar = sum(speeds) / len(speeds)
        u = v = 0.0
        n = min(len(speeds), len(directions))
        if n:
            for speed, direction in zip(speeds, directions):
                rad = math.radians(direction)
                u += -speed * math.sin(rad)
                v += -speed * math.cos(rad)
            u /= n
            v /= n
            direction_mean = (math.degrees(math.atan2(-u, -v)) + 360) % 360
        else:
            direction_mean = None
        levels[height] = {
            "speed": scalar,
            "u": u,
            "v": v,
            "direction": direction_mean,
        }
    return levels


def _altitude_weights(df, heights):
    """Fraction of flight time spent nearest each available height band."""
    if not heights:
        return {}
    altitude = pd.to_numeric(
        df["relative_altitude_m"], errors="coerce"
    ).dropna()
    if altitude.empty:
        return {h: 1.0 / len(heights) for h in heights}
    ordered = sorted(heights)
    counts = dict.fromkeys(ordered, 0)
    for value in altitude:
        nearest = min(ordered, key=lambda h: abs(h - value))
        counts[nearest] += 1
    total = sum(counts.values()) or 1
    return {h: counts[h] / total for h in ordered}


def get_wind_levels(df, flight_date):
    """
    Wind at several altitudes, weighted by how long the flight spent at each
    height (multi-level weighting). Returns per-level values plus one
    flight-weighted wind vector.
    """
    empty = {"levels": [], "weighted_speed": None, "weighted_direction": None}
    if not flight_date:
        return empty
    try:
        lat = float(df["latitude"].mean())
        lon = float(df["longitude"].mean())
        raw = _open_meteo_wind_levels(lat, lon, flight_date)
    except Exception:
        return empty
    if not raw:
        return empty

    heights = list(raw.keys())
    weights = _altitude_weights(df, heights)

    rows = []
    u_sum = 0.0
    v_sum = 0.0
    for height in heights:
        weight = weights.get(height, 0.0)
        level = raw[height]
        rows.append({
            "alt_m": height,
            "speed_mps": level["speed"],
            "direction": level["direction"],
            "weight": weight,
        })
        u_sum += level["u"] * weight
        v_sum += level["v"] * weight

    weighted_speed = math.sqrt(u_sum ** 2 + v_sum ** 2)
    weighted_direction = (math.degrees(math.atan2(-u_sum, -v_sum)) + 360) % 360

    return {
        "levels": rows,
        "weighted_speed": weighted_speed,
        "weighted_direction": weighted_direction,
    }


def get_wind_ensemble(df, flight_date, grid_size=6):
    """
    Multi-source regional wind.

    Starts from the Open-Meteo grid field, then adds an independent estimate
    from NASA POWER and returns an ensemble mean + spread. More than one model
    means we can report how much the sources agree (a crude confidence signal).
    """
    field = get_wind_field(df, flight_date, grid_size=grid_size)

    sources = []
    if field.get("speed") is not None:
        sources.append(("Open-Meteo", float(field["speed"])))

    if flight_date:
        try:
            lat = float(df["latitude"].mean())
            lon = float(df["longitude"].mean())
            ymd = flight_date.replace("-", "")
            response = requests.get(
                "https://power.larc.nasa.gov/api/temporal/daily/point",
                params={
                    "parameters": "WS10M",
                    "community": "RE",
                    "longitude": lon,
                    "latitude": lat,
                    "start": ymd,
                    "end": ymd,
                    "format": "JSON",
                },
                timeout=15,
            )
            response.raise_for_status()
            values = (
                response.json()
                .get("properties", {})
                .get("parameter", {})
                .get("WS10M", {})
            )
            if values:
                sources.append(("NASA POWER", float(next(iter(values.values())))))
        except Exception:
            pass

    speeds = [speed for _, speed in sources if speed is not None]
    field["sources"] = sources
    if speeds:
        field["speed_ensemble"] = sum(speeds) / len(speeds)
        field["spread"] = max(speeds) - min(speeds)
    else:
        field["speed_ensemble"] = None
        field["spread"] = None

    profile = get_wind_levels(df, flight_date)
    field["levels"] = profile.get("levels", [])
    field["weighted_speed"] = profile.get("weighted_speed")
    field["weighted_direction"] = profile.get("weighted_direction")
    return field


# =========================================================
# Helpers
# =========================================================

def direction_to_chinese(direction):
    """Convert a meteorological wind direction (the direction wind comes
    FROM) into an easy-to-read 8-point Chinese compass label."""
    if direction is None:
        return None

    direction = float(direction) % 360
    directions = ["北", "东北", "东", "东南", "南", "西南", "西", "西北"]
    index = int(((direction + 22.5) % 360) // 45)
    return directions[index]


# =========================================================
# Generate flight plot
# =========================================================

def generate_flight_plot(df, wind):
    """Plot the real flight path and a separate regional wind reference field in local meters."""
    fig, ax = plt.subplots(figsize=(10, 7))

    lat0 = math.radians(float(df.iloc[0]["latitude"]))
    lon0 = math.radians(float(df.iloc[0]["longitude"]))
    radius = 6371000.0
    lat = np.radians(df["latitude"].to_numpy(dtype=float))
    lon = np.radians(df["longitude"].to_numpy(dtype=float))
    x = (lon - lon0) * math.cos(lat0) * radius
    y = (lat - lat0) * radius

    ax.plot(x, y, linewidth=2.2, label="Flight path")
    ax.scatter(x[0], y[0], s=80, marker="o", label="Start")
    ax.scatter(x[-1], y[-1], s=80, marker="X", label="End")

    grid = wind.get("grid", []) if wind else []
    if grid:
        grid_lats = np.array([float(p["lat"]) for p in grid])
        grid_lons = np.array([float(p["lon"]) for p in grid])
        grid_x = (np.radians(grid_lons) - lon0) * math.cos(lat0) * radius
        grid_y = (np.radians(grid_lats) - lat0) * radius
        us = np.array([float(p["u"]) for p in grid])
        vs = np.array([float(p["v"]) for p in grid])
        speeds = np.array([max(float(p.get("speed", 0)), 0.0) for p in grid])
        max_speed = max(float(speeds.max()) if len(speeds) else 0.0, 0.1)
        plot_span = max(float(np.ptp(x)), float(np.ptp(y)), 20.0)
        arrow_length = plot_span * 0.08
        arrow_u = us / max_speed * arrow_length
        arrow_v = vs / max_speed * arrow_length

        ax.quiver(
            grid_x, grid_y, arrow_u, arrow_v,
            angles="xy", scale_units="xy", scale=1,
            width=0.0025, headwidth=3.5, headlength=4.5,
            headaxislength=3.8, alpha=0.60,
        )

    if wind and wind.get("speed") is not None and wind.get("direction") is not None:
        ax.text(
            0.02, 0.97,
            f"Regional wind reference: {float(wind['speed']) * 3.6:.1f} km/h @ {float(wind['direction']):.0f}°",
            transform=ax.transAxes, va="top", fontsize=10,
        )
    else:
        ax.text(0.02, 0.97, "Regional wind reference unavailable", transform=ax.transAxes, va="top", fontsize=10)

    ax.set_title("Drone Flight Path + Regional Wind Reference")
    ax.set_xlabel("East-West distance from start (m)")
    ax.set_ylabel("North-South distance from start (m)")
    ax.grid(True, alpha=0.25)
    ax.set_aspect("equal", adjustable="box")
    ax.legend()
    fig.tight_layout()

    filename = f"flight_{uuid.uuid4().hex}.png"
    filepath = os.path.join(GENERATED_DIR, filename)
    fig.savefig(filepath, dpi=180, bbox_inches="tight")
    plt.close(fig)
    return filename


# =========================================================
# PDF report
# =========================================================

def generate_pdf_report(
    df,
    stats,
    wind,
    image_path,
    flight_date=None,
    health=None,
    report_context=None,
):
    """Generate a professional, source-aware multi-page flight report."""
    filename = f"flight_report_{uuid.uuid4().hex}.pdf"
    pdf_path = os.path.join(GENERATED_DIR, filename)
    c = canvas.Canvas(pdf_path, pagesize=A4)
    width, height = A4
    margin = 42
    navy = colors.HexColor("#0f172a")
    blue = colors.HexColor("#2563eb")
    muted = colors.HexColor("#64748b")
    light = colors.HexColor("#e2e8f0")

    def footer(page_no):
        c.setStrokeColor(light)
        c.line(margin, 30, width - margin, 30)
        c.setFillColor(muted)
        c.setFont("Helvetica", 7.5)
        c.drawString(margin, 18, "Drone Flight Report | Source-aware analytics")
        c.drawRightString(width - margin, 18, f"Page {page_no}")

    def header(title, subtitle=None):
        c.setFillColor(navy)
        c.setFont("Helvetica-Bold", 18)
        c.drawString(margin, height - 52, title)
        if subtitle:
            c.setFillColor(muted)
            c.setFont("Helvetica", 8.5)
            c.drawString(margin, height - 68, subtitle)

    def value(value, suffix=""):
        return "Unavailable" if value is None else f"{value}{suffix}"

    def measurement(value, suffix="", decimals=1):
        if value is None:
            return "Unavailable"
        try:
            return f"{float(value):.{decimals}f}{suffix}"
        except (TypeError, ValueError):
            return "Unavailable"

    def pdf_text(value, max_length=92):
        text = clean_form_text(value, max_length)
        return text.encode("latin-1", "replace").decode("latin-1")

    def kpi(x, y, w, label, text):
        c.setFillColor(colors.HexColor("#f8fafc"))
        c.roundRect(x, y, w, 58, 7, fill=1, stroke=0)
        c.setFillColor(muted)
        c.setFont("Helvetica", 8)
        c.drawString(x + 10, y + 39, label.upper())
        c.setFillColor(navy)
        c.setFont("Helvetica-Bold", 14)
        c.drawString(x + 10, y + 17, text)

    def chart_series(name):
        if name not in df.columns:
            return [], [], "Sample index"
        values = pd.to_numeric(df[name], errors="coerce")
        if "elapsed_seconds" in df.columns:
            x_values = pd.to_numeric(df["elapsed_seconds"], errors="coerce")
            mask = values.notna() & x_values.notna()
            x_values = x_values[mask].tolist()
            values = values[mask].tolist()
            x_label = "Elapsed time (s)"
        else:
            mask = values.notna()
            values = values[mask].tolist()
            x_values = list(range(len(values)))
            x_label = "Sample index"
        if len(values) > 180:
            step = max(1, len(values) // 180)
            x_values, values = x_values[::step], values[::step]
        return [float(v) for v in x_values], [float(v) for v in values], x_label

    def line_chart(x, y, w, h, title, x_values, values, colour=blue, unit="", x_label="Sample index"):
        c.setFillColor(navy)
        c.setFont("Helvetica-Bold", 10)
        c.drawString(x, y + h + 16, title)
        c.setStrokeColor(light)
        c.rect(x, y, w, h, fill=0, stroke=1)
        if not values:
            c.setFillColor(muted)
            c.setFont("Helvetica", 9)
            c.drawCentredString(x + w / 2, y + h / 2, "No recorded data")
            return
        plot_x, plot_y = x + 44, y + 28
        plot_w, plot_h = w - 58, h - 48
        lo, hi = min(values), max(values)
        if hi == lo:
            hi = lo + 1.0
        x_lo, x_hi = min(x_values), max(x_values)
        if x_hi == x_lo:
            x_hi = x_lo + 1.0
        c.setStrokeColor(colors.HexColor("#e2e8f0"))
        c.setLineWidth(0.5)
        for tick in range(5):
            ratio = tick / 4.0
            gy = plot_y + ratio * plot_h
            c.line(plot_x, gy, plot_x + plot_w, gy)
            label = lo + ratio * (hi - lo)
            c.setFillColor(muted)
            c.setFont("Helvetica", 7)
            c.drawRightString(plot_x - 6, gy - 2, f"{label:.1f}{unit}")
        for tick in range(5):
            ratio = tick / 4.0
            gx = plot_x + ratio * plot_w
            c.line(gx, plot_y, gx, plot_y + plot_h)
            label = x_lo + ratio * (x_hi - x_lo)
            c.setFillColor(muted)
            c.setFont("Helvetica", 7)
            c.drawCentredString(gx, y + 15, f"{label:.0f}")
        points = []
        for i, val in enumerate(values):
            px = plot_x + ((x_values[i] - x_lo) / (x_hi - x_lo)) * plot_w
            py = plot_y + ((val - lo) / (hi - lo)) * plot_h
            points.append((px, py))
        c.setStrokeColor(colour)
        c.setLineWidth(1.6)
        path = c.beginPath()
        path.moveTo(*points[0])
        for px, py in points[1:]:
            path.lineTo(px, py)
        c.drawPath(path)
        c.setFillColor(muted)
        c.setFont("Helvetica", 7.5)
        c.drawCentredString(plot_x + plot_w / 2, y + 3, x_label)
        c.saveState()
        c.translate(x + 10, plot_y + plot_h / 2)
        c.rotate(90)
        c.drawCentredString(0, 0, title + (f" ({unit})" if unit else ""))
        c.restoreState()

    # Page 1: Flight Summary
    header("Flight Summary", "Generated from the uploaded flight log")
    c.setFillColor(muted)
    c.setFont("Helvetica", 9)
    c.drawString(margin, height - 94, f"Flight date: {flight_date or 'Unavailable'}")
    report_context = report_context or {}
    primary_context = " | ".join(
        item for item in [
            pdf_text(report_context.get("organization")),
            pdf_text(report_context.get("project")),
        ] if item
    )
    secondary_context = " | ".join(
        item for item in [
            pdf_text(report_context.get("aircraft")),
            pdf_text(report_context.get("pilot")),
            pdf_text(report_context.get("client_reference")),
        ] if item
    )
    if primary_context:
        c.drawString(margin, height - 110, primary_context[:110])
    if secondary_context:
        c.drawString(margin, height - 126, secondary_context[:110])
    kpi(margin, height - 175, 120, "Distance", f"{stats['distance_km']:.2f} km")
    kpi(margin + 132, height - 175, 120, "Duration", value(round(stats['duration_s'], 1) if stats.get('duration_s') is not None else None, " s"))
    kpi(margin + 264, height - 175, 120, "Samples", str(stats['points']))
    kpi(margin + 396, height - 175, 120, "Max speed", value(round(stats['max_speed_mps'], 1) if stats.get('max_speed_mps') is not None else None, " m/s"))
    c.setFillColor(navy)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(margin, height - 215, "Altitude")
    c.setFillColor(muted)
    c.setFont("Helvetica", 10)
    reference = stats.get("altitude_reference", "MSL")
    c.drawString(margin, height - 235, f"Reference: {reference}")
    c.drawString(margin, height - 253, f"Minimum: {measurement(stats.get('min_altitude'), ' m')}")
    c.drawString(margin, height - 271, f"Mean: {measurement(stats.get('mean_altitude'), ' m')}")
    c.drawString(margin, height - 289, f"Maximum: {measurement(stats.get('max_altitude'), ' m')}")
    c.setFillColor(navy)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(margin + 220, height - 215, "Wind reference")
    c.setFillColor(muted)
    c.setFont("Helvetica", 10)
    if wind.get("speed") is not None:
        c.drawString(margin + 220, height - 235, f"Speed: {float(wind['speed']) * 3.6:.1f} km/h")
        c.drawString(margin + 220, height - 253, f"Direction: {value(wind.get('direction'), ' deg')}")
        c.drawString(margin + 220, height - 271, f"Source: {wind.get('source', 'Regional model')}")
    else:
        c.drawString(margin + 220, height - 235, "Wind data unavailable")
    c.setFillColor(colors.HexColor("#eff6ff"))
    c.roundRect(margin, height - 390, width - 2 * margin, 72, 8, fill=1, stroke=0)
    c.setFillColor(navy)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(margin + 14, height - 344, "Interpretation note")
    c.setFillColor(muted)
    c.setFont("Helvetica", 8.5)
    c.drawString(margin + 14, height - 362, "Wind values are labeled by source. Regional/model wind is not a direct onboard measurement")
    c.drawString(margin + 14, height - 376, "and must not be read as a high-resolution local CFD result.")
    footer(1)
    c.showPage()

    # Page 2: trajectory
    header("Flight Trajectory", "Recorded path with regional wind context")
    if image_path and os.path.exists(image_path):
        image = ImageReader(image_path)
        c.drawImage(image, margin, 150, width=width - 2 * margin, height=height - 290,
                    preserveAspectRatio=True, anchor="c", mask="auto")
    else:
        c.setFillColor(muted)
        c.setFont("Helvetica", 10)
        c.drawCentredString(width / 2, height / 2, "Trajectory image unavailable")
    c.setFillColor(muted)
    c.setFont("Helvetica", 8)
    c.drawString(margin, 125, "The plotted trajectory is derived from recorded latitude/longitude samples only.")
    footer(2)
    c.showPage()

    # Page 3: altitude and telemetry
    header("Altitude Analysis", "Recorded telemetry trends")
    altitude_x, altitude_values, x_label = chart_series("altitude_m")
    speed_x, speed_values, speed_x_label = chart_series("speed_mps")
    line_chart(margin, height - 300, width - 2 * margin, 170, "Altitude", altitude_x, altitude_values, blue, " m", x_label)
    line_chart(margin, height - 535, width - 2 * margin, 170, "Speed", speed_x, speed_values, colors.HexColor("#0f766e"), " m/s", speed_x_label)
    footer(3)
    c.showPage()

    # Page 4: wind analysis
    header("Wind Analysis", "Source-aware wind interpretation")
    c.setFillColor(navy)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(margin, height - 100, "Along-flight wind reference")
    c.setFillColor(muted)
    c.setFont("Helvetica", 9)
    wind_lines = [
        f"Reference speed: {float(wind['speed']) * 3.6:.1f} km/h" if wind.get("speed") is not None else "Reference speed: Unavailable",
        f"Reference direction: {value(wind.get('direction'), ' deg')}",
        f"Primary source: {wind.get('source', 'Unavailable')}",
        f"Grid samples: {len(wind.get('grid', []))}",
    ]
    for i, line in enumerate(wind_lines):
        c.drawString(margin, height - 122 - i * 18, line)
    c.setFillColor(navy)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(margin, height - 220, "Source classification")
    c.setFillColor(muted)
    c.setFont("Helvetica", 9)
    c.drawString(margin, height - 242, "Recorded onboard wind: only shown when present in the log schema.")
    c.drawString(margin, height - 260, "Model/reference wind: external regional estimate, labeled as such.")
    c.drawString(margin, height - 278, "Missing wind: shown as unavailable; no value is inferred from silence.")
    levels = wind.get("levels") or []
    c.setFillColor(navy)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(margin, height - 330, "Available wind levels")
    c.setFont("Helvetica", 8.5)
    c.setFillColor(muted)
    c.drawString(margin, height - 348, "Altitude (m)")
    c.drawString(margin + 120, height - 348, "Speed (m/s)")
    c.drawString(margin + 240, height - 348, "Direction")
    for i, level in enumerate(levels[:10]):
        y = height - 366 - i * 16
        c.drawString(margin, y, str(level.get("alt_m", "-")))
        c.drawString(margin + 120, y, str(level.get("speed", "-")))
        c.drawString(margin + 240, y, str(level.get("direction", "-")))
    footer(4)
    c.showPage()

    # Page 5: vertical wind profile
    header("Vertical Wind Profile", "Height-dependent wind reference")
    profile = {"levels": [], "source": None}
    if flight_date and len(df):
        try:
            profile = get_wind_profile(float(df["latitude"].mean()), float(df["longitude"].mean()), flight_date,
                                       base_speed=wind.get("speed"), base_direction=wind.get("direction"))
        except Exception:
            profile = {"levels": [], "source": None}
    levels = profile.get("levels") or []
    if len(levels) >= 2:
        x, y, w, h = margin + 36, 180, width - 2 * margin - 70, 330
        max_alt = max(float(item["alt_m"]) for item in levels) or 1.0
        max_speed = max(float(item["speed"]) for item in levels) or 1.0
        c.setStrokeColor(light)
        c.rect(x, y, w, h, fill=0, stroke=1)
        pts = []
        for item in levels:
            px = x + float(item["speed"]) / max_speed * w
            py = y + float(item["alt_m"]) / max_alt * h
            pts.append((px, py))
        c.setStrokeColor(colors.HexColor("#7c3aed"))
        c.setLineWidth(2)
        path = c.beginPath()
        path.moveTo(*pts[0])
        for pt in pts[1:]:
            path.lineTo(*pt)
        c.drawPath(path)
        c.setFillColor(muted)
        c.setFont("Helvetica", 8)
        c.drawString(x, y - 16, "0 m/s")
        c.drawRightString(x + w, y - 16, f"{max_speed:.1f} m/s")
        c.drawString(x - 34, y, "0 m")
        c.drawString(x - 34, y + h - 3, f"{max_alt:.0f} m")
        c.drawString(margin, 125, f"Profile source: {profile.get('source') or 'Unavailable'}")
    else:
        c.setFillColor(muted)
        c.setFont("Helvetica", 10)
        c.drawCentredString(width / 2, height / 2, "Vertical wind profile unavailable")
    footer(5)
    c.showPage()

    # Page 6: quality and methodology
    header("Data Quality & Methodology", "Coverage, limitations and reproducibility")
    c.setFillColor(navy)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(margin, height - 100, "Recorded field coverage")
    c.setFont("Helvetica", 9)
    fields = [("Latitude", "latitude"), ("Longitude", "longitude"), ("Altitude", "altitude_m"),
              ("Speed", "speed_mps"), ("Timestamp", "timestamp_utc"), ("Battery", "battery_percent")]
    for i, (label, col) in enumerate(fields):
        present = 0
        if col in df.columns:
            present = int(pd.Series(df[col]).notna().sum())
        pct = present / max(len(df), 1) * 100.0
        y = height - 126 - i * 22
        c.setFillColor(muted)
        c.drawString(margin, y, label)
        c.setFillColor(navy)
        c.drawRightString(width - margin, y, f"{present}/{len(df)} ({pct:.0f}%)")
        c.setStrokeColor(light)
        c.line(margin, y - 6, width - margin, y - 6)
    c.setFillColor(navy)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(margin, height - 295, "Methodology")
    c.setFillColor(muted)
    c.setFont("Helvetica", 8.5)
    notes = [
        "Flight statistics are calculated from the canonical parsed log schema.",
        "The trajectory uses recorded latitude and longitude samples; no path is invented between missing samples.",
        "Altitude and speed charts omit unavailable samples rather than filling them silently.",
        "Wind values are separated into recorded onboard data, external model/reference data, or unavailable data.",
        "Vertical profiles are marked as pressure-level model data or power-law estimates when applicable.",
    ]
    for i, note in enumerate(notes):
        c.drawString(margin, height - 320 - i * 18, "- " + note)
    if health:
        c.setFillColor(navy)
        c.setFont("Helvetica-Bold", 11)
        c.drawString(margin, height - 435, "Flight health")
        c.setFillColor(muted)
        c.setFont("Helvetica", 9)
        c.drawString(margin, height - 455, f"Score: {health.get('score', 'Unavailable')} | Verdict: {health.get('verdict', 'Unavailable')}")
        for i, flag in enumerate((health.get("flags") or [])[:4]):
            c.drawString(margin, height - 474 - i * 16, "- " + str(flag))
    footer(6)
    c.save()
    return filename


# =========================================================
# Save de-identified flight data
# =========================================================

# Retention policy (hours). Raw uploads are always deleted immediately.
RETENTION_HOURS = {
    "generated": 24,          # PDF / trajectory images
    "logs": 24 * 30,          # de-identified trajectories: 30 days
}


def purge_old_files(directory, max_age_hours):
    """Delete files in `directory` older than max_age_hours. Returns count removed."""
    removed = 0
    try:
        now = datetime.utcnow()
        for name in os.listdir(directory):
            path = os.path.join(directory, name)
            if not os.path.isfile(path):
                continue
            age_hours = (
                now - datetime.utcfromtimestamp(os.path.getmtime(path))
            ).total_seconds() / 3600.0
            if age_hours > max_age_hours:
                try:
                    os.remove(path)
                    removed += 1
                except Exception:
                    pass
    except Exception:
        pass
    return removed


def enforce_retention():
    """Apply the global retention policy. Safe to call on every request."""
    purge_old_files(GENERATED_DIR, RETENTION_HOURS["generated"])
    purge_old_files(LOG_DIR, RETENTION_HOURS["logs"])


DELETE_INDEX_PATH = os.path.join(LOG_DIR, "deletion_index.json")


def _load_deletion_index():
    """Token -> file mapping for user-initiated deletion."""
    try:
        with open(DELETE_INDEX_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_deletion_index(index):
    try:
        with open(DELETE_INDEX_PATH, "w", encoding="utf-8") as fh:
            json.dump(index, fh)
    except OSError:
        pass


def delete_shared_data(token):
    """Delete the shared de-identified file for `token`.

    Returns True only if a file was actually removed. Tokens are random and
    are the only handle we keep, so no account is needed.
    """
    token = (token or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,64}", token):
        return False

    index = _load_deletion_index()
    entry = index.get(token)
    if not entry:
        return False

    path = os.path.join(LOG_DIR, entry.get("file", ""))
    removed = False

    if os.path.exists(path):
        try:
            os.remove(path)
            removed = True
        except OSError:
            return False

    index.pop(token, None)
    _save_deletion_index(index)
    return removed


def save_deidentified_log(df):
    """Save a de-identified trajectory. Returns (path, token).

    Removed entirely: latitude, longitude, UTC timestamps and the absolute
    (sea-level) altitude. What remains is a relative shape: metres east and
    north of the first point, height above the take-off point, elapsed
    seconds, speed and heading. The random token lets the uploader delete
    this copy later without an account.
    """
    if len(df) < 1:
        return None, None

    lat0 = math.radians(float(df.iloc[0]["latitude"]))
    lon0 = math.radians(float(df.iloc[0]["longitude"]))
    radius = 6371000.0

    lat = np.radians(df["latitude"].to_numpy(dtype=float))
    lon = np.radians(df["longitude"].to_numpy(dtype=float))
    x_m = (lon - lon0) * math.cos(lat0) * radius
    y_m = (lat - lat0) * radius

    altitude = pd.to_numeric(df["altitude_m"], errors="coerce")

    if "relative_altitude_m" in df.columns:
        relative_altitude = pd.to_numeric(
            df["relative_altitude_m"], errors="coerce"
        )
    else:
        known = altitude.dropna()
        relative_altitude = (
            altitude - float(known.iloc[0]) if len(known) else altitude
        )

    safe = pd.DataFrame({
        "elapsed_seconds": df["elapsed_seconds"],
        "x_m": x_m,
        "y_m": y_m,
        "altitude_above_start_m": relative_altitude,
        "speed_mps": df["speed_mps"],
        "heading_deg": df["heading_deg"],
    })

    token = secrets.token_urlsafe(12)
    filename = f"deidentified_{token}.csv"
    path = os.path.join(LOG_DIR, filename)
    safe.to_csv(path, index=False)

    index = _load_deletion_index()
    index[token] = {
        "file": filename,
        "created": datetime.utcnow().isoformat(timespec="seconds"),
    }
    _save_deletion_index(index)

    return path, token
# =========================================================
# Demo flight
# =========================================================

def create_demo_flight():
    points = 80
    center_lat, center_lon = 34.0522, -118.2437
    start = pd.Timestamp("2026-01-15T18:00:00Z")
    rows = []
    for i in range(points):
        angle = 2 * math.pi * i / (points - 1)
        radius_deg = 0.006
        rows.append({
            "latitude": center_lat + radius_deg * math.sin(angle),
            "longitude": center_lon + radius_deg * math.cos(angle),
            "altitude_m": 40 + 15 * math.sin(angle * 2),
            "timestamp_utc": start + pd.to_timedelta(i, unit="s"),
        })
    return normalize_flight_data(pd.DataFrame(rows))


# =========================================================
# Report page
# =========================================================

REPORT_HTML = r"""
<!DOCTYPE html>

<html lang="en">

<head>

<meta charset="UTF-8">

<meta name="viewport"
      content="width=device-width, initial-scale=1.0">

<title>Flight Report</title>

<link
    rel="stylesheet"
    href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
>

<style>

body {

    margin: 0;

    background: #020617;

    color: #f8fafc;

    font-family:
        Inter,
        -apple-system,
        BlinkMacSystemFont,
        "Segoe UI",
        sans-serif;
}

.container {

    width: min(1100px, 92%);

    margin: 0 auto;

    padding: 45px 0;
}

h1 {

    margin-bottom: 10px;
}

.subtitle {

    color: #94a3b8;

    margin-bottom: 30px;
}

.grid {

    display: grid;

    grid-template-columns:
        repeat(
            auto-fit,
            minmax(180px, 1fr)
        );

    gap: 15px;

    margin-bottom: 30px;
}

.stat {

    background: #0f172a;

    border:
        1px solid
        rgba(148,163,184,.15);

    border-radius: 14px;

    padding: 20px;
}

.stat-title {

    color: #94a3b8;

    font-size: 13px;

    margin-bottom: 8px;
}

.stat-value {

    font-size: 25px;

    font-weight: 700;
}

.card {

    background: #0f172a;

    border:
        1px solid
        rgba(148,163,184,.15);

    border-radius: 18px;

    padding: 25px;

    margin-top: 20px;
}

.card img {

    width: 100%;

    border-radius: 12px;

    background: white;
}

#map {

    width: 100%;

    height: 480px;

    border-radius: 12px;

    background: #0b1220;

    z-index: 1;
}

.map-note {

    margin-top: 12px;
}

.map-tools {

    display: flex;

    align-items: center;

    justify-content: space-between;

    gap: 14px;

    flex-wrap: wrap;

    margin: 0 0 10px;

    color: #94a3b8;

    font-size: 13px;
}

.map-tools label {

    display: inline-flex;

    align-items: center;

    gap: 7px;

    cursor: pointer;

    user-select: none;
}

.map-legend {

    display: inline-flex;

    align-items: center;

    gap: 10px;
}

.map-legend span {

    display: inline-flex;

    align-items: center;

    gap: 5px;
}

.map-legend i {

    width: 9px;

    height: 9px;

    border-radius: 50%;

    display: inline-block;
}

.wind-arrow {

    background: none !important;

    border: none !important;
}

.analysis-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:18px; }
.analysis-panel { background:#0b1220; border:1px solid rgba(148,163,184,.15); border-radius:14px; padding:18px; }
.analysis-panel h3 { margin-top:0; }
.event-row { border-left:2px solid #38bdf8; padding:8px 0 8px 12px; }
.event-kind { color:#94a3b8; font-size:12px; }
.node-profile { margin-top:14px; padding:12px; border:1px solid rgba(148,163,184,.15); border-radius:10px; background:#0b1220; }
.node-profile .profile-source { color:#fbbf24; }
.node-profile svg { margin-top:8px; max-width:620px; }
@media (max-width:760px) { .analysis-grid { grid-template-columns:1fr; } }

.button {

    display: inline-block;

    margin-top: 20px;

    padding: 12px 20px;

    border-radius: 10px;

    background: #2563eb;

    color: white;

    text-decoration: none;

    font-weight: 600;
}

.small {

    color: #94a3b8;

    font-size: 13px;

    line-height: 1.6;
}

</style>

</head>


<body>

<div class="container">

<h1>Drone Flight Report</h1>

<div class="subtitle">

    {% if flight_date %}

        {{ flight_date }}

        {% if date_source == "manual" %}
            &middot; date entered manually
        {% endif %}

    {% else %}

        Date unavailable

    {% endif %}

</div>

{% if not flight_date %}

<p class="small" style="text-align:center;margin:-6px auto 22px;max-width:640px;">
    This log contains no GPS time, so the date and the wind reference are
    unavailable. Re-upload it with the optional flight date filled in to
    enable the wind lookup.
</p>

{% endif %}

{% if report_context %}
<div class="card" style="margin:0 0 24px;">
    <h2 style="margin-top:0;">Report context</h2>
    <div class="grid" style="margin-bottom:0;">
        {% for key, label in [
            ('organization', 'Organization'),
            ('project', 'Project / mission'),
            ('aircraft', 'Aircraft'),
            ('pilot', 'Pilot / operator'),
            ('client_reference', 'Client reference')
        ] %}
            {% if report_context.get(key) %}
            <div class="stat">
                <div class="stat-title">{{ label }}</div>
                <div style="font-size:16px;font-weight:650;">
                    {{ report_context.get(key) }}
                </div>
            </div>
            {% endif %}
        {% endfor %}
    </div>
    <p class="small" style="margin-bottom:0;">
        Draft report context supplied for this generation. Review all labels
        before sending the report to a client or approver.
    </p>
</div>
{% endif %}


<div class="grid">

    <div class="stat">

        <div class="stat-title">
            GPS Points
        </div>

        <div class="stat-value">
            {{ stats.points }}
        </div>

    </div>


    <div class="stat">

        <div class="stat-title">
            Distance
        </div>

        <div class="stat-value">

            {{ "%.3f"|format(stats.distance_km) }}
            km

        </div>

    </div>


    <div class="stat">

        <div class="stat-title">
            Max Altitude ({{ stats.altitude_reference }})
        </div>

        <div class="stat-value">

            {% if stats.max_altitude is not none %}

                {{ "%.2f"|format(stats.max_altitude) }}
                m

            {% else %}

                N/A

            {% endif %}

        </div>

    </div>


    <div class="stat">

        <div class="stat-title">
            Mean Altitude ({{ stats.altitude_reference }})
        </div>

        <div class="stat-value">

            {% if stats.mean_altitude is not none %}

                {{ "%.2f"|format(stats.mean_altitude) }}
                m

            {% else %}

                N/A

            {% endif %}

        </div>

    </div>


    <div class="stat">

        <div class="stat-title">
            Vertical range
        </div>

        <div class="stat-value">

            {% if stats.vertical_range is not none %}

                {{ "%.2f"|format(stats.vertical_range) }}
                m

            {% else %}

                N/A

            {% endif %}

        </div>

    </div>

</div>


<div class="card">

    <h2>Flight Health</h2>

    {% if health %}

        <p>

            Score:
            <strong>{{ health.score }}/100</strong>

            &middot;

            <span style="
                padding:2px 8px;
                border-radius:8px;
                background:
                {% if health.verdict == 'healthy' %}
                    rgba(34,197,94,.18)
                {% elif health.verdict == 'review' %}
                    rgba(234,179,8,.18)
                {% else %}
                    rgba(239,68,68,.18)
                {% endif %};
            ">{{ health.verdict }}</span>

        </p>

        {% if health.flags %}

            <ul class="small">

                {% for flag in health.flags %}
                    <li>{{ flag }}</li>
                {% endfor %}

            </ul>

        {% else %}

            <p class="small">
                No anomalies detected across GPS, timing, altitude and speed.
            </p>

        {% endif %}

    {% else %}

        <p>Health screening unavailable.</p>

    {% endif %}

</div>


<div class="card">

    <h2>Wind Reference</h2>


    {% if wind.speed is not none %}

        <p>

            Wind speed:
            <strong>
                {{ "%.1f"|format(wind.speed *3.6) }}
                km/h
            </strong>

        </p >


        {% if wind.direction is not none %}

            <p>

                Wind direction:
                <strong>
                    {{ "%.0f"|format(wind.direction) }}°
                </strong>
                {% if wind.direction_cn %}
                    ({{ wind.direction_cn }})
                {% endif %}

            </p >

        {% endif %}


        <p class="small">

            Source:
            {{ wind.source }}

        </p >

        {% if wind.speed_ensemble is not none %}

            <p class="small">

                Multi-source ensemble:
                <strong>
                    {{ "%.1f"|format(wind.speed_ensemble * 3.6) }}
                    km/h
                </strong>

                {% if wind.spread is not none %}
                    (&plusmn; {{ "%.1f"|format(wind.spread * 3.6) }} km/h
                    across {{ wind.sources|length }} sources)
                {% endif %}

            </p >

        {% endif %}

        {% if wind.weighted_speed is not none %}

            <p>

                Flight-weighted wind:
                <strong>
                    {{ "%.1f"|format(wind.weighted_speed * 3.6) }}
                    km/h @ {{ "%.0f"|format(wind.weighted_direction) }}&deg;
                </strong>

            </p >

            {% if wind.levels %}

                <ul class="small">

                    {% for level in wind.levels %}
                        <li>
                            {{ level.alt_m }} m &mdash;
                            {{ "%.1f"|format(level.speed_mps * 3.6) }} km/h
                            (weight {{ "%.0f"|format(level.weight * 100) }}%)
                        </li>
                    {% endfor %}

                </ul>

            {% endif %}

            <p class="small">
                Weighted by time spent at each altitude level.
            </p >

        {% endif %}

    {% else %}

        <p>
            Wind data unavailable.
        </p >

    {% endif %}

</div>


{% if data_token %}

<div class="card" style="margin-top:22px;">

    <h2>Your shared data</h2>

    <p class="small">
        You opted in to sharing a de-identified copy of this flight. It contains
        no coordinates, no timestamps and no absolute altitude - only the shape
        of the track. Keep this ID if you want to delete it later:
    </p>

    <p id="dataToken"
       style="font-family:ui-monospace,SFMono-Regular,Menlo,monospace;
              font-size:16px;color:#93c5fd;word-break:break-all;margin:10px 0;">
        {{ data_token }}
    </p>

    <p class="small">
        Delete any time at
        <a href="/delete-data" style="color:#60a5fa;text-decoration:none;">/delete-data</a>.
        It is also removed automatically after 30 days.
    </p>

</div>

{% endif %}


<div class="card">

    <h2>Satellite Track Map</h2>

    <div class="map-tools">

        <label for="windToggle">
            <input type="checkbox" id="windToggle">
            Wind arrows
        </label>

        <span class="map-legend">
            <span><i style="background:#93c5fd;"></i>&lt;2 m/s</span>
            <span><i style="background:#38bdf8;"></i>2-5</span>
            <span><i style="background:#fbbf24;"></i>5-8</span>
            <span><i style="background:#f87171;"></i>&gt;8</span>
        </span>

    </div>

    <div id="map"></div>

    <p class="small map-note">
        Satellite imagery: Esri World Imagery (global), 高德卫星 (China), and
        天地图 when a key is configured (北斗 / CGCS2000, mainland China).
        Coordinates are rendered in your browser only and are never stored.
        Use the layer switcher at the top right to change the basemap.
    </p>

</div>

<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
(function () {
    var points = {{ map_points|tojson }};
    var windArrows = {{ (wind_arrows or [])|tojson }};
    var container = document.getElementById("map");

    if (!window.L || !points || points.length < 2) {
        container.innerHTML =
            '<div style="padding:24px;color:#94a3b8;">' +
            "Map preview unavailable for this log.</div>";
        return;
    }

    // WGS-84 -> GCJ-02, needed only for 高德 tiles (they are GCJ-02 based).
    function outOfChina(lng, lat) {
        return !(lng > 73.66 && lng < 135.05 && lat > 3.86 && lat < 53.55);
    }

    function transformLat(x, y) {
        var ret = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y +
            0.2 * Math.sqrt(Math.abs(x));
        ret += (20.0 * Math.sin(6.0 * x * Math.PI) +
            20.0 * Math.sin(2.0 * x * Math.PI)) * 2.0 / 3.0;
        ret += (20.0 * Math.sin(y * Math.PI) +
            40.0 * Math.sin(y / 3.0 * Math.PI)) * 2.0 / 3.0;
        ret += (160.0 * Math.sin(y / 12.0 * Math.PI) +
            320.0 * Math.sin(y * Math.PI / 30.0)) * 2.0 / 3.0;
        return ret;
    }

    function transformLng(x, y) {
        var ret = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y +
            0.1 * Math.sqrt(Math.abs(x));
        ret += (20.0 * Math.sin(6.0 * x * Math.PI) +
            20.0 * Math.sin(2.0 * x * Math.PI)) * 2.0 / 3.0;
        ret += (20.0 * Math.sin(x * Math.PI) +
            40.0 * Math.sin(x / 3.0 * Math.PI)) * 2.0 / 3.0;
        ret += (150.0 * Math.sin(x / 12.0 * Math.PI) +
            300.0 * Math.sin(x / 30.0 * Math.PI)) * 2.0 / 3.0;
        return ret;
    }

    function wgs84ToGcj02(lng, lat) {
        if (outOfChina(lng, lat)) {
            return [lng, lat];
        }
        var a = 6378245.0;
        var ee = 0.00669342162296594323;
        var dLat = transformLat(lng - 105.0, lat - 35.0);
        var dLng = transformLng(lng - 105.0, lat - 35.0);
        var radLat = lat / 180.0 * Math.PI;
        var magic = Math.sin(radLat);
        magic = 1 - ee * magic * magic;
        var sqrtMagic = Math.sqrt(magic);
        dLat = (dLat * 180.0) /
            ((a * (1 - ee)) / (magic * sqrtMagic) * Math.PI);
        dLng = (dLng * 180.0) /
            (a / sqrtMagic * Math.cos(radLat) * Math.PI);
        return [lng + dLng, lat + dLat];
    }

    var gcjPoints = points.map(function (p) {
        var converted = wgs84ToGcj02(p[1], p[0]);
        return [converted[1], converted[0]];
    });

    var map = L.map("map", { scrollWheelZoom: true });
    window.__droneFlightMap = map;

    var esri = L.tileLayer(
        "https://server.arcgisonline.com/ArcGIS/rest/services/" +
        "World_Imagery/MapServer/tile/{z}/{y}/{x}",
        { maxZoom: 19, attribution: "Tiles &copy; Esri" }
    );
    var gaode = L.tileLayer(
        "https://webst0{s}.is.autonavi.com/appmaptile" +
        "?style=6&x={x}&y={y}&z={z}",
        {
            subdomains: ["1", "2", "3", "4"],
            maxZoom: 18,
            attribution: "&copy; 高德地图"
        }
    );
    var osm = L.tileLayer(
        "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
        {
            maxZoom: 19,
            attribution: "&copy; OpenStreetMap contributors"
        }
    );

    // Optional official Chinese satellite basemap (天地图 / CGCS2000).
    // Requires a free key from https://console.tianditu.gov.cn/.
    var tiandituKey = {{ tianditu_key|tojson }};
    var tianditu = null;
    if (tiandituKey) {
        tianditu = L.tileLayer(
            "https://t{s}.tianditu.gov.cn/img_w/wmts" +
            "?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0" +
            "&LAYER=img&STYLE=default&TILEMATRIXSET=w" +
            "&FORMAT=tiles&TILEMATRIX={z}&TILEROW={y}" +
            "&TILECOL={x}&tk=" + encodeURIComponent(tiandituKey),
            {
                subdomains: ["0", "1", "2", "3", "4", "5", "6", "7"],
                maxZoom: 18,
                attribution: "&copy; 天地图"
            }
        );
    }

    function trackGroup(coords) {
        return L.layerGroup([
            L.polyline(coords, {
                color: "#38bdf8",
                weight: 4,
                opacity: 0.95
            }),
            L.circleMarker(coords[0], {
                radius: 7,
                color: "#ffffff",
                weight: 2,
                fillColor: "#22c55e",
                fillOpacity: 1
            }).bindPopup("Start"),
            L.circleMarker(coords[coords.length - 1], {
                radius: 7,
                color: "#ffffff",
                weight: 2,
                fillColor: "#ef4444",
                fillOpacity: 1
            }).bindPopup("End")
        ]);
    }

    // ---------------------------------------------------------
    // Wind arrows
    // One arrow per regional grid point, coloured by speed and
    // rotated to point where the air is moving. Click for the
    // exact value. This is the reference wind, not onboard data.
    // ---------------------------------------------------------
    function windColor(speed) {
        if (speed < 2) { return "#93c5fd"; }
        if (speed < 5) { return "#38bdf8"; }
        if (speed < 8) { return "#fbbf24"; }
        return "#f87171";
    }

    function windArrowsLayer(grid, project) {
        var group = L.layerGroup();

        grid.forEach(function (p) {
            if (!isFinite(p.u) || !isFinite(p.v)) { return; }

            var speed = Math.sqrt(p.u * p.u + p.v * p.v);
            // Meteorological bearing: where the wind comes FROM.
            var fromDeg =
                (270 - Math.atan2(p.v, p.u) * 180 / Math.PI + 360) % 360;
            var latlng = project ? project(p.lon, p.lat) : [p.lat, p.lon];

            var icon = L.divIcon({
                className: "wind-arrow",
                iconSize: [26, 26],
                iconAnchor: [13, 13],
                html:
                    '<div style="transform:rotate(' +
                    (fromDeg + 180).toFixed(1) + 'deg);color:' +
                    windColor(speed) + ';">' +
                    '<svg width="22" height="22" viewBox="0 0 24 24">' +
                    '<path d="M12 2 L18 18 L12 15 L6 18 Z" ' +
                    'fill="currentColor"/></svg></div>'
            });

            L.marker(latlng, { icon: icon, keyboard: false })
                .bindPopup(
                    "<strong>" + speed.toFixed(1) + " m/s</strong><br>" +
                    "from " + fromDeg.toFixed(0) + "&deg;"
                )
                .addTo(group);
        });

        return group;
    }

    var wgsGroup = trackGroup(points).addTo(map);
    var gcjGroup = trackGroup(gcjPoints);

    var windWgs = windArrowsLayer(windArrows, null);
    var windGcj = windArrowsLayer(windArrows, wgs84ToGcj02);

    var windEnabled = windArrows.length > 0;
    var usingGaode = false;

    if (windEnabled) {
        windWgs.addTo(map);
    }

    var windToggle = document.getElementById("windToggle");
    if (windToggle) {
        windToggle.checked = windEnabled;
        windToggle.disabled = windArrows.length === 0;
        windToggle.addEventListener("change", function (event) {
            windEnabled = event.target.checked;
            var active = usingGaode ? windGcj : windWgs;
            var idle = usingGaode ? windWgs : windGcj;
            map.removeLayer(idle);
            if (windEnabled) { active.addTo(map); }
            else { map.removeLayer(active); }
        });
    }

    map.on("baselayerchange", function (event) {
        usingGaode = event.name.indexOf("高德") !== -1;

        if (usingGaode) {
            map.removeLayer(wgsGroup);
            gcjGroup.addTo(map);
            map.removeLayer(windWgs);
            if (windEnabled) { windGcj.addTo(map); }
        } else {
            map.removeLayer(gcjGroup);
            wgsGroup.addTo(map);
            map.removeLayer(windGcj);
            if (windEnabled) { windWgs.addTo(map); }
        }
    });

    var baseLayers = {};
    if (tianditu) {
        baseLayers["卫星 · 天地图（北斗 / CGCS2000）"] = tianditu;
        tianditu.addTo(map);
    } else {
        esri.addTo(map);
    }
    baseLayers["卫星 · Esri"] = esri;
    baseLayers["卫星 · 高德"] = gaode;
    baseLayers["街道 · OSM"] = osm;

    L.control.layers(
        baseLayers,
        {},
        { collapsed: false }
    ).addTo(map);

    L.control.scale({ imperial: false }).addTo(map);
    map.fitBounds(L.latLngBounds(points).pad(0.15));
})();
</script>


<div class="card">
    <h2>Flight Analytics</h2>
    <p class="small">Click a trajectory node to inspect recorded telemetry and the labeled wind source.</p>
    <div class="analysis-grid">
        <div class="analysis-panel">
            <h3>Event Timeline</h3>
            {% if analysis_events %}
                {% for event in analysis_events %}
                <div class="event-row"><strong>{{ event.label }}</strong><div class="event-kind">{{ event.kind }} · {{ event.time_label }}</div></div>
                {% endfor %}
            {% else %}<div class="small">No derived events were recorded.</div>{% endif %}
        </div>
        <div class="analysis-panel">
            <h3>Telemetry Charts</h3>
            <svg id="telemetry-chart" viewBox="0 0 760 340" style="width:100%;height:auto;"></svg>
            <div class="small">Battery is shown only when recorded; no battery value is inferred.</div>
        </div>
    </div>
</div>

<script>
(function () {
    var nodes = {{ analysis_nodes|tojson }};
    var series = {{ analysis_series|tojson }};
    var flightDate = {{ flight_date|tojson }};
    var detail = document.createElement("div");
    detail.className = "small";
    detail.style.marginTop = "10px";
    var mapContainer = document.getElementById("map");
    if (mapContainer && nodes.length && window.L) {
        mapContainer.parentNode.appendChild(detail);
        detail.textContent = "Select a trajectory node for details.";
        var points = nodes.map(function (node) { return [node.lat, node.lon]; });
        nodes.forEach(function (node, index) {
            L.circleMarker([node.lat, node.lon], {
                radius: (index === 0 || index === nodes.length - 1) ? 7 : 4,
                color: "#fbbf24", fillOpacity: 0.9
            }).addTo(window.__droneFlightMap || window.map).on("click", function () {
                detail.innerHTML = "<strong>Sample " + node.index + "</strong> · " + node.lat.toFixed(6) + ", " + node.lon.toFixed(6) +
                    "<br>Altitude: " + (node.altitude_m === null ? "N/A" : node.altitude_m.toFixed(1) + " m") +
                    " · Speed: " + (node.speed_mps === null ? "N/A" : node.speed_mps.toFixed(1) + " m/s") +
                    "<br>Wind: " + (node.wind_speed_mps === null ? "missing" : (node.wind_speed_mps * 3.6).toFixed(1) + " km/h FROM " + Number(node.wind_direction_deg || 0).toFixed(0) + "°") +
                    " · Source: " + (node.wind_source || "missing") +
                    '<div id="node-wind-profile" class="node-profile small">Loading vertical wind profile...</div>';
                var profileBox = document.getElementById("node-wind-profile");
                var params = new URLSearchParams({lat: node.lat, lon: node.lon});
                if (flightDate) params.set("date", flightDate);
                if (node.wind_speed_mps !== null) params.set("base_speed", node.wind_speed_mps);
                if (node.wind_direction_deg !== null) params.set("base_direction", node.wind_direction_deg);
                fetch("/api/wind-profile?" + params.toString()).then(function (response) { return response.json(); }).then(function (profile) {
                    if (!profileBox) return;
                    if (!profile.svg) {
                        profileBox.textContent = "Vertical wind profile unavailable - no reliable model data for this point.";
                        return;
                    }
                    var sourceLabel = profile.source === "pressure_levels" ? "Model estimate: pressure-level wind" :
                        (profile.source === "power_law" ? "Model estimate: power-law profile" : "Wind profile unavailable");
                    profileBox.innerHTML = "<strong>Vertical wind profile</strong><br><span class=\"profile-source\">" + sourceLabel + "</span>" + profile.svg +
                        "<div class=\"small\">This is model/reference wind, not an onboard measurement.</div>";
                }).catch(function () {
                    if (profileBox) profileBox.textContent = "Vertical wind profile unavailable.";
                });
            });
        });
    }
    var svg = document.getElementById("telemetry-chart");
    if (!svg) return;
    var xData = series.x || [];
    var xLabel = series.x_label === "sample_index" ? "Sample index" : "Elapsed time (s)";
    function panel(title, unit, data, color, top) {
        var left = 72, right = 742, bottom = top + 112, plotTop = top + 20;
        var valid = data.map(function (value, index) { return { value: value, x: xData[index] }; }).filter(function (item) { return item.value !== null && item.x !== null; });
        if (!valid.length) {
            return '<text x="72" y="' + (top + 62) + '" fill="#94a3b8" font-size="12">' + title + ': no recorded data</text>';
        }
        var yValues = valid.map(function (item) { return Number(item.value); });
        var yMin = Math.min.apply(null, yValues), yMax = Math.max.apply(null, yValues);
        if (yMin === yMax) { yMin -= 1; yMax += 1; }
        var xMin = Number(xData[0] || 0), xMax = Number(xData[xData.length - 1] || 1);
        if (xMin === xMax) { xMax = xMin + 1; }
        function sx(value) { return left + (Number(value) - xMin) / (xMax - xMin) * (right - left); }
        function sy(value) { return bottom - (Number(value) - yMin) / (yMax - yMin) * (bottom - plotTop); }
        var out = '<text x="72" y="' + (top + 11) + '" fill="' + color + '" font-size="13" font-weight="600">' + title + ' (' + unit + ')</text>';
        for (var tick = 0; tick <= 4; tick++) {
            var gy = plotTop + tick / 4 * (bottom - plotTop);
            var yValue = yMax - tick / 4 * (yMax - yMin);
            out += '<line x1="' + left + '" y1="' + gy.toFixed(1) + '" x2="' + right + '" y2="' + gy.toFixed(1) + '" stroke="#334155" stroke-opacity=".55"/>';
            out += '<text x="62" y="' + (gy + 4).toFixed(1) + '" fill="#94a3b8" font-size="10" text-anchor="end">' + yValue.toFixed(1) + '</text>';
        }
        for (var xtick = 0; xtick <= 4; xtick++) {
            var gx = left + xtick / 4 * (right - left);
            var xValue = xMin + xtick / 4 * (xMax - xMin);
            out += '<line x1="' + gx.toFixed(1) + '" y1="' + plotTop + '" x2="' + gx.toFixed(1) + '" y2="' + bottom + '" stroke="#334155" stroke-opacity=".35"/>';
            out += '<text x="' + gx.toFixed(1) + '" y="' + (bottom + 15) + '" fill="#94a3b8" font-size="10" text-anchor="middle">' + xValue.toFixed(0) + '</text>';
        }
        var d = "";
        data.forEach(function (value, index) {
            if (value === null || xData[index] === null) { d += " "; return; }
            d += (d.trim() ? "L" : "M") + sx(xData[index]).toFixed(1) + "," + sy(value).toFixed(1);
        });
        out += '<path d="' + d + '" fill="none" stroke="' + color + '" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round"/>';
        out += '<text x="' + ((left + right) / 2) + '" y="' + (bottom + 30) + '" fill="#94a3b8" font-size="10" text-anchor="middle">' + xLabel + '</text>';
        out += '<text x="16" y="' + ((plotTop + bottom) / 2) + '" fill="#94a3b8" font-size="10" text-anchor="middle" transform="rotate(-90 16 ' + ((plotTop + bottom) / 2) + ')">' + unit + '</text>';
        return out;
    }
    var hasValues = (series.altitude_m || []).some(function (v) { return v !== null; }) || (series.speed_mps || []).some(function (v) { return v !== null; });
    if (!hasValues) { svg.innerHTML = '<text x="24" y="40" fill="#94a3b8">No altitude or speed telemetry was recorded.</text>'; return; }
    svg.innerHTML = panel("Altitude", "m", series.altitude_m || [], "#38bdf8", 0) + panel("Speed", "m/s", series.speed_mps || [], "#fbbf24", 165);
})();
</script>


{% if wind_profile_svg %}

<div class="card" style="margin-top:22px;">

    <h2>Wind profile</h2>

    {{ wind_profile_svg|safe }}

    <p class="small" style="margin-top:12px;">
        {% if wind_profile_source == "pressure_levels" %}
            Pressure-level wind for this area and hour (Open-Meteo, roughly
            110-1450 m above sea level), shifted to height above the take-off
            point. The shaded band is the range of heights you actually flew.
        {% else %}
            Estimated from the surface wind with a power law (open terrain):
            pressure-level data is only published for recent flights. Treat the
            shape as indicative, not exact.
        {% endif %}
        Regional reference, not an onboard measurement.
    </p>

</div>

{% endif %}


<div class="card">

    <h2>Flight Trajectory</h2>

    <img
        src="/generated/{{ image_filename }}"
        alt="Flight trajectory"
    >

</div>


<a
    class="button"
    href="{{ url_for('download_report',
    filename=pdf_filename)}}"
>
    Download PDF Report
</a >


</div>

</body>

</html>
"""


PRIVACY_HTML = r"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Privacy &amp; Data Retention</title>
<style>
body{margin:0;background:#020617;color:#f8fafc;
 font-family:Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;}
.wrap{width:min(820px,92%);margin:0 auto;padding:56px 0;line-height:1.75;}
h1{margin:0 0 6px;} .sub{color:#94a3b8;margin-bottom:28px;}
h2{font-size:18px;margin:30px 0 8px;color:#e2e8f0;}
p{margin:8px 0;color:#cbd5e1;}
.card{background:#0f172a;border:1px solid rgba(148,163,184,.15);
 border-radius:16px;padding:24px;margin-top:18px;}
a{color:#60a5fa;text-decoration:none;}
.small{color:#94a3b8;font-size:13px;}
</style>
</head>
<body>
<div class="wrap">
<h1>Privacy &amp; Data Retention</h1>
<div class="sub">Drone Flight Report</div>

<div class="card">
<h2>What we process</h2>
<p>When you upload a flight log, we parse it, compute flight statistics,
derive a regional wind reference, and generate a trajectory image and a PDF report.</p>

<h2>Retention</h2>
<p>&middot; Your original uploaded log is processed in a temporary file and
deleted immediately after processing &mdash; it is never kept.</p>
<p>&middot; Generated images and PDF reports are deleted automatically after
<strong>24 hours</strong>.</p>
<p>&middot; If you opt in to sharing, only a <strong>de-identified</strong> version
may be kept for up to <strong>30 days</strong>: relative trajectory
(metres from the first point), elapsed time, height above the take-off point,
speed and heading. Raw GPS coordinates, absolute UTC timestamps and the
absolute sea-level altitude are removed.</p>

<h2>What we do not keep</h2>
<p>We do not retain your original filename, name, email, phone number or postal
address. We do not store your IP address with your flight data.</p>

<h2>Professional report labels</h2>
<p>If you add organization, project, aircraft, pilot or client-reference
labels, they are used only in the browser report and generated PDF. They are
not added to an opted-in de-identified flight sample. The generated report is
removed under the same 24-hour policy described above.</p>

<h2>Team pilot enquiries</h2>
<p>The design-partner form at <a href="/for-teams">/for-teams</a> stores the
contact and workflow details you deliberately submit for up to
<strong>180 days</strong>. It does not accept flight logs and does not store
your IP address with the enquiry. You can request earlier deletion through
the <a href="/contact">contact form</a>.</p>

<h2>Your choices</h2>
<p>Sharing de-identified data is <strong>off by default</strong> and requires an
explicit opt-in checkbox. Your report shows a random data ID; paste it at
<a href="/delete-data">/delete-data</a> to delete that copy immediately. No
account or email address is needed, and deletion is permanent.</p>

<h2>Wind data</h2>
<p>Wind information is a regional historical weather reference
(Open-Meteo / NASA POWER), not a local real-time measurement.</p>

<h2>Satellite map</h2>
<p>The interactive track map runs in your browser. Satellite tiles are loaded
directly from Esri and 高德; those tile requests necessarily include the map
area being viewed. We do not store map views, coordinates or tile requests.</p>

<p class="small" style="margin-top:22px;">
<a href="/">&larr; Back to upload</a>
</p>
</div>
</div>
</body>
</html>
"""


# =========================================================
# Homepage / upload
# =========================================================

@app.route(
    "/",
    methods=["GET", "POST"]
)
def index():

    if request.method == "GET":

        return render_template_string(
            HTML
        )


    # -----------------------------------------------------
    # Check upload
    # -----------------------------------------------------

    if "file" not in request.files:

        return render_template_string(
            HTML
        ), 400


    uploaded_file = request.files[
        "file"
    ]


    if (
        uploaded_file.filename is None
        or uploaded_file.filename.strip() == ""
    ):

        return render_template_string(
            HTML
        ), 400


    filename = secure_filename(
        uploaded_file.filename
    )

    report_context = extract_report_context(request.form)


    extension = (
        os.path.splitext(filename)[1]
        .lower()
    )


    allowed_extensions = {
        ".csv",
        ".txt",
        ".bin",
        ".ulg",
    }


    if extension not in allowed_extensions:

        return (
            f"""
            <h2>Unsupported file type</h2>

            <p>
                Supported:
                CSV / TXT / BIN / ULG
            </p >

            <p>
                <a href="/">
                    Back
                </a >
            </p >
            """,
            400
        )


    # -----------------------------------------------------
    # Temporary input file
    # -----------------------------------------------------

    temp_path = None


    try:

        with tempfile.NamedTemporaryFile(
            delete=False,
            suffix=extension
        ) as temp:

            uploaded_file.save(
                temp.name
            )

            temp_path = temp.name


        # -------------------------------------------------
        # File size protection
        # -------------------------------------------------

        file_size = os.path.getsize(
            temp_path
        )


        max_size = 100 * 1024 * 1024


        if file_size > max_size:

            raise ValueError(
                "File is larger than "
                "100 MB."
            )


        # -------------------------------------------------
        # Parse
        # -------------------------------------------------

        df = parse_flight_log(
            temp_path
        )

        df = validate_flight_data(df)


        # -------------------------------------------------
        # Statistics
        # -------------------------------------------------

        stats = calculate_statistics(
            df
        )

        health = detect_flight_health(
            df
        )


        # -------------------------------------------------
        # Optional data saving
        # -------------------------------------------------

        save_consent = (
            request.form.get(
                "save_consent"
            )
            == "on"
        )


        data_token = None

        if save_consent:

            _, data_token = save_deidentified_log(
                df
            )


        # -------------------------------------------------
        # Flight date
        # -------------------------------------------------

        detected_date = get_flight_date(
            df
        )

        manual_date = parse_flight_date_override(
            request.form.get("flight_date")
        )

        flight_date = manual_date or detected_date

        # `manual` dates are shown as such: the report must not imply that a
        # date the user typed came out of the log.
        date_source = (
            "manual" if manual_date
            else ("log" if detected_date else None)
        )

        print(
            "Flight date:",
            flight_date,
            "(source:",
            date_source,
            ")"
        )

        # -------------------------------------------------
        # Wind
        # -------------------------------------------------

        wind = get_wind_ensemble(
            df,
            flight_date,
            grid_size=6
        )
        print(
            "Wind field grid points:",
            len(wind.get("grid", []))
        )

        # Chinese compass label for the reference wind (merged from the
        # app_seo_updated-1 version).
        wind["direction_cn"] = direction_to_chinese(
            wind.get("direction")
        )

        # -------------------------------------------------
        # Interactive satellite map data
        # -------------------------------------------------
        # Coordinates are only passed to the browser for rendering and are
        # never written to disk. Sample large logs so the HTML stays light.
        max_map_points = 1500
        stride = max(1, len(df) // max_map_points)
        map_df = df.iloc[::stride]
        map_points = [
            [round(float(lat), 6), round(float(lon), 6)]
            for lat, lon in zip(
                map_df["latitude"],
                map_df["longitude"]
            )
        ]
        last_point = [
            round(float(df.iloc[-1]["latitude"]), 6),
            round(float(df.iloc[-1]["longitude"]), 6),
        ]
        if map_points and map_points[-1] != last_point:
            map_points.append(last_point)

        # -------------------------------------------------
        # Plot
        # -------------------------------------------------

        image_filename = (
            generate_flight_plot(
                df,
                wind
            )
        )


        image_path = os.path.join(
            GENERATED_DIR,
            image_filename
        )


        # -------------------------------------------------
        # PDF
        # -------------------------------------------------

        pdf_filename = (
            generate_pdf_report(
                df,
                stats,
                wind,
                image_path,
                flight_date=flight_date,
                health=health,
                report_context=report_context,
            )
        )


        wind_profile_source, wind_profile_svg = build_wind_profile_payload(
            df, wind, flight_date, stats
        )
        analysis = build_telemetry_payload(df, wind, health)

        return render_template_string(

            REPORT_HTML,

            stats=stats,

            wind=wind,

            map_points=map_points,

            wind_arrows=build_wind_arrows(wind),

            wind_profile_svg=wind_profile_svg,

            wind_profile_source=wind_profile_source,

            tianditu_key=TIANDITU_KEY,

            image_filename=
                image_filename,

            pdf_filename=
                pdf_filename,

            flight_date=
                flight_date,

            date_source=
                date_source,

            data_token=
                data_token,

            health=health,

            report_context=report_context,

            analysis_nodes=analysis["nodes"],
            analysis_series=analysis["series"],
            analysis_events=analysis["events"],

        )


    except Exception as exc:

        if isinstance(exc, ValueError):

            # Expected, user-facing validation errors.
            error_message = str(exc)

        else:

            # Unexpected: log details server-side, show a generic page.
            import traceback

            traceback.print_exc()

            error_message = (
                "Unexpected processing error. "
                "Please check the log format and try again."
            )


        return f"""

        <div style="
            max-width:800px;
            margin:60px auto;
            padding:30px;
            font-family:Arial;
        ">

            <h2>
                Flight log processing failed
            </h2>

            <p>
                {error_message}
            </p >

            <hr>

            <p>
                Please check that the file contains
                valid latitude and longitude data.
            </p >

            <p>
                <a href="/">
                    ← Back
                </a >
            </p >

        </div>

        """, 400


    finally:

        # -------------------------------------------------
        # Delete temporary upload
        # -------------------------------------------------

        if (
            temp_path
            and os.path.exists(temp_path)
        ):

            try:

                os.remove(
                    temp_path
                )

            except Exception:

                pass


        # Apply the retention policy (generated files + de-identified logs).
        enforce_retention()


# =========================================================
# Generated image
# =========================================================

@app.route(
    "/generated/<filename>"
)
def generated_file(filename):

    filename = secure_filename(
        filename
    )


    path = os.path.join(
        GENERATED_DIR,
        filename
    )


    if not os.path.exists(path):

        return (
            "File not found.",
            404
        )


    return send_file(
        path
    )


# =========================================================
# Download PDF
# =========================================================

@app.route(
    "/download_report/<filename>"
)
def download_report(filename):

    filename = secure_filename(
        filename
    )


    path = os.path.join(
        GENERATED_DIR,
        filename
    )


    if not os.path.exists(path):

        return (
            "Report not found.",
            404
        )


    return send_file(
        path,
        as_attachment=True,
        mimetype="application/pdf"
    )


@app.route("/api/wind-profile")
def api_wind_profile():
    """Return a source-labeled vertical wind profile for a clicked map node."""
    try:
        lat = float(request.args.get("lat", ""))
        lon = float(request.args.get("lon", ""))
    except (TypeError, ValueError):
        return jsonify({"levels": [], "source": None, "svg": "", "error": "invalid coordinates"}), 400

    date_str = (request.args.get("date") or "").strip()
    if date_str and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_str):
        date_str = ""

    def optional_float(name):
        try:
            return float(request.args.get(name, ""))
        except (TypeError, ValueError):
            return None

    profile = get_wind_profile(
        lat,
        lon,
        date_str or None,
        base_speed=optional_float("base_speed"),
        base_direction=optional_float("base_direction"),
    )
    levels = profile.get("levels") or []
    return jsonify({
        "levels": levels,
        "source": profile.get("source"),
        "svg": render_wind_profile_svg(profile) if len(levels) >= 2 else "",
    })


# =========================================================
# Shared helpers
# =========================================================

def build_map_points(df, max_points=1500):
    """Down-sample a flight into [lat, lon] pairs for the Leaflet map.

    Kept in one place so every page that renders REPORT_HTML gets a real
    value instead of a Jinja Undefined (which breaks `|tojson`).
    """
    if df is None or len(df) == 0:
        return []
    if "latitude" not in df.columns or "longitude" not in df.columns:
        return []

    stride = max(1, len(df) // max_points)
    map_df = df.iloc[::stride]

    points = [
        [round(float(lat), 6), round(float(lon), 6)]
        for lat, lon in zip(map_df["latitude"], map_df["longitude"])
        if lat == lat and lon == lon  # drop NaN
    ]

    last = df.iloc[-1]
    last_point = [
        round(float(last["latitude"]), 6),
        round(float(last["longitude"]), 6),
    ]
    if last_point[0] == last_point[0] and points and points[-1] != last_point:
        points.append(last_point)

    return points


def build_telemetry_payload(df, wind, health=None, max_points=360):
    """Create a compact, honest P1 payload from recorded telemetry only."""
    if df is None or len(df) == 0:
        return {"nodes": [], "series": {}, "events": []}

    stride = max(1, len(df) // max_points)
    sample = df.iloc[::stride]
    nodes = []
    for index, row in sample.iterrows():
        try:
            lat = float(row.get("latitude"))
            lon = float(row.get("longitude"))
        except (TypeError, ValueError):
            continue
        def number(name):
            value = row.get(name)
            try:
                value = float(value)
                return value if math.isfinite(value) else None
            except (TypeError, ValueError):
                return None
        wind_speed = number("wind_speed_mps")
        wind_direction = number("wind_direction_deg")
        if wind_speed is None:
            wind_speed = (wind or {}).get("weighted_speed", (wind or {}).get("speed"))
        if wind_direction is None:
            wind_direction = (wind or {}).get("weighted_direction", (wind or {}).get("direction"))
        nodes.append({
            "index": int(index),
            "lat": round(lat, 6), "lon": round(lon, 6),
            "elapsed_seconds": number("elapsed_seconds"),
            "timestamp_utc": str(row.get("timestamp_utc")) if row.get("timestamp_utc") not in (None, "", "NaT") else None,
            "altitude_m": number("relative_altitude_m") if number("relative_altitude_m") is not None else number("altitude_m"),
            "speed_mps": number("speed_mps"),
            "battery_percent": number("battery_percent"),
            "wind_speed_mps": wind_speed,
            "wind_direction_deg": wind_direction,
            "wind_source": (wind or {}).get("source", "missing") if wind_speed is not None else "missing",
        })
    if nodes and nodes[-1]["index"] != int(df.index[-1]):
        last = df.iloc[-1]
        nodes.append({**nodes[-1], "index": int(df.index[-1]), "lat": round(float(last["latitude"]), 6), "lon": round(float(last["longitude"]), 6)})
    x = [node["elapsed_seconds"] for node in nodes]
    if not all(value is not None for value in x):
        x = [node["index"] for node in nodes]
        x_label = "sample_index"
    else:
        x_label = "elapsed_seconds"
    events = []

    def add_event(kind, label, node):
        if not node:
            return
        event_x = node.get("elapsed_seconds") if x_label == "elapsed_seconds" else node.get("index")
        if event_x is None:
            event_x = node.get("index", 0)
        time_label = (
            f"t = {float(event_x):.1f} s"
            if x_label == "elapsed_seconds"
            else f"sample {int(event_x)}"
        )
        events.append({
            "kind": kind,
            "label": label,
            "index": node.get("index", 0),
            "x": event_x,
            "time_label": time_label,
        })

    if nodes:
        add_event("flight", "Trajectory start", nodes[0])
        add_event("flight", "Trajectory end", nodes[-1])
        altitude_nodes = [node for node in nodes if node.get("altitude_m") is not None]
        if altitude_nodes:
            add_event("altitude", "Maximum recorded altitude", max(altitude_nodes, key=lambda node: node["altitude_m"]))
        speed_nodes = [node for node in nodes if node.get("speed_mps") is not None]
        if speed_nodes:
            add_event("speed", "Maximum recorded speed", max(speed_nodes, key=lambda node: node["speed_mps"]))
        battery_nodes = [node for node in nodes if node.get("battery_percent") is not None and node["battery_percent"] <= 20]
        if battery_nodes:
            add_event("battery", "Battery at or below 20%", battery_nodes[0])
        if wind and wind.get("speed") is not None:
            add_event("wind", "Wind reference attached", nodes[0])
    for flag in (health or {}).get("flags", []):
        add_event("health", str(flag), nodes[0] if nodes else None)
    events.sort(key=lambda event: float(event.get("x", 0)))
    return {
        "nodes": nodes,
        "series": {
            "x_label": x_label, "x": x,
            "altitude_m": [node["altitude_m"] for node in nodes],
            "speed_mps": [node["speed_mps"] for node in nodes],
            "battery_percent": [node["battery_percent"] for node in nodes],
        },
        "events": events,
    }


def build_wind_arrows(wind):
    """Slim JSON-safe wind grid for the Leaflet arrow overlay.

    Only the components are sent: speed and bearing are derived in the
    browser, which keeps the payload small and the maths consistent.
    """
    if not wind:
        return []

    arrows = []
    for point in wind.get("grid", []) or []:
        try:
            arrows.append({
                "lat": round(float(point["lat"]), 5),
                "lon": round(float(point["lon"]), 5),
                "u": round(float(point["u"]), 3),
                "v": round(float(point["v"]), 3),
            })
        except (KeyError, TypeError, ValueError):
            continue

    return arrows


# =========================================================
# Vertical wind profile
# =========================================================

PROFILE_LEVELS_HPA = [1000, 975, 950, 925, 900, 850]

# Heights (above sea level, metres) used when the pressure-level API is not
# available for the flight date. 0.14 is the classic open-terrain exponent of
# the power law; it is an estimate, and the report says so.
POWER_LAW_ALPHAS = 0.14
FALLBACK_HEIGHTS_M = [10, 25, 50, 80, 120, 180, 250, 350, 500, 700, 1000, 1500]


def pressure_to_altitude_m(hpa):
    """Standard-atmosphere height for a pressure level (approximate)."""
    return 44330.0 * (1.0 - (float(hpa) / 1013.25) ** 0.1903)


def _profile_cache_path(lat, lon, date_str):
    key = "%.3f_%.3f_%s" % (float(lat), float(lon), date_str)
    digest = uuid.uuid5(uuid.NAMESPACE_URL, "windprofile:" + key).hex[:16]
    return os.path.join(CACHE_DIR, "wind_profile_%s.json" % digest)


def _read_profile_cache(lat, lon, date_str):
    path = _profile_cache_path(lat, lon, date_str)
    try:
        if os.path.exists(path) and (
            time.time() - os.path.getmtime(path) < 7 * 24 * 3600
        ):
            with open(path, "r", encoding="utf-8") as fh:
                return json.load(fh)
    except (OSError, ValueError):
        return None
    return None


def _write_profile_cache(lat, lon, date_str, data):
    path = _profile_cache_path(lat, lon, date_str)
    try:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
    except OSError:
        pass


def get_wind_profile(lat, lon, date_str, base_speed=None, base_direction=None):
    """Vertical wind profile at one point.

    Preferred source: pressure-level wind from Open-Meteo (1000-850 hPa,
    roughly 110-1450 m MSL). Those levels are only served for recent dates,
    so older flights fall back to a power-law extrapolation of the surface
    wind. The returned dict always carries 'source' so the UI can be honest.
    """
    if date_str:
        cached = _read_profile_cache(lat, lon, date_str)
        if cached:
            return cached

    levels = []

    if date_str:
        variables = []
        for level in PROFILE_LEVELS_HPA:
            variables.append("wind_speed_%dhPa" % level)
            variables.append("wind_direction_%dhPa" % level)

        params = {
            "latitude": lat,
            "longitude": lon,
            "start_date": date_str,
            "end_date": date_str,
            "hourly": ",".join(variables),
            "timezone": "UTC",
        }

        try:
            response = requests.get(
                "https://api.open-meteo.com/v1/forecast",
                params=params,
                timeout=8,
            )
            response.raise_for_status()
            hourly = response.json().get("hourly", {})
        except Exception:
            hourly = {}

        for level in PROFILE_LEVELS_HPA:
            speeds = hourly.get("wind_speed_%dhPa" % level) or []
            directions = hourly.get("wind_direction_%dhPa" % level) or []
            speed = next((v for v in speeds if v is not None), None)
            direction = next((v for v in directions if v is not None), None)
            if speed is None or direction is None:
                continue
            levels.append({
                "alt_m": round(pressure_to_altitude_m(level), 0),
                "hpa": level,
                "speed": round(float(speed), 2),
                "direction": round(float(direction), 0),
            })

        if len(levels) >= 3:
            profile = {
                "levels": sorted(levels, key=lambda item: item["alt_m"]),
                "source": "pressure_levels",
            }
            _write_profile_cache(lat, lon, date_str, profile)
            return profile

    # Fallback: power law from the surface wind we already fetched.
    if base_speed is not None and base_direction is not None:
        speed10 = max(float(base_speed), 0.0)
        levels = []
        for height in FALLBACK_HEIGHTS_M:
            factor = (height / 10.0) ** POWER_LAW_ALPHAS
            levels.append({
                "alt_m": height,
                "speed": round(speed10 * factor, 2),
                "direction": round(float(base_direction), 0),
            })
        return {"levels": levels, "source": "power_law"}

    return {"levels": [], "source": None}


def _wind_arrow_path(direction, cx, cy, length, colour):
    """Small SVG arrow pointing downwind."""
    angle = math.radians((float(direction) + 180.0) % 360.0)
    dx = math.sin(angle) * length
    dy = -math.cos(angle) * length
    x2 = cx + dx
    y2 = cy + dy

    # Perpendicular for the head.
    px = -dy / length * 4.0
    py = dx / length * 4.0

    return (
        '<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" '
        'stroke="%s" stroke-width="1.6" stroke-linecap="round"/>'
        '<polygon points="%.1f,%.1f %.1f,%.1f %.1f,%.1f" fill="%s"/>'
        % (
            cx - dx * 0.45, cy - dy * 0.45, x2 - dx * 0.15, y2 - dy * 0.15,
            colour,
            x2, y2,
            x2 - dx * 0.28 + px, y2 - dy * 0.28 + py,
            x2 - dx * 0.28 - px, y2 - dy * 0.28 - py,
            colour,
        )
    )


def render_wind_profile_svg(
    profile,
    flight_min_alt=0.0,
    flight_max_alt=None,
    ground_msl=None,
):
    """Inline SVG: wind speed against height, plus the flown height band.

    Everything is drawn as height above the take-off point. Pressure-level
    data arrives as metres above sea level, so it is shifted down by the
    terrain elevation; levels that end up below the ground are dropped.
    """
    rates = (profile or {}).get("levels") or []
    if len(rates) < 2:
        return ""

    is_msl = (profile or {}).get("source") == "pressure_levels"

    levels = []
    for level in rates:
        alt = float(level["alt_m"])
        if is_msl and ground_msl is not None:
            alt = alt - float(ground_msl)
        if alt < -5:
            continue
        levels.append({
            "alt_m": max(alt, 0.0),
            "speed": level["speed"],
            "direction": level["direction"],
        })

    if len(levels) < 2:
        return ""

    width, height = 560, 280
    left, right, top, bottom = 64, 96, 18, 40

    plot_w = width - left - right
    plot_h = height - top - bottom

    max_speed = max(level["speed"] for level in levels)
    x_max = max(5.0, math.ceil(max_speed * 1.35))

    y_max = max(level["alt_m"] for level in levels)
    y_max = max(y_max, float(flight_max_alt or 0) + 100.0, 300.0)
    y_max = math.ceil(y_max / 250.0) * 250.0

    def sx(speed):
        return left + (float(speed) / x_max) * plot_w

    def sy(alt):
        return top + plot_h - (float(alt) / y_max) * plot_h

    parts = [
        '<svg viewBox="0 0 %d %d" xmlns="http://www.w3.org/2000/svg" '
        'style="width:100%%;height:auto;max-width:640px;display:block;">'
        % (width, height)
    ]

    # Flown height band.
    if flight_max_alt and flight_max_alt > flight_min_alt:
        band_top = sy(min(float(flight_max_alt), y_max))
        band_bottom = sy(max(float(flight_min_alt), 0.0))
        parts.append(
            '<rect x="%d" y="%.1f" width="%d" height="%.1f" '
            'fill="rgba(56,189,248,0.10)"/>'
            % (left, band_top, plot_w, max(band_bottom - band_top, 1.0))
        )
        parts.append(
            '<text x="%d" y="%.1f" fill="#38bdf8" font-size="10">'
            "flown height</text>"
            % (left + 6, band_top + 12)
        )

    # Grid + y labels.
    step = 250 if y_max <= 1000 else 500
    alt = 0
    while alt <= y_max:
        y = sy(alt)
        parts.append(
            '<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" '
            'stroke="rgba(148,163,184,0.16)" stroke-width="1"/>'
            % (left, y, left + plot_w, y)
        )
        parts.append(
            '<text x="%d" y="%.1f" fill="#94a3b8" font-size="10" '
            'text-anchor="end">%d</text>' % (left - 8, y + 3, alt)
        )
        alt += step

    # X labels.
    for speed in range(0, int(x_max) + 1, max(1, int(x_max / 4))):
        x = sx(speed)
        parts.append(
            '<line x1="%.1f" y1="%d" x2="%.1f" y2="%d" '
            'stroke="rgba(148,163,184,0.10)" stroke-width="1"/>'
            % (x, top, x, top + plot_h)
        )
        parts.append(
            '<text x="%.1f" y="%d" fill="#94a3b8" font-size="10" '
            'text-anchor="middle">%d</text>' % (x, top + plot_h + 16, speed)
        )

    # Curve.
    path = " ".join(
        "%.1f,%.1f" % (sx(level["speed"]), sy(level["alt_m"]))
        for level in levels
    )
    parts.append(
        '<polyline points="%s" fill="none" stroke="#38bdf8" '
        'stroke-width="2.4" stroke-linejoin="round"/>' % path
    )

    # Dots, values and direction arrows.
    for level in levels:
        x = sx(level["speed"])
        y = sy(level["alt_m"])
        parts.append(
            '<circle cx="%.1f" cy="%.1f" r="3.4" fill="#0ea5e9" '
            'stroke="#e0f2fe" stroke-width="1"/>' % (x, y)
        )
        parts.append(
            '<text x="%.1f" y="%.1f" fill="#cbd5e1" font-size="10">'
            "%.1f m/s</text>" % (x + 8, y + 3, level["speed"])
        )
        parts.append(
            _wind_arrow_path(
                level["direction"], left + plot_w + 24, y, 14, "#94a3b8"
            )
        )
        parts.append(
            '<text x="%d" y="%.1f" fill="#64748b" font-size="9">'
            "%d\u00b0</text>"
            % (left + plot_w + 44, y + 3, int(level["direction"]))
        )

    # Axis titles.
    parts.append(
        '<text x="%.1f" y="%d" fill="#94a3b8" font-size="11" '
        'text-anchor="middle">wind speed (m/s)</text>'
        % (left + plot_w / 2, height - 8)
    )
    parts.append(
        '<text x="14" y="%.1f" fill="#94a3b8" font-size="11" '
        'text-anchor="middle" transform="rotate(-90 14 %.1f)">'
        "height above take-off (m)</text>" % (top + plot_h / 2, top + plot_h / 2)
    )

    parts.append("</svg>")
    return "".join(parts)


def build_wind_profile_payload(df, wind, flight_date, stats):
    """Profile + rendered SVG for the report page."""
    profile = get_wind_profile(
        float(pd.to_numeric(df["latitude"], errors="coerce").mean()),
        float(pd.to_numeric(df["longitude"], errors="coerce").mean()),
        flight_date,
        base_speed=(wind or {}).get("speed"),
        base_direction=(wind or {}).get("direction"),
    )

    svg = render_wind_profile_svg(
        profile,
        flight_min_alt=stats.get("min_relative_altitude") or 0.0,
        flight_max_alt=stats.get("max_relative_altitude"),
        ground_msl=stats.get("min_altitude"),
    )

    return (profile or {}).get("source"), svg


# =========================================================
# Demo
# =========================================================

@app.route(
    "/demo"
)
def demo():

    try:

        df = create_demo_flight()


        stats = calculate_statistics(
            df
        )

        health = detect_flight_health(
            df
        )


        flight_date = get_flight_date(df)


        wind = get_wind_ensemble(df, flight_date, grid_size=6)


        image_filename = (
            generate_flight_plot(
                df,
                wind
            )
        )


        image_path = os.path.join(
            GENERATED_DIR,
            image_filename
        )


        pdf_filename = (
            generate_pdf_report(
                df,
                stats,
                wind,
                image_path,
                flight_date=flight_date,
                health=health,
            )
        )


        wind_profile_source, wind_profile_svg = build_wind_profile_payload(
            df, wind, flight_date, stats
        )
        analysis = build_telemetry_payload(df, wind, health)

        return render_template_string(

            REPORT_HTML,

            stats=stats,

            wind=wind,

            map_points=build_map_points(df),

            wind_arrows=build_wind_arrows(wind),

            wind_profile_svg=wind_profile_svg,

            wind_profile_source=wind_profile_source,

            tianditu_key=TIANDITU_KEY,

            image_filename=
                image_filename,

            pdf_filename=
                pdf_filename,

            flight_date=
                flight_date,

            health=health,

            analysis_nodes=analysis["nodes"],
            analysis_series=analysis["series"],
            analysis_events=analysis["events"],

        )


    except Exception as exc:

        return f"""

        <h2>Demo failed</h2>

        <p>
            {str(exc)}
        </p >

        <p>
            <a href="/">
                Back
            </a >
        </p >

        """, 500


# =========================================================
# Health check
# =========================================================

# =========================================================
# SEO landing pages (static-ish, good for search)
# =========================================================

SEO_PAGE_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>%%TITLE%%</title>
<meta name="description" content="%%DESC%%">
<meta name="robots" content="index, follow">
<link rel="canonical" href="%%SITE%%%%PATH%%">
<meta property="og:type" content="article">
<meta property="og:site_name" content="Drone Flight Report">
<meta property="og:title" content="%%TITLE%%">
<meta property="og:description" content="%%DESC%%">
<meta property="og:url" content="%%SITE%%%%PATH%%">
<meta name="twitter:card" content="summary">
<meta name="twitter:title" content="%%TITLE%%">
<meta name="twitter:description" content="%%DESC%%">
%%EXTRA_HEAD%%
<style>
body { margin:0; font-family: Inter, system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif; background:#0b1220; color:#e2e8f0; line-height:1.75; }
.wrap { max-width:760px; margin:0 auto; padding:48px 22px; }
h1 { font-size:30px; line-height:1.25; margin:0 0 10px; }
h2 { font-size:20px; margin:30px 0 8px; }
p, li { color:#cbd5e1; }
code { background:#1e293b; padding:2px 6px; border-radius:6px; }
a.cta { display:inline-block; margin:26px 0; padding:14px 24px; background:#2563eb; color:#fff; text-decoration:none; border-radius:12px; font-weight:600; }
.muted { color:#94a3b8; font-size:14px; }
.crumbs { font-size:14px; color:#94a3b8; margin-bottom:18px; }
.crumbs a { color:#60a5fa; text-decoration:none; }
.related { padding-left:20px; }
.related li { margin:6px 0; }
.related a { color:#60a5fa; text-decoration:none; }
.note { border-left:3px solid #2563eb; padding:2px 0 2px 14px; color:#94a3b8; }
footer { margin-top:44px; color:#64748b; font-size:13px; }
</style>
</head>
<body>
<div class="wrap">
<p class="crumbs"><a href="/">Drone Flight Report</a> / <span>%%H1%%</span></p>
<h1>%%H1%%</h1>
%%BODY%%
<a class="cta" href="/">Analyze a flight log free &rarr;</a>
%%RELATED%%
<footer>Free &middot; no sign-up &middot; privacy-first &middot; <a href="/privacy" style="color:#60a5fa;text-decoration:none;">Privacy</a></footer>
</div>
</body>
</html>
"""


def render_seo_page(page, path):
    extra_head = []

    breadcrumb_ld = {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {
                "@type": "ListItem",
                "position": 1,
                "name": "Home",
                "item": SITE_URL + "/",
            },
            {
                "@type": "ListItem",
                "position": 2,
                "name": page["h1"],
                "item": SITE_URL + path,
            },
        ],
    }
    extra_head.append(
        '<script type="application/ld+json">%s</script>'
        % json.dumps(breadcrumb_ld, ensure_ascii=False)
    )

    if page.get("faqs"):
        faq_ld = {
            "@context": "https://schema.org",
            "@type": "FAQPage",
            "mainEntity": [
                {
                    "@type": "Question",
                    "name": question,
                    "acceptedAnswer": {
                        "@type": "Answer",
                        "text": answer,
                    },
                }
                for question, answer in page["faqs"]
            ],
        }
        extra_head.append(
            '<script type="application/ld+json">%s</script>'
            % json.dumps(faq_ld, ensure_ascii=False)
        )

    related_items = []
    all_paths = list(SEO_PAGES)
    start_index = (all_paths.index(path) + 1) if path in all_paths else 0
    for offset in range(len(all_paths)):
        other_path = all_paths[(start_index + offset) % len(all_paths)]
        if other_path == path:
            continue
        other_page = SEO_PAGES[other_path]
        label = other_page["h1"].split("(")[0].strip()
        related_items.append(
            '<li><a href="%s">%s</a></li>' % (other_path, label)
        )
        if len(related_items) >= 6:
            break

    related_html = ""
    if related_items:
        related_html = (
            "<h2>Related tools</h2>\n<ul class=\"related\">\n"
            + "\n".join(related_items)
            + "\n</ul>"
        )

    return (SEO_PAGE_TEMPLATE
            .replace("%%SITE%%", SITE_URL)
            .replace("%%TITLE%%", page["title"])
            .replace("%%DESC%%", page["desc"])
            .replace("%%PATH%%", path)
            .replace("%%H1%%", page["h1"])
            .replace("%%BODY%%", page["body"])
            .replace("%%EXTRA_HEAD%%", "\n".join(extra_head))
            .replace("%%RELATED%%", related_html))


SEO_PAGES = {

    "/dji-flight-log": {
        "title": "DJI Flight Log Analyzer - Free Online Tool | Drone Flight Report",
        "desc": "Upload a DJI flight log (CSV/TXT) and get a flight-track map, "
                "statistics, wind reference, flight-health check and a PDF report. "
                "Free, no sign-up, privacy-first.",
        "h1": "DJI Flight Log Analyzer (Free, Online)",
        "body": """
<p>Exported a DJI flight log and not sure what to do with it? Drop your
<strong>DJI CSV/TXT</strong> log into Drone Flight Report and get a clear
report in seconds - right in your browser, nothing to install.</p>
<h2>What you get</h2>
<ul>
<li>Flight track map (auto-detects latitude / longitude / altitude)</li>
<li>Distance, max altitude, duration and speed statistics</li>
<li>Regional wind reference for the flight date and area</li>
<li>Automated flight-health check (GPS quality, time gaps, altitude/speed anomalies)</li>
<li>A downloadable PDF report you can share with clients</li>
</ul>
<h2>How to export a DJI log</h2>
<ol>
<li>In the DJI app, open <em>Flight Records</em> and share/export the flight.</li>
<li>Or copy the <code>.txt</code> / <code>.csv</code> from the DJI flight-record folder.</li>
<li>Upload it here.</li>
</ol>
<h2>Privacy</h2>
<p>Your raw log is used only to build your report and is deleted after
processing. Sharing is opt-in and always de-identified.</p>
<h2>FAQ</h2>
<p><strong>Is it free?</strong> Yes.</p>
<p><strong>Do I need an account?</strong> No.</p>
""",
        "faqs": [
            ("Is the DJI flight log analyzer free?",
             "Yes. Upload a DJI CSV/TXT log and generate the map, statistics and PDF at no cost."),
            ("Do I need a DJI account or app login?",
             "No. Only the exported log file is needed."),
            ("What DJI file types are supported?",
             "Delimited CSV or TXT telemetry containing latitude, longitude, altitude and time fields."),
        ],
    },

    "/ardupilot-bin": {
        "title": "ArduPilot .bin Flight Log Analyzer - Free Online | Drone Flight Report",
        "desc": "Analyze ArduPilot (.bin) flight logs online for free: flight track, "
                "statistics, wind reference, flight-health check and a PDF report. "
                "No sign-up, privacy-first.",
        "h1": "ArduPilot .bin Flight Log Analyzer (Free, Online)",
        "body": """
<p>Got an ArduPilot dataflash <strong>.bin</strong> log from your flight
controller? Upload it here and get a readable report directly in the browser.</p>
<h2>What you get</h2>
<ul>
<li>Flight track map from the log's GPS data</li>
<li>Distance, max altitude, duration and speed statistics</li>
<li>Regional wind reference for the flight date and area</li>
<li>Flight-health check (GPS quality, logging gaps, altitude/speed anomalies)</li>
<li>Downloadable PDF report</li>
</ul>
<h2>Where .bin logs come from</h2>
<p>ArduPilot / Mission Planner stores these on the flight controller's SD card
under <code>/APM/LOGS</code>. Copy the file and upload it - no desktop software
required.</p>
<h2>Privacy</h2>
<p>The raw log is deleted after your report is generated. Sharing is opt-in and
de-identified.</p>
<h2>FAQ</h2>
<p><strong>Do I need Mission Planner?</strong> No, this runs in your browser.</p>
<p><strong>Is my log uploaded to a server?</strong> Only to build your report, then deleted.</p>
""",
        "faqs": [
            ("Can I open an ArduPilot .bin log without Mission Planner?",
             "Yes. Upload the .bin file and the report is generated in your browser."),
            ("Where are ArduPilot DataFlash logs stored?",
             "On the flight controller SD card, usually under /APM/LOGS."),
            ("How long is my uploaded log kept?",
             "It is deleted immediately after the report is generated."),
        ],
    },

    "/px4-ulg": {
        "title": "PX4 .ulg Flight Log Analyzer - Free Online | Drone Flight Report",
        "desc": "Analyze PX4 ULog (.ulg) flight logs online for free: flight track, "
                "statistics, wind reference, flight-health check and a PDF report.",
        "h1": "PX4 .ulg Flight Log Analyzer (Free, Online)",
        "body": """
<p>Upload a PX4 <strong>.ulg</strong> (ULog) file from QGroundControl or your
flight controller and get a clear flight report - in the browser, no install.</p>
<h2>What you get</h2>
<ul>
<li>Flight track map from logged GPS positions</li>
<li>Distance, max altitude, duration and speed statistics</li>
<li>Regional wind reference (including the flight's own wind estimate when present)</li>
<li>Flight-health check</li>
<li>Downloadable PDF report</li>
</ul>
<h2>Where .ulg logs come from</h2>
<p>PX4 logs live on the SD card (<code>/log/</code>) and can be downloaded via
QGroundControl &rarr; <em>Analyze Tools &rarr; Log Download</em>.</p>
<h2>Privacy</h2>
<p>Raw logs are deleted after processing; optional sharing is de-identified.</p>
<h2>FAQ</h2>
<p><strong>Free?</strong> Yes, no sign-up.</p>
""",
        "faqs": [
            ("How do I open a PX4 .ulg file online?",
             "Upload the .ulg file; the ULog is parsed and a visual report is generated."),
            ("Do I need QGroundControl?",
             "Only to download the log if you do not already have the file. Analysis happens in the browser."),
            ("Does the report include wind data?",
             "Yes, using the log's wind estimate when available, otherwise a regional weather reference."),
        ],
    },

    "/vs-airdata": {
        "title": "Drone Flight Report vs AirData - Free, Privacy-First Alternative",
        "desc": "How Drone Flight Report compares with AirData: cross-vendor logs "
                "(DJI, ArduPilot, PX4), no sign-up, privacy-first, free browser reports.",
        "h1": "Drone Flight Report vs AirData",
        "body": """
<p>AirData is a well-known drone log service. Drone Flight Report takes a
different angle: <strong>cross-vendor, no account, privacy-first, free</strong>.</p>
<h2>At a glance</h2>
<ul>
<li><strong>Vendors:</strong> DJI CSV/TXT, ArduPilot .bin and PX4 .ulg - in one tool.</li>
<li><strong>Sign-up:</strong> none. Upload and get a report.</li>
<li><strong>Privacy:</strong> raw log deleted after processing; sharing is opt-in and de-identified.</li>
<li><strong>Output:</strong> flight track, statistics, wind reference, health check and a PDF.</li>
<li><strong>Price:</strong> free to use.</li>
</ul>
<h2>When AirData may fit better</h2>
<p>If you need long-term cloud history, fleet management and deep analytics across
many aircraft, a dedicated platform can help. For a quick, private, no-account
report from any vendor's log, try Drone Flight Report.</p>
""",
        "faqs": [
            ("Is Drone Flight Report a free alternative to AirData?",
             "Yes. Core analysis, the satellite map and the PDF report are free with no account."),
            ("Does it support the same log types as AirData?",
             "It handles DJI CSV/TXT, ArduPilot .bin and PX4 .ulg in one tool."),
            ("Can I keep long-term flight history?",
             "The free tool is report-focused. For fleet history and team management, a dedicated platform may fit better."),
        ],
    },

    "/vs-flight-reader": {
        "title": "Drone Flight Report vs Flight Reader - Free Cross-Vendor Alternative",
        "desc": "How Drone Flight Report compares with Flight Reader: cross-vendor "
                "(DJI / ArduPilot / PX4), no sign-up, free browser reports.",
        "h1": "Drone Flight Report vs Flight Reader",
        "body": """
<p>Flight Reader is a well-known DJI-focused log tool (desktop app plus a web
version). Drone Flight Report takes a different angle:
<strong>cross-vendor, no account, privacy-first, free</strong>.</p>
<h2>At a glance</h2>
<ul>
<li><strong>Vendors:</strong> DJI CSV/TXT, ArduPilot .bin and PX4 .ulg in one tool
(Flight Reader is mainly DJI).</li>
<li><strong>Sign-up:</strong> none - upload and get a report.</li>
<li><strong>Where it runs:</strong> any browser, no install (Flight Reader desktop is Windows-only).</li>
<li><strong>Output:</strong> flight track, statistics, wind reference, health check and a PDF.</li>
<li><strong>Price:</strong> free to use.</li>
</ul>
<h2>When Flight Reader may fit better</h2>
<p>If you need the deepest possible DJI field extraction or an offline Windows
desktop workflow, a specialised tool can help. For a quick, private, no-account
report from any vendor's log, try Drone Flight Report.</p>
""",
        "faqs": [
            ("Is Drone Flight Report a free alternative to Flight Reader?",
             "Yes, and it also accepts ArduPilot and PX4 logs, not only DJI files."),
            ("Does it run on Mac or Linux?",
             "Yes. It is browser-based, so any modern operating system works."),
            ("Do I need to install anything?",
             "No. Upload the log and the report is generated online."),
        ],
    },

    "/vs-px4-review": {
        "title": "Drone Flight Report vs PX4 Flight Review - Online Log Analyzer",
        "desc": "Drone Flight Report vs PX4 Flight Review: a free, browser-based "
                "analyzer that also handles DJI and ArduPilot logs, plus a PDF report.",
        "h1": "Drone Flight Report vs PX4 Flight Review",
        "body": """
<p>PX4 Flight Review is the official PX4 log tool (.ulg) - powerful for
developers, but PX4-only and developer-oriented. Drone Flight Report is a
<strong>general-purpose analyzer for pilots</strong>.</p>
<h2>At a glance</h2>
<ul>
<li><strong>Vendors:</strong> PX4 .ulg <em>plus</em> DJI CSV/TXT and ArduPilot .bin.</li>
<li><strong>Audience:</strong> pilots who want a clear report, not just developer plots.</li>
<li><strong>Output:</strong> flight track, statistics, regional wind reference, flight-health
check and a downloadable PDF.</li>
<li><strong>Sign-up:</strong> none. <strong>Price:</strong> free.</li>
</ul>
<h2>When PX4 Flight Review may fit better</h2>
<p>If you are debugging PX4 firmware internals, the official tool (or a local
QGroundControl setup) is the right place. For a quick, shareable report, try
Drone Flight Report.</p>
""",
        "faqs": [
            ("Is this a replacement for PX4 Flight Review?",
             "For pilot-facing reports, yes. For firmware-level debugging and full plot stacks, the official Flight Review remains more suitable."),
            ("Does it analyze non-PX4 logs?",
             "Yes. DJI CSV/TXT and ArduPilot .bin logs are supported too."),
            ("Do I need a PX4 account?",
             "No account is required."),
        ],
    },

    "/drone-flight-log-viewer": {
        "title": "Drone Flight Log Viewer - Free Online (DJI, ArduPilot, PX4)",
        "desc": "Free online drone flight log viewer. Upload a DJI CSV/TXT, "
                "ArduPilot .bin or PX4 .ulg log and see the flight track on a "
                "satellite map, plus statistics and a PDF report. No sign-up.",
        "h1": "Drone Flight Log Viewer (Free, Online)",
        "body": """
<p>A flight log is only useful when you can actually see what happened.
Drone Flight Report turns a raw telemetry file into a visual flight track,
readable statistics and a shareable PDF - in your browser, with nothing to
install.</p>
<h2>What the viewer shows</h2>
<ul>
<li>An interactive satellite map with the full flight path, start and end points</li>
<li>Distance flown, maximum and mean altitude, duration and GPS point count</li>
<li>A regional wind reference for the flight date and location</li>
<li>An automated flight-health check for GPS gaps, altitude jumps and speed spikes</li>
<li>A downloadable PDF report for your records or your client</li>
</ul>
<h2>Supported files</h2>
<p>DJI telemetry exported as <code>.csv</code> or <code>.txt</code>,
ArduPilot DataFlash <code>.bin</code>, and PX4 ULog <code>.ulg</code>.
The tool looks for latitude, longitude, altitude, time and speed fields and
normalises them before analysis.</p>
<h2>Why use a browser viewer?</h2>
<p>Desktop log tools are powerful but tied to one computer and one vendor.
This viewer works on any laptop, tablet or phone, handles logs from three
ecosystems, and produces a report you can send to someone who does not own
the same software.</p>
<h2>Privacy</h2>
<p>Your uploaded log is processed in a temporary file and deleted immediately
after the report is generated. Optional data sharing is off by default and
always de-identified.</p>
""",
        "faqs": [
            ("Is the drone flight log viewer free?",
             "Yes. Uploading a log and generating the map, statistics and PDF is free, with no account required."),
            ("Which drone brands are supported?",
             "DJI CSV/TXT telemetry, ArduPilot .bin and PX4 .ulg are supported. Other formats work if they contain standard latitude, longitude and altitude columns."),
            ("Is my flight log stored?",
             "No. The original upload is deleted right after processing. Generated reports are removed automatically after 24 hours."),
        ],
    },

    "/drone-flight-log-to-pdf": {
        "title": "Drone Flight Log to PDF Report - Free Online Converter",
        "desc": "Turn a drone flight log into a clean PDF report: satellite track "
                "map, distance, altitude, wind reference and flight-health check. "
                "Free, browser-based, no sign-up.",
        "h1": "Drone Flight Log to PDF Report",
        "body": """
<p>Clients, insurers and flight supervisors rarely want a raw telemetry file.
They want a one-page document that shows where the aircraft flew and whether
anything looked wrong. Drone Flight Report generates that PDF automatically
from your log.</p>
<h2>What is in the PDF</h2>
<ul>
<li>Flight date and summary statistics</li>
<li>The trajectory image with start and end markers</li>
<li>Altitude, distance and duration figures</li>
<li>The regional wind reference used for the flight</li>
<li>Flight-health findings, when anomalies are detected</li>
</ul>
<h2>How to convert a log</h2>
<ol>
<li>Upload a DJI CSV/TXT, ArduPilot .bin or PX4 .ulg file.</li>
<li>Wait for the browser report to finish.</li>
<li>Click <em>Download PDF Report</em>.</li>
</ol>
<p>The PDF is generated server-side and is available for 24 hours. No desktop
software, spreadsheet macros or account are needed.</p>
<h2>Good use cases</h2>
<p>Site surveys, roof and facade inspections, mapping missions, training
flights and incident reviews all benefit from a consistent report format.
Because the same pipeline handles DJI, ArduPilot and PX4, mixed fleets produce
comparable documents.</p>
<h2>Privacy note</h2>
<p>The raw log is deleted after conversion. The PDF and track image expire
automatically, and sharing de-identified data is opt-in.</p>
""",
        "faqs": [
            ("Can I convert a DJI log to PDF for free?",
             "Yes. Upload the exported CSV or TXT telemetry and download the generated PDF at no cost."),
            ("Does the PDF include GPS coordinates?",
             "The report shows the flight track and statistics. Raw coordinates are not published or added to the optional shared dataset."),
            ("How long is the PDF available?",
             "Generated reports are kept for 24 hours and then deleted automatically."),
        ],
    },

    "/ardupilot-bin-viewer": {
        "title": "ArduPilot .bin Viewer - Free Online Flight Log Analysis",
        "desc": "View an ArduPilot DataFlash .bin log online without Mission Planner. "
                "Get a satellite flight track, altitude and distance statistics, "
                "wind reference and a PDF report.",
        "h1": "ArduPilot .bin Viewer (Online)",
        "body": """
<p>ArduPilot writes DataFlash logs to the flight controller's SD card. They are
compact, detailed and awkward to read without the right desktop software.
This viewer parses the GPS and attitude streams in your browser and turns them
into a flight report.</p>
<h2>What is read from the .bin</h2>
<ul>
<li>GPS position, altitude and ground speed</li>
<li>Attitude and heading where available</li>
<li>Satellite count and GPS quality indicators</li>
<li>Flight timing, used to reconstruct elapsed time</li>
</ul>
<h2>Where to find the log</h2>
<p>Remove the SD card from the flight controller and look under
<code>/APM/LOGS</code>. Files are usually named with a date and sequence
number. Copy the newest <code>.bin</code> file and upload it here.</p>
<h2>What you get</h2>
<p>A satellite track map, distance and altitude statistics, a regional wind
reference, a flight-health check and a PDF report. The health check flags GPS
dropouts, large time gaps, altitude jumps and implausible speed values.</p>
<h2>Limitations</h2>
<p>This is a pilot-facing report, not a replacement for Mission Planner's
full parameter and vibration analysis. Use it for a quick visual review,
client documentation or a second opinion before deeper tuning.</p>
""",
        "faqs": [
            ("Do I need Mission Planner to open a .bin file?",
             "No. Upload the .bin file directly and the report is generated online."),
            ("Where are ArduPilot logs stored?",
             "On the flight controller SD card, normally under /APM/LOGS."),
            ("Can I view a .bin log on a phone?",
             "Yes, the viewer and report work in a mobile browser, although a larger screen is easier for reading the map."),
        ],
    },

    "/px4-ulg-viewer": {
        "title": "PX4 .ulg Viewer - Free Online ULog Analysis",
        "desc": "Open a PX4 ULog (.ulg) file online and get a satellite flight track, "
                "distance, altitude, wind reference, health check and PDF report. "
                "Free and browser-based.",
        "h1": "PX4 .ulg Viewer (Online ULog Analysis)",
        "body": """
<p>PX4 stores flight data as ULog files. They contain a lot of useful
information, but reading them usually means installing QGroundControl or
running the PX4 Flight Review stack. This viewer gives pilots a faster path to
the essentials.</p>
<h2>What is extracted</h2>
<ul>
<li>GPS latitude, longitude and altitude</li>
<li>Local position and velocity where logged</li>
<li>Battery and flight-mode context, when available</li>
<li>The log's own wind estimate, if the flight recorded one</li>
<li>Timing information for elapsed flight time</li>
</ul>
<h2>How to get the .ulg file</h2>
<p>Open QGroundControl, connect the flight controller, go to
<em>Analyze Tools &rarr; Log Download</em>, select the flight and download the
<code>.ulg</code> file. You can also copy it from the SD card's
<code>/log</code> directory.</p>
<h2>What the report includes</h2>
<p>A satellite map with the flight path, start and end markers, distance and
altitude statistics, a regional wind reference, a health check and a
downloadable PDF.</p>
<h2>PX4 Flight Review vs this viewer</h2>
<p>Flight Review is excellent for firmware-level debugging and full plot
stacks. This tool is aimed at pilots and clients who need a clear, shareable
summary across PX4, ArduPilot and DJI logs.</p>
""",
        "faqs": [
            ("How do I open a .ulg file without QGroundControl?",
             "Upload the .ulg file here. The parser reads the ULog structure directly and builds the report in your browser."),
            ("Does the viewer support PX4 wind estimates?",
             "Yes. When the log contains a wind estimate it is used as the primary wind source; otherwise a regional weather reference is shown."),
            ("Is the .ulg file kept on the server?",
             "No. It is processed in a temporary file and deleted immediately afterwards."),
        ],
    },

    "/dji-mini-3-flight-log": {
        "title": "DJI Mini 3 Flight Log - Export and Analyze It Free",
        "desc": "How to find and analyze DJI Mini 3 flight logs: export the telemetry, "
                "view the flight track on a satellite map, check distance, altitude "
                "and GPS health, and download a PDF report.",
        "h1": "DJI Mini 3 Flight Log: Export and Analyze",
        "body": """
<p>The DJI Mini 3 is a popular sub-250 g drone for travel and light commercial
work. Its flight logs are useful for checking where you flew, how high you
went and whether GPS or battery behaviour deserves attention.</p>
<h2>Where the logs live</h2>
<p>DJI stores flight records in the DJI Fly app and, depending on the model and
firmware, on the aircraft itself. App records are convenient for replay but are
not always a plain CSV. For analysis, use a CSV/TXT export produced by DJI
Assistant 2, a trusted log converter, or your own telemetry recorder.</p>
<h2>Analyzing a Mini 3 log</h2>
<ol>
<li>Export or obtain a CSV/TXT file that contains latitude, longitude,
altitude and time fields.</li>
<li>Upload it to Drone Flight Report.</li>
<li>Review the satellite track, distance, maximum altitude and health check.</li>
<li>Download the PDF if you need a record for a client or insurance file.</li>
</ol>
<h2>What to check after a Mini 3 flight</h2>
<ul>
<li><strong>Max altitude:</strong> confirm you stayed inside your local limit.</li>
<li><strong>Distance:</strong> useful for mapping and inspection coverage.</li>
<li><strong>GPS quality:</strong> sudden satellite drops can explain drift or
RTH behaviour.</li>
<li><strong>Wind reference:</strong> a regional reference helps interpret
battery drain and ground speed.</li>
</ul>
<p class="note">Compatibility note: the analyzer reads delimited CSV/TXT
telemetry, not DJI's encrypted internal binary logs. If your export opens as
readable columns in a spreadsheet, it will work here.</p>
""",
        "faqs": [
            ("Can I upload a DJI Mini 3 log directly from DJI Fly?",
             "DJI Fly does not expose a universal CSV export for every firmware version. Export the telemetry to CSV/TXT first, then upload that file."),
            ("What can I learn from a Mini 3 flight log?",
             "Flight path, distance, maximum and mean altitude, duration, GPS quality and a regional wind reference."),
            ("Is the Mini 3 log analysis free?",
             "Yes, including the satellite map and PDF report."),
        ],
    },

    "/dji-air-3-flight-log": {
        "title": "DJI Air 3 Flight Log - Free Online Analysis",
        "desc": "Analyze a DJI Air 3 flight log online: satellite track map, distance, "
                "altitude, wind reference, GPS health check and a downloadable PDF. "
                "No account needed.",
        "h1": "DJI Air 3 Flight Log Analysis",
        "body": """
<p>The DJI Air 3 carries two cameras and flies longer missions than the Mini
series, so its logs often cover inspection, mapping and content flights that
are worth documenting properly.</p>
<h2>Getting a usable file</h2>
<p>DJI's app records are designed for replay, not spreadsheet analysis. To use
this tool, obtain a CSV/TXT telemetry export with latitude, longitude,
altitude and timestamp columns. DJI Assistant 2, a reputable converter, or a
separate flight-recording app can produce one.</p>
<h2>What the report shows</h2>
<ul>
<li>Full flight path on satellite imagery</li>
<li>Distance flown and altitude range</li>
<li>Flight duration and GPS point count</li>
<li>Regional wind reference for the flight area and date</li>
<li>Automated health screening for GPS gaps and telemetry anomalies</li>
<li>PDF export for client documentation</li>
</ul>
<h2>Why document Air 3 flights?</h2>
<p>For commercial work, a consistent flight record helps with client reports,
site handover and insurance questions. For recreational flights, it is a
simple way to review a location before flying it again.</p>
<h2>Privacy</h2>
<p>Uploads are temporary and deleted after processing. Generated reports expire
after 24 hours. Optional sharing is de-identified and off by default.</p>
""",
        "faqs": [
            ("Does the tool read DJI Air 3 logs directly?",
             "It reads CSV/TXT telemetry exports. Convert or export the log to a delimited text file first."),
            ("Can I see the Air 3 flight path on a satellite map?",
             "Yes, the report includes an interactive satellite map with start and end markers."),
            ("Is there a file size limit?",
             "Uploads are limited to 100 MB, which is far above a typical Air 3 telemetry export."),
        ],
    },

    "/dji-mavic-3-flight-log": {
        "title": "DJI Mavic 3 Flight Log - Free Online Analyzer",
        "desc": "Upload a DJI Mavic 3 telemetry export and get a satellite track map, "
                "distance and altitude statistics, wind reference, health check "
                "and PDF report. Free and private.",
        "h1": "DJI Mavic 3 Flight Log Analyzer",
        "body": """
<p>Mavic 3 flights are often longer and more expensive to repeat than a
recreational hop. A clear log report makes it easier to verify coverage,
altitude discipline and aircraft behaviour after the fact.</p>
<h2>What you can verify</h2>
<ul>
<li>Whether the planned area was actually covered</li>
<li>Maximum and mean altitude above the takeoff point</li>
<li>Distance flown and time in the air</li>
<li>GPS satellite count and quality flags</li>
<li>Regional wind conditions for the flight date</li>
</ul>
<h2>Preparing the log</h2>
<p>Export the flight telemetry to CSV or TXT. The file should contain columns
for latitude, longitude, altitude and time; speed, heading and satellite count
are helpful but optional. The analyzer normalises common column names
automatically.</p>
<h2>Report output</h2>
<p>The result page includes an interactive satellite map, summary statistics,
a flight-health score and a PDF download. The map supports Esri global
imagery, 高德 satellite imagery in China and an optional 天地图 layer.</p>
<h2>Good practice</h2>
<p>Keep the original log until the report has been reviewed, then rely on the
PDF for records. Do not upload logs that contain sensitive site coordinates
unless you are comfortable processing them on a web service.</p>
""",
        "faqs": [
            ("Can I analyze a Mavic 3 log without installing software?",
             "Yes. The analyzer runs in the browser; you only need a CSV/TXT telemetry export."),
            ("Does the report include a satellite map?",
             "Yes, with the flight path, start and end points and switchable basemaps."),
            ("Are Mavic 3 Enterprise logs supported?",
             "Any delimited telemetry export with standard GPS and altitude fields can be processed."),
        ],
    },

    "/dji-neo-flight-log": {
        "title": "DJI Neo Flight Log - Free Online Flight Analysis",
        "desc": "Analyze DJI Neo flight logs online: view the track on a satellite map, "
                "check distance, altitude and GPS health, and download a PDF report. "
                "Free, no sign-up.",
        "h1": "DJI Neo Flight Log Analysis",
        "body": """
<p>The DJI Neo is small, light and often flown close to people and objects.
Even short flights benefit from a quick log review, especially when you are
learning the aircraft or documenting a commercial visit.</p>
<h2>What to look at first</h2>
<ul>
<li><strong>Track shape:</strong> did the aircraft go where you intended?</li>
<li><strong>Altitude:</strong> confirm clearance over obstacles and local limits.</li>
<li><strong>GPS quality:</strong> short flights near buildings can lose satellites.</li>
<li><strong>Distance:</strong> useful for comparing repeated shots or routes.</li>
</ul>
<h2>Exporting the telemetry</h2>
<p>As with other DJI models, the app's replay data is not always a plain CSV.
Use DJI Assistant 2 or a trusted converter to produce a CSV/TXT file with
latitude, longitude, altitude and time. Then upload it here.</p>
<h2>Report features</h2>
<p>You get an interactive satellite map, distance and altitude statistics, a
regional wind reference, a health check and a PDF report. The same report
format works for Mini, Air, Mavic, ArduPilot and PX4 logs, which makes fleet
records easier to compare.</p>
<h2>Privacy</h2>
<p>Uploads are deleted immediately after processing. Generated files expire
after 24 hours, and optional sharing is de-identified.</p>
""",
        "faqs": [
            ("Is there a minimum flight length for analysis?",
             "The log needs at least two valid GPS points and a usable time field."),
            ("Can I use this on a phone?",
             "Yes, upload and view the report in a mobile browser."),
            ("Does it work with DJI Neo app recordings?",
             "Only if you can export them as CSV/TXT telemetry with GPS and altitude columns."),
        ],
    },

    "/how-to-read-drone-flight-log": {
        "title": "How to Read a Drone Flight Log - Beginner Guide",
        "desc": "A practical guide to drone flight logs: what latitude, longitude, "
                "altitude, speed, heading and satellite count mean, which problems "
                "to look for, and how to turn a log into a visual report.",
        "h1": "How to Read a Drone Flight Log",
        "body": """
<p>A drone flight log is a time-stamped record of what the aircraft and its
sensors were doing. Most logs look intimidating at first because they contain
dozens of fields recorded several times per second. You only need a handful of
them for a useful review.</p>
<h2>The core fields</h2>
<ul>
<li><strong>Timestamp:</strong> when each sample was recorded. Gaps can mean a
logging stall or a power interruption.</li>
<li><strong>Latitude / longitude:</strong> the aircraft position. Plotting these
produces the flight track.</li>
<li><strong>Altitude:</strong> height above takeoff or above sea level,
depending on the source. Always check which reference is used.</li>
<li><strong>Ground speed:</strong> how fast the aircraft moved over the ground,
not through the air.</li>
<li><strong>Heading:</strong> the direction the nose was pointing.</li>
<li><strong>Satellite count / GPS quality:</strong> how confident the position
fix was.</li>
</ul>
<h2>What commonly goes wrong</h2>
<p>Large time gaps, sudden altitude jumps, impossible speed values and long
periods with few satellites are the usual warning signs. A single odd sample
can be noise; a sustained pattern is worth investigating.</p>
<h2>Read the track, not just the numbers</h2>
<p>A table tells you the maximum altitude. A map tells you where that altitude
occurred, whether the aircraft drifted, and whether the return path was
straight. Putting the log on satellite imagery makes those patterns obvious.</p>
<h2>Turn a log into a report</h2>
<p>Upload a DJI CSV/TXT, ArduPilot .bin or PX4 .ulg file to Drone Flight Report.
The tool extracts the core fields, draws the track, checks for anomalies and
produces a PDF you can keep or share.</p>
""",
        "faqs": [
            ("What is the most important field in a drone flight log?",
             "For most reviews, the GPS position and timestamp matter most because they establish where the aircraft was and when."),
            ("What does a gap in the log mean?",
             "It can indicate a logging pause, a processor stall or a power issue. Check whether other fields also stop at the same time."),
            ("Can I read a flight log without special software?",
             "You can open a CSV in a spreadsheet, but a visual analyzer is much faster for track and anomaly review."),
        ],
    },

    "/about": {
        "title": "About Drone Flight Report - Free, Privacy-First Log Analysis",
        "desc": "Drone Flight Report is an independent, browser-based analyzer for "
                "DJI, ArduPilot and PX4 flight logs. Free core tool, no sign-up, "
                "privacy-first by design.",
        "h1": "About Drone Flight Report",
        "body": """
<p>Drone Flight Report is an independent, browser-based tool for turning raw
drone telemetry into a clear flight report. It was built for pilots who want
answers quickly, without installing desktop software or handing their logs to
a fleet-management platform.</p>
<h2>Why it exists</h2>
<p>Flight logs contain the evidence of what happened in the air: where the
aircraft flew, how high it went, how the GPS behaved and what the wind was
doing. Most tools that expose this are tied to one vendor, require an account,
or are designed for engineers rather than pilots. Drone Flight Report takes a
different approach: upload a log, get a visual report, keep your data private.</p>
<h2>Principles</h2>
<ul>
<li><strong>Cross-vendor:</strong> DJI CSV/TXT, ArduPilot .bin and PX4 .ulg in one place.</li>
<li><strong>No sign-up:</strong> the core analyzer works without an account.</li>
<li><strong>Privacy-first:</strong> the original upload is deleted after processing;
sharing de-identified data is opt-in.</li>
<li><strong>Honest limits:</strong> the wind layer is a regional reference, not a
claim of onboard measurement, and the report is not a certified maintenance tool.</li>
</ul>
<h2>Who it is for</h2>
<p>Commercial drone operators, inspection and mapping pilots, flight schools,
repair shops, insurance reviewers and hobbyists who want a second pair of eyes
on a flight.</p>
<h2>What it is not</h2>
<p>It is not a replacement for manufacturer diagnostics, firmware-level
debugging in PX4 Flight Review or Mission Planner, or a certified airworthiness
inspection. Use it as a fast, readable first review.</p>
<p>Questions or feedback? <a href="/contact" style="color:#60a5fa;">Contact us</a>.</p>
""",
        "faqs": [
            ("Who runs Drone Flight Report?",
             "It is an independent project focused on practical, privacy-first flight-log analysis."),
            ("Is the tool really free?",
             "The core analyzer, satellite map and PDF report are free. Any future paid features will be optional."),
            ("Can I use it for commercial work?",
             "Yes, you can use the reports in your own workflow. They are not a substitute for certified inspections."),
        ],
    },

    "/methodology": {
        "title": "Methodology - How Drone Flight Logs Are Analyzed",
        "desc": "How Drone Flight Report parses, normalizes, validates and analyzes "
                "DJI, ArduPilot and PX4 logs, including wind sources, statistics "
                "and the flight-health score.",
        "h1": "Methodology: How the Analysis Works",
        "body": """
<p>This page explains what happens between uploading a log and downloading a
report, so you can judge whether the output fits your use case.</p>
<h2>1. Parsing</h2>
<p>CSV and TXT files are read with common encodings and delimiters. ArduPilot
DataFlash <code>.bin</code> files are read from their GPS and attitude streams.
PX4 <code>.ulg</code> files are read as ULog data. Unsupported or corrupt files
are rejected with a user-facing error.</p>
<h2>2. Normalisation</h2>
<p>Every format is mapped into one internal schema: UTC timestamp, elapsed
seconds, latitude, longitude, altitude, relative altitude, speed, heading, GPS
satellites and GPS quality. Column names, units and common export quirks are
normalised before analysis.</p>
<h2>3. Validation</h2>
<p>A report is only generated when the log has at least two valid GPS points,
plausible latitude/longitude ranges, a usable trajectory and reconstructable
flight time. Invalid coordinates are rejected rather than plotted.</p>
<h2>4. Statistics</h2>
<p>Distance is calculated with the haversine formula between consecutive GPS
points. Altitude statistics use the altitude field available in the log; the
reference (above takeoff or above sea level) depends on the source format.
Duration and speed are derived from the logged time and speed fields.</p>
<h2>5. Wind reference</h2>
<p>The wind layer combines regional historical weather data (Open-Meteo and
NASA POWER). When the log contains its own wind estimate, that estimate is used
as the primary source. The report also shows a flight-weighted wind value based
on time spent at each altitude. This is a regional reference, not a local
real-time measurement.</p>
<h2>6. Flight-health score</h2>
<p>The score screens for GPS quality problems, timeline gaps, altitude jumps
and implausible speed values. It is a heuristic review aid, not a
certification or a maintenance diagnosis.</p>
<h2>7. Privacy and retention</h2>
<p>The original upload is processed in a temporary file and deleted immediately.
Generated images and PDFs expire after 24 hours. Optional sharing is
de-identified and off by default.</p>
<h2>Limitations</h2>
<p>GPS accuracy varies by receiver and environment. Logged altitude references
differ between vendors. Wind data is regional, not onboard. The report should
be read alongside the original log and, where safety or airworthiness is at
stake, a qualified professional.</p>
""",
        "faqs": [
            ("What wind data sources are used?",
             "Open-Meteo and NASA POWER regional historical data, plus the log's own wind estimate when available."),
            ("Is the flight-health score a certification?",
             "No. It is a heuristic screening aid, not a maintenance or airworthiness certification."),
            ("What happens to my uploaded log?",
             "It is deleted immediately after the report is generated. Generated files expire after 24 hours."),
        ],
    },

    "/sample-report": {
        "title": "Sample Drone Flight Report - What You Get",
        "desc": "See what a Drone Flight Report contains: satellite track map, "
                "distance and altitude statistics, flight-health check, wind "
                "reference and a downloadable PDF.",
        "h1": "Sample Drone Flight Report",
        "body": """
<p>Every report follows the same structure, whether the source is a DJI CSV,
an ArduPilot .bin or a PX4 .ulg. The example below is generated from a
synthetic demo flight.</p>
<img src="/static/sample-report.jpg"
     alt="Sample drone flight report with satellite track map, statistics and health score"
     style="width:100%;border-radius:12px;border:1px solid rgba(148,163,184,.2);">
<p class="note">Synthetic demo data. Your own report will use the coordinates,
altitude and timing from your log.</p>
<h2>What each section shows</h2>
<ul>
<li><strong>Satellite track map:</strong> the flight path on real imagery, with
start and end markers and switchable basemaps.</li>
<li><strong>Summary statistics:</strong> GPS points, distance, maximum and mean
altitude.</li>
<li><strong>Flight health:</strong> a 0-100 score with plain-language flags for
GPS, timing, altitude and speed anomalies.</li>
<li><strong>Wind reference:</strong> regional historical wind, plus the
flight-weighted value when altitude data is available.</li>
<li><strong>PDF report:</strong> a downloadable summary you can keep or send to
a client.</li>
</ul>
<p><a href="/demo" style="color:#60a5fa;">Open the live demo report &rarr;</a></p>
<p>Ready to try your own log? The analyzer accepts DJI CSV/TXT, ArduPilot .bin
and PX4 .ulg files.</p>
""",
        "faqs": [
            ("Is the sample report generated from a real flight?",
             "The sample uses synthetic demo data; the layout and analysis are the same as a real report."),
            ("Can I download the sample PDF?",
             "Open the live demo and use the Download PDF button to generate a demo PDF."),
        ],
    },

    "/used-drone-battery-check": {
        "title": "Used Drone Check - Read the Flight Log Before You Buy",
        "desc": "Buying a second-hand drone? Upload its flight log and check "
                "flight history, GPS health, altitude and speed anomalies, and "
                "the wind it flew in before you hand over the money.",
        "h1": "Used drone check: read the flight log before you buy",
        "body": """
<p>A used drone looks identical whether it has flown ten times or four
hundred. The seller's word and a clean shell tell you very little. The flight
log does: it is the aircraft's own record of where it went, how hard it was
pushed and whether anything went wrong. Ask the seller to export the log from
the DJI app (or hand over the .bin / .ulg file from the flight controller) and
run it through the analyzer before you pay.</p>
<h2>What a log can tell you</h2>
<ul>
<li><strong>How much it actually flew.</strong> Total distance, duration and
the number of GPS points give a rough usage picture that is hard to fake
consistently across several files.</li>
<li><strong>Whether the GPS is healthy.</strong> A satellite count that drops
below six, or long gaps in the track, points to a receiver or antenna problem
that will bite you later.</li>
<li><strong>Whether it was flown hard.</strong> Abrupt altitude or speed
changes, and unusually high climb rates, show up in the flight-health check
as flags rather than as a vague impression.</li>
<li><strong>What conditions it survived.</strong> The regional wind reference
adds context: a flight in strong wind stresses motors and airframe far more
than a calm hover.</li>
<li><strong>Whether the story matches.</strong> If the seller says "barely
flown, indoor only" and the log shows 4 km at 300 m altitude, you have your
answer.</li>
</ul>
<h2>What a log cannot tell you</h2>
<p class="note">Battery cycle count, cell balance and internal resistance are
not in these logs. This tool does not certify airworthiness, and it cannot see
crash damage. Use the report to ask better questions, and still inspect the
airframe, props and batteries in person.</p>
<h2>How to check a drone in five minutes</h2>
<p>Ask for two or three recent logs, not just one. Upload each file, compare
the dates and distances, and look for the same warning appearing twice. Two
flights with GPS dropouts are a pattern; one is an accident. Then check that
the serial number on the box matches the account the logs came from, and that
the aircraft is not still bound to the seller's DJI account.</p>
""",
        "faqs": [
            ("Can I check battery health from a flight log?",
             "Not from the formats this tool parses. Battery cycle count and cell "
             "data live in the DJI app's battery page or in .DAT logs, which are "
             "not supported here."),
            ("How many logs should I ask the seller for?",
             "Two or three recent flights. Comparing several files makes it much "
             "harder to hide a recurring GPS or altitude problem."),
            ("Does this replace a physical inspection?",
             "No. It is a cheap first filter that costs nothing and takes minutes, "
             "but you should still inspect the airframe, props, motors and "
             "batteries in person."),
        ],
    },

}


def _seo_view(path):
    p = SEO_PAGES[path]
    return render_seo_page(p, path)


for _seo_path in SEO_PAGES:
    _seo_endpoint = "seo_" + _seo_path.strip("/").replace("-", "_")
    app.add_url_rule(
        _seo_path,
        endpoint=_seo_endpoint,
        view_func=(lambda p=_seo_path: _seo_view(p)),
    )


SOLUTION_PAGES = {
    "/solutions/flight-test-teams": {
        "title": "Flight-Test Log Reports for UAV Engineering Teams",
        "desc": "Turn supported PX4, ArduPilot and CSV flight logs into consistent engineering review reports while keeping evidence sources and missing data explicit.",
        "h1": "Flight-test reports without rebuilding the spreadsheet each time",
        "body": """
<p>Flight-test teams often repeat the same work after every sortie: identify the
right log, normalize timestamps and units, rebuild plots, mark anomalies and
prepare a report another engineer can review. Drone Flight Report turns a
supported log into one consistent first-pass report.</p>
<h2>Available now</h2>
<ul>
<li>Single-log processing for PX4 ULog, ArduPilot DataFlash and delimited telemetry.</li>
<li>Trajectory, statistics, telemetry charts, event context and data-quality warnings.</li>
<li>Organization, project, aircraft, pilot and reference labels in the report and PDF.</li>
<li>Source-labelled wind context that separates aircraft estimates from regional models.</li>
</ul>
<h2>Where an engineer remains responsible</h2>
<p>This report is a review aid, not an airworthiness decision or automated root-cause
verdict. Unsupported fields remain unavailable, and a missing check is not presented
as a passed check. Engineers should verify findings against the source log and the
aircraft's own tooling before making a safety decision.</p>
<h2>Team pilot</h2>
<p>The next workflow stage covers repeat projects, review states, approved templates
and cross-flight comparison. Those capabilities are being validated with design
partners and are not represented as live account features.</p>
<p><a href="/for-teams" style="color:#60a5fa;">Describe your flight-test workflow &rarr;</a></p>
""",
        "faqs": [
            ("Does this replace PX4 Flight Review or Mission Planner?",
             "No. It provides a consistent cross-format first-pass report. Firmware-level diagnosis and safety decisions still require the source log and specialist tools."),
            ("Can several engineers approve a report today?",
             "Not yet. Review and approval states belong to the team-workflow pilot and are clearly separated from the available single-report flow."),
        ],
    },
    "/solutions/drone-service-reporting": {
        "title": "Drone Client Report Automation for Service Providers",
        "desc": "Create repeatable flight evidence PDFs for inspection, mapping and drone-service clients without manually rebuilding each report.",
        "h1": "A repeatable flight appendix for every client job",
        "body": """
<p>Inspection and mapping clients rarely want a raw flight-controller file. They
need a readable record of when and where the aircraft flew, what the log supports
and what should be reviewed. The current workflow creates that appendix from one
authorized log at a time.</p>
<h2>Current delivery workflow</h2>
<ol>
<li>Export a supported log after the flight.</li>
<li>Add the client, project, aircraft, pilot and internal reference.</li>
<li>Review the generated map, figures, warnings and source notes.</li>
<li>Download the PDF and attach it to the service deliverable.</li>
</ol>
<h2>What the report does not claim</h2>
<p>The report does not certify regulatory compliance, prove that an inspection found
every defect, or turn a regional weather model into measured wind. It documents the
flight evidence available in the uploaded file and labels important limits.</p>
<h2>What we want to validate next</h2>
<ul>
<li>Reusable client templates and branded cover information.</li>
<li>Batch processing for recurring sites and multi-flight jobs.</li>
<li>Draft, reviewed, approved and delivered report states.</li>
<li>Monthly delivery summaries for recurring contracts.</li>
</ul>
<p><a href="/for-teams" style="color:#60a5fa;">Request a reporting pilot &rarr;</a></p>
""",
        "faqs": [
            ("Can I add a client or project name to the PDF?",
             "Yes. The upload form includes optional professional report labels for organization, project, aircraft, pilot and client reference."),
            ("Is branded batch reporting live?",
             "No. It is a design-partner pilot scope, not a currently available self-service feature."),
        ],
    },
    "/solutions/research-flight-data": {
        "title": "Reproducible Drone Flight-Log Reports for Research Teams",
        "desc": "Normalize supported UAV logs into source-aware reports for research review without hiding missing fields or mixing wind evidence types.",
        "h1": "Make flight-log preprocessing reviewable before modelling begins",
        "body": """
<p>Research groups often lose time to file formats, unit conversions and undocumented
spreadsheet steps before analysis begins. Drone Flight Report provides a repeatable
first-pass view of supported logs so a researcher can inspect data quality before
building a dataset or model.</p>
<h2>Useful for</h2>
<ul>
<li>Checking time, coordinate, altitude and speed normalization.</li>
<li>Reviewing trajectory coverage and gaps before feature extraction.</li>
<li>Separating onboard wind estimates, regional model context and unavailable data.</li>
<li>Creating a human-readable PDF alongside an experiment record.</li>
</ul>
<h2>Reproducibility boundary</h2>
<p>A generated report is not a substitute for retaining the authorized source log,
parser version, configuration and analysis code. The future visual wind-prediction
work remains a separate research track and is not implied by the current report.</p>
<h2>Potential pilot workflow</h2>
<p>For a repeated study, the team pilot can validate project grouping, batch intake,
parser-failure queues, review status and dataset export requirements before those
features become a full account product.</p>
<p><a href="/for-teams" style="color:#60a5fa;">Discuss a research workflow &rarr;</a></p>
""",
        "faqs": [
            ("Does the service train a wind-prediction model?",
             "No. Current reports analyze supported telemetry and source-labelled wind context. Visual wind prediction remains a separate future research direction."),
            ("Are missing fields filled automatically?",
             "No. Missing or unsupported evidence should remain missing rather than being fabricated for a complete-looking report."),
        ],
    },
    "/platform/team-log-workflow": {
        "title": "Team Drone Log Workflow - Product Scope and Pilot Status",
        "desc": "See the planned organization, batch upload, review, approval and flight-history workflow, with a clear distinction between available features and pilot scope.",
        "h1": "From one uploaded log to a controlled team workflow",
        "body": """
<p>The free analyzer solves one flight at a time. A team product must also answer who
uploaded it, which project and aircraft it belongs to, whether parsing succeeded,
who reviewed it and which report was delivered.</p>
<h2>Available single-report foundation</h2>
<ul>
<li>Supported-log upload, normalized analysis and PDF generation.</li>
<li>Optional organization, project, aircraft, pilot and client-reference labels.</li>
<li>Explicit data-quality and wind-source language.</li>
</ul>
<h2>Pilot workflow being validated</h2>
<ol>
<li><strong>Intake:</strong> authorized batch or folder upload with duplicate detection.</li>
<li><strong>Parse queue:</strong> successful flights separated from files needing review.</li>
<li><strong>Assignment:</strong> organization, project, aircraft and pilot attached to each flight.</li>
<li><strong>Review:</strong> draft, reviewed, approved and delivered states with an audit trail.</li>
<li><strong>History:</strong> filters and comparisons across a project's previous flights.</li>
<li><strong>Delivery:</strong> approved PDF, summary export or scheduled client package.</li>
</ol>
<p class="note"><strong>Status:</strong> account login, persistent flight history, batch
upload and approvals are not live self-service features today. This page documents the
pilot contract so prospective teams can say which part is worth building first.</p>
<h2>Later, only after repeat demand</h2>
<p>API ingestion, webhooks, ground-station sync and private deployment belong after
the manual and pilot workflow proves that teams repeatedly pay for the same outcome.</p>
<p><a href="/for-teams" style="color:#60a5fa;">Join the design-partner pilot &rarr;</a></p>
""",
        "faqs": [
            ("Can my team create accounts now?",
             "No. Accounts, persistent history, batch upload and approvals remain pilot scope."),
            ("Why publish the workflow before building every feature?",
             "It lets real teams validate which steps repeat and which controls they need before the product commits to an expensive architecture."),
        ],
    },
    "/evidence-and-limits": {
        "title": "Evidence, Data Sources and Limits | Drone Flight Report",
        "desc": "Understand what Drone Flight Report reads, what it infers, what it cannot verify and how future validation evidence will be published.",
        "h1": "What the report knows, estimates and cannot check",
        "body": """
<p>A useful flight report must distinguish evidence from presentation. This page sets
the standard for every current report and future team feature.</p>
<h2>Directly read from a supported log</h2>
<p>Depending on format, the parser can read time, position, altitude, velocity,
attitude, battery, flight-mode or estimator fields. A field is shown only when the
source and unit can be identified with sufficient confidence.</p>
<h2>Derived from log values</h2>
<p>Distance, duration, summary statistics, trajectory sampling and health flags are
computed from normalized values. They remain dependent on the source log's sampling,
sensor quality and gaps.</p>
<h2>External or estimated context</h2>
<p>Regional weather-model wind is context, not a measurement at the aircraft. An
onboard estimator is also not the same as an anemometer. The report must name the
source and keep measured, estimated, modelled and unavailable values separate.</p>
<h2>Not verified by the current product</h2>
<ul>
<li>Airworthiness, legal compliance or safe-to-fly decisions.</li>
<li>A complete accident root cause.</li>
<li>Local gusts that were not measured by an independent sensor.</li>
<li>Future camera-only wind predictions.</li>
</ul>
<h2>Evidence roadmap</h2>
<p>Validation should publish the parser version, test format, expected result, failure
cases and independent references. No flight-count or accuracy claim will be published
until the underlying test set and method can be explained.</p>
<p><a href="/methodology" style="color:#60a5fa;">Read the current methodology &rarr;</a></p>
""",
        "faqs": [
            ("Does a health flag prove a fault?",
             "No. It identifies evidence worth reviewing. A specialist should confirm it using the source log, aircraft documentation and appropriate diagnostic tools."),
            ("Is regional wind measured at the drone?",
             "No. It is coarse external model context and must not be used as measured local wind or for safety-critical decisions."),
        ],
    },
}


def _solution_view(path):
    return render_seo_page(SOLUTION_PAGES[path], path)


for _solution_path in SOLUTION_PAGES:
    _solution_endpoint = (
        "solution_"
        + _solution_path.strip("/").replace("/", "_").replace("-", "_")
    )
    app.add_url_rule(
        _solution_path,
        endpoint=_solution_endpoint,
        view_func=(lambda p=_solution_path: _solution_view(p)),
    )


def clean_form_text(value, max_length):
    """Return a compact, control-character-free form value."""
    text = str(value or "")
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", " ", text)
    return " ".join(text.split())[:max_length]


def extract_report_context(form):
    """Read optional professional-report labels without storing them."""
    fields = {
        "organization": 100,
        "project": 120,
        "aircraft": 100,
        "pilot": 100,
        "client_reference": 120,
    }
    return {
        name: clean_form_text(form.get(name), limit)
        for name, limit in fields.items()
        if clean_form_text(form.get(name), limit)
    }


def cleanup_pilot_requests(now=None):
    """Remove expired design-partner enquiries from local storage."""
    if not os.path.exists(PILOT_REQUESTS_FILE):
        return

    cutoff = (now or datetime.utcnow()) - timedelta(
        days=PILOT_LEAD_RETENTION_DAYS
    )
    kept = []
    try:
        with open(PILOT_REQUESTS_FILE, encoding="utf-8") as handle:
            for line in handle:
                try:
                    record = json.loads(line)
                    created = datetime.fromisoformat(
                        str(record.get("ts", "")).rstrip("Z")
                    )
                    if created >= cutoff:
                        kept.append(record)
                except (ValueError, TypeError, json.JSONDecodeError):
                    continue
    except OSError:
        return

    temp_name = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            delete=False,
            dir=DATA_DIR,
            prefix="pilot_requests_",
            suffix=".tmp",
        ) as handle:
            temp_name = handle.name
            for record in kept:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        os.replace(temp_name, PILOT_REQUESTS_FILE)
    except OSError:
        if temp_name and os.path.exists(temp_name):
            try:
                os.remove(temp_name)
            except OSError:
                pass


TEAM_PILOT_PAGE = {
    "title": "Drone Flight Report for Teams - Flight-Test Report Automation",
    "desc": "A design-partner pilot for PX4, ArduPilot and mixed-fleet teams that need repeatable flight-log QA, review-ready reports and a clear path to team workflow automation.",
    "h1": "Flight-log QA and report automation for teams",
    "body": r"""
<p>Drone Flight Report is expanding from a single-flight analyzer into a
repeatable workflow for UAV test teams, service providers and research groups.
The goal is simple: turn each supported log into a review-ready engineering or
client report without hiding missing data or mixing measured, estimated and
modelled wind.</p>

<p class="note"><strong>Honest status:</strong> single-log analysis and optional
professional report labels are available now. Team accounts, batch history,
approval states and automated ingestion are the next pilot stage; they are not
presented as live features yet. This SaaS track is separate from the product P
line, wind-data D line and any future visual wind-prediction research.</p>

<h2>The workflow we are building</h2>
<ol>
<li>Upload a supported DJI/CSV, ArduPilot DataFlash or PX4 ULog file.</li>
<li>Normalize time, position, altitude and telemetry into a versioned schema.</li>
<li>Check data quality and show missing or unsupported evidence explicitly.</li>
<li>Review the event timeline, track, charts and source-labelled wind context.</li>
<li>Add organization, project, aircraft, pilot and client-reference labels.</li>
<li>Generate a review-ready PDF now; move to team review and scheduled delivery during the pilot.</li>
</ol>

<h2>S1 - Design-partner reporting, available now</h2>
<ul>
<li>Single-log compatibility and data-quality review.</li>
<li>Professional context fields carried into the browser report and PDF.</li>
<li>Trajectory, statistics, health flags and source-aware wind context.</li>
<li>Private design-partner intake for recurring reports and custom templates.</li>
</ul>

<h2>S2 - Team report workflow, pilot scope</h2>
<ul>
<li>Organizations, projects, aircraft and flight records.</li>
<li>Batch ingestion, duplicate detection and parser-failure review queues.</li>
<li>Draft, reviewed, approved and delivered report states.</li>
<li>Reusable branded templates, cross-flight comparison and scheduled summaries.</li>
<li>API, webhooks and private/self-hosted deployment only after customer validation.</li>
</ul>

<h2>90-day validation plan</h2>
<ul>
<li><strong>Days 1-30:</strong> work with three design partners, process authorized logs and measure what repeats.</li>
<li><strong>Days 31-60:</strong> validate organization/project structure, batch upload, templates and review states.</li>
<li><strong>Days 61-90:</strong> test recurring delivery, plan limits and the smallest useful integration.</li>
</ul>

<h2>Request a design-partner pilot</h2>
<p>Use this form if your team repeatedly reviews flight logs or prepares
engineering/client reports. Do not attach flight logs, secrets or sensitive
site coordinates here.</p>

<form method="post" action="/for-teams"
      style="display:grid;gap:13px;margin:20px 0;">
  <label>Name *
    <input type="text" name="name" required maxlength="100"
           style="width:100%;padding:10px;border-radius:8px;border:1px solid #334155;background:#0f172a;color:#e2e8f0;">
  </label>
  <label>Work email *
    <input type="email" name="email" required maxlength="200"
           style="width:100%;padding:10px;border-radius:8px;border:1px solid #334155;background:#0f172a;color:#e2e8f0;">
  </label>
  <label>Organization or team
    <input type="text" name="organization" maxlength="150"
           style="width:100%;padding:10px;border-radius:8px;border:1px solid #334155;background:#0f172a;color:#e2e8f0;">
  </label>
  <label>Your role
    <input type="text" name="role" maxlength="100" placeholder="Flight-test engineer, operations lead, researcher..."
           style="width:100%;padding:10px;border-radius:8px;border:1px solid #334155;background:#0f172a;color:#e2e8f0;">
  </label>
  <label>Primary workflow *
    <select name="workflow" required
            style="width:100%;padding:10px;border-radius:8px;border:1px solid #334155;background:#0f172a;color:#e2e8f0;">
      <option value="">Choose one</option>
      <option value="flight_test">Flight-test engineering</option>
      <option value="client_reports">Client or inspection reports</option>
      <option value="research">Research and reproducibility</option>
      <option value="training">Training or education</option>
      <option value="other">Other recurring log workflow</option>
    </select>
  </label>
  <label>Log formats
    <input type="text" name="formats" maxlength="160" placeholder="PX4 .ulg, ArduPilot .bin, DJI/CSV..."
           style="width:100%;padding:10px;border-radius:8px;border:1px solid #334155;background:#0f172a;color:#e2e8f0;">
  </label>
  <label>Approximate flights per month
    <select name="monthly_flights"
            style="width:100%;padding:10px;border-radius:8px;border:1px solid #334155;background:#0f172a;color:#e2e8f0;">
      <option value="unknown">Not sure yet</option>
      <option value="1-10">1-10</option>
      <option value="11-50">11-50</option>
      <option value="51-200">51-200</option>
      <option value="200+">More than 200</option>
    </select>
  </label>
  <label>What is still manual today? *
    <textarea name="message" required maxlength="3000" rows="6"
              placeholder="Describe how logs become reports, who reviews them and what has to be delivered."
              style="width:100%;padding:10px;border-radius:8px;border:1px solid #334155;background:#0f172a;color:#e2e8f0;"></textarea>
  </label>
  <label style="display:flex;gap:9px;align-items:flex-start;">
    <input type="checkbox" name="contact_consent" value="yes" required style="margin-top:6px;">
    <span>I agree that these contact and workflow details may be stored for up to 180 days to evaluate and respond to this pilot request.</span>
  </label>
  <input type="text" name="website" tabindex="-1" autocomplete="off"
         aria-hidden="true" style="position:absolute;left:-9999px;width:1px;height:1px;opacity:0;">
  <button type="submit"
          style="justify-self:start;padding:12px 22px;border:0;border-radius:10px;background:#2563eb;color:#fff;font-weight:600;cursor:pointer;">
    Request pilot review
  </button>
</form>
<p class="muted">Pilot enquiries are kept separately from flight data. Raw
logs cannot be attached to this form and IP addresses are not stored with the
request.</p>
""",
    "faqs": [
        ("Is the team SaaS live today?",
         "Single-log analysis and professional report labels are live. Team accounts, batch history and approvals are a clearly labelled pilot scope, not a claimed live feature."),
        ("Does this replace the P and D roadmaps?",
         "No. S1 and S2 describe the service and team-workflow track. Product features remain on the P line, wind data and validation remain on the D line, and future visual prediction research stays separate."),
        ("Should sensitive logs be submitted with the pilot form?",
         "No. The form accepts contact and workflow details only. Logs should be shared later only through an agreed authorized process."),
    ],
}


@app.route("/for-teams", methods=["GET", "POST"])
def for_teams():
    if request.method == "GET":
        cleanup_pilot_requests()
        return render_seo_page(TEAM_PILOT_PAGE, "/for-teams")

    honeypot = clean_form_text(request.form.get("website"), 200)
    if honeypot:
        return render_seo_page(TEAM_PILOT_PAGE, "/for-teams")

    name = clean_form_text(request.form.get("name"), 100)
    email = clean_form_text(request.form.get("email"), 200)
    organization = clean_form_text(request.form.get("organization"), 150)
    role = clean_form_text(request.form.get("role"), 100)
    workflow = clean_form_text(request.form.get("workflow"), 40)
    formats = clean_form_text(request.form.get("formats"), 160)
    monthly_flights = clean_form_text(
        request.form.get("monthly_flights"), 20
    )
    message = clean_form_text(request.form.get("message"), 3000)
    consent = request.form.get("contact_consent") == "yes"

    allowed_workflows = {
        "flight_test",
        "client_reports",
        "research",
        "training",
        "other",
    }
    allowed_volumes = {"unknown", "1-10", "11-50", "51-200", "200+"}
    error = None
    if len(name) < 2:
        error = "Please enter your name."
    elif not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        error = "Please enter a valid work email address."
    elif workflow not in allowed_workflows:
        error = "Please choose the workflow that best matches your team."
    elif monthly_flights not in allowed_volumes:
        error = "Please choose a valid monthly flight range."
    elif len(message) < 20:
        error = "Please describe the recurring workflow in a little more detail."
    elif not consent:
        error = "Consent is required so the team can respond to your request."

    if error is None:
        record = {
            "ts": datetime.utcnow().isoformat() + "Z",
            "name": name,
            "email": email,
            "organization": organization,
            "role": role,
            "workflow": workflow,
            "formats": formats,
            "monthly_flights": monthly_flights,
            "message": message,
        }
        try:
            cleanup_pilot_requests()
            with open(
                PILOT_REQUESTS_FILE,
                "a",
                encoding="utf-8",
            ) as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError:
            error = "The pilot request could not be saved. Please try again later."

    if error is None:
        page = dict(TEAM_PILOT_PAGE)
        page["title"] = "Pilot request received - Drone Flight Report"
        page["h1"] = "Pilot request received"
        page["body"] = """
<p>Thank you. The workflow details were received without a flight-log
attachment. They will be reviewed as a potential design-partner pilot.</p>
<p><a href="/" style="color:#60a5fa;">Analyze a log now</a> or return to
<a href="/for-teams" style="color:#60a5fa;">the team workflow overview</a>.</p>
"""
        return render_seo_page(page, "/for-teams")

    page = dict(TEAM_PILOT_PAGE)
    page["body"] = (
        '<p style="color:#fca5a5;"><strong>%s</strong></p>' % error
        + TEAM_PILOT_PAGE["body"]
    )
    return render_seo_page(page, "/for-teams"), 400


CONTACT_PAGE = {
    "title": "Contact Drone Flight Report",
    "desc": "Contact the Drone Flight Report team for bug reports, feature "
            "requests, privacy questions or feedback about the flight log analyzer.",
    "h1": "Contact Drone Flight Report",
    "body": """
<p>Bug reports, feature requests and feedback are welcome. For public issues,
the fastest route is GitHub:</p>
<p><a href="https://github.com/LIU0612nn/DroneFlightLog/issues"
      style="color:#60a5fa;">Open an issue on GitHub &rarr;</a></p>
<h2>Send a private message</h2>
<p>If your message contains personal data or you prefer not to post publicly,
use the form below. We usually reply within a few business days.</p>
<form method="post" action="/contact"
      style="display:grid;gap:12px;margin:18px 0;">
    <label>Name
        <input type="text" name="name" maxlength="100"
               style="width:100%;padding:10px;border-radius:8px;border:1px solid #334155;background:#0f172a;color:#e2e8f0;">
    </label>
    <label>Email
        <input type="email" name="email" maxlength="200"
               style="width:100%;padding:10px;border-radius:8px;border:1px solid #334155;background:#0f172a;color:#e2e8f0;">
    </label>
    <label>Message
        <textarea name="message" required maxlength="5000" rows="6"
                  style="width:100%;padding:10px;border-radius:8px;border:1px solid #334155;background:#0f172a;color:#e2e8f0;"></textarea>
    </label>
    <input type="text" name="website" tabindex="-1" autocomplete="off"
           aria-hidden="true"
           style="position:absolute;left:-9999px;width:1px;height:1px;opacity:0;">
    <button type="submit"
            style="justify-self:start;padding:12px 22px;border:0;border-radius:10px;background:#2563eb;color:#fff;font-weight:600;cursor:pointer;">
        Send message
    </button>
</form>
<p class="note">Do not include passwords, API keys or other secrets in the form.
Uploaded flight logs are never attached to contact messages.</p>
""",
    "faqs": [
        ("How do I report a bug?",
         "Open an issue on GitHub with the log format and the error message, or use the contact form."),
        ("Can I request deletion of shared data?",
         "Yes. Your report shows a random data ID; paste it at /delete-data and the copy is deleted immediately."),
    ],
}


@app.route("/contact", methods=["GET", "POST"])
def contact():
    if request.method == "GET":
        return render_seo_page(CONTACT_PAGE, "/contact")

    name = (request.form.get("name") or "").strip()[:100]
    email = (request.form.get("email") or "").strip()[:200]
    message = (request.form.get("message") or "").strip()[:5000]
    honeypot = (request.form.get("website") or "").strip()

    # Silent success for bots that fill the hidden field.
    if honeypot:
        message = ""

    error = None
    if len(message) < 5:
        error = "Please enter a message."
    elif email and "@" not in email:
        error = "Please enter a valid email address."

    if error is None:
        record = {
            "ts": datetime.utcnow().isoformat() + "Z",
            "name": name,
            "email": email,
            "message": message,
        }
        try:
            with open(
                os.path.join(DATA_DIR, "contact_messages.jsonl"),
                "a",
                encoding="utf-8",
            ) as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception:
            error = "The message could not be saved. Please try again later."

    if error is None:
        page = dict(CONTACT_PAGE)
        page["title"] = "Message sent - Drone Flight Report"
        page["h1"] = "Message sent"
        page["body"] = """
<p>Thanks - your message has been received. We usually reply within a few
business days.</p>
<p><a href="/" style="color:#60a5fa;">&larr; Back to the analyzer</a></p>
"""
        return render_seo_page(page, "/contact")

    page = dict(CONTACT_PAGE)
    page["body"] = (
        '<p style="color:#fca5a5;"><strong>%s</strong></p>' % error
        + CONTACT_PAGE["body"]
    )
    return render_seo_page(page, "/contact"), 400


@app.route(
    "/privacy"
)
def privacy():

    return render_template_string(
        PRIVACY_HTML
    )


DELETE_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="robots" content="noindex, nofollow">
<title>Delete shared data &mdash; Drone Flight Report</title>
<style>
body{margin:0;background:#020617;color:#f8fafc;
 font-family:Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;}
.wrap{width:min(640px,92%);margin:0 auto;padding:64px 0;line-height:1.75;}
h1{margin:0 0 10px;font-size:26px;}
p{color:#cbd5e1;}
input[type=text]{width:100%;padding:13px 14px;border-radius:10px;
 border:1px solid rgba(148,163,184,.3);background:#0f172a;color:#e2e8f0;
 font-size:15px;font-family:ui-monospace,Menlo,monospace;}
button{margin-top:16px;padding:13px 24px;border:0;border-radius:10px;
 background:#2563eb;color:#fff;font-weight:600;font-size:15px;cursor:pointer;}
.msg{padding:14px 16px;border-radius:10px;margin:18px 0;}
.ok{background:rgba(34,197,94,.12);border:1px solid rgba(34,197,94,.3);}
.err{background:rgba(239,68,68,.12);border:1px solid rgba(239,68,68,.3);}
.small{color:#94a3b8;font-size:13px;}
a{color:#60a5fa;text-decoration:none;}
</style>
</head>
<body>
<div class="wrap">

<h1>Delete your shared data</h1>

<p>Paste the data ID shown on your report. It looks like
<code>aB3dEf6hIjK</code> (12 characters). Deleting is immediate and permanent.</p>

{% if message %}
<div class="msg {{ 'ok' if ok else 'err' }}">{{ message }}</div>
{% endif %}

<form method="post" action="/delete-data">
    <input type="text" name="token" id="token" required
           placeholder="your data ID" autocomplete="off" spellcheck="false">
    <button type="submit">Delete</button>
</form>

<p class="small" style="margin-top:26px;">
Only de-identified copies are ever stored, and only if you ticked the sharing
box. If the 30-day retention window has already passed, there is nothing left
to delete &mdash; you will see "not found", which is the expected answer.
</p>

<p class="small"><a href="/">&larr; Back to upload</a></p>

</div>
</body>
</html>
"""


@app.route("/delete-data", methods=["GET", "POST"])
def delete_data():
    """Let a user delete the de-identified copy without an account."""
    message = None
    ok = None

    if request.method == "POST":
        token = (request.form.get("token") or "").strip()
        if delete_shared_data(token):
            ok = True
            message = (
                "Deleted. The shared de-identified copy for this ID no longer exists."
            )
        else:
            ok = False
            message = (
                "Not found. The ID may be mistyped, already deleted, or past "
                "its 30-day retention window."
            )

    return render_template_string(DELETE_HTML, message=message, ok=ok)


@app.route("/<name>.txt")
def indexnow_key_file(name):
    """Serve the IndexNow key file at /<key>.txt.

    Search engines fetch this URL to verify that whoever submits URLs for
    this host actually controls it. The key is public by definition, so it
    is safe to ship as a default and override via INDEXNOW_KEY.
    """
    if INDEXNOW_KEY and name == INDEXNOW_KEY:
        return Response(INDEXNOW_KEY, mimetype="text/plain")
    return Response("Not found", status=404, mimetype="text/plain")


@app.route("/robots.txt")
def robots_txt():
    body = (
        "User-agent: *\n"
        "Allow: /\n"
        "Disallow: /generated/\n"
        "Sitemap: https://drone-flight-report.com/sitemap.xml\n"
    )
    return Response(body, mimetype="text/plain")


@app.route("/sitemap.xml")
def sitemap_xml():
    core_pages = {"/dji-flight-log", "/ardupilot-bin", "/px4-ulg"}
    low_priority = {"/about", "/methodology", "/sample-report"}
    urls = [("/", "1.0", "weekly")]
    for path in SEO_PAGES:
        if path in core_pages:
            priority = "0.8"
        elif path in low_priority:
            priority = "0.4"
        else:
            priority = "0.7"
        urls.append((path, priority, "monthly"))
    for path in SOLUTION_PAGES:
        urls.append((path, "0.7", "monthly"))
    urls.append(("/for-teams", "0.8", "weekly"))
    urls.append(("/contact", "0.4", "yearly"))
    urls.append(("/privacy", "0.3", "yearly"))
    parts = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for loc, prio, freq in urls:
        parts.append(
            "  <url><loc>https://drone-flight-report.com%s</loc>"
            "<changefreq>%s</changefreq><priority>%s</priority></url>"
            % (loc, freq, prio)
        )
    parts.append("</urlset>")
    return Response("\n".join(parts) + "\n", mimetype="application/xml")


@app.route(
    "/health"
)
def health():

    return {

        "status":
            "ok",

        "service":
            "Drone Flight Report",

        "time":
            datetime.utcnow()
            .isoformat()

    }


# =========================================================
# Local development
# =========================================================

if __name__ == "__main__":

    # Production-safe defaults. Set DEBUG=1 for local development only.
    app.run(

        host=os.environ.get("HOST", "0.0.0.0"),

        port=int(
            os.environ.get(
                "PORT",
                5000
            )
        ),

        debug=os.environ.get("DEBUG", "0") == "1"

    )
