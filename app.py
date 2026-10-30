import os
import re
import math
import json
import uuid
import tempfile
from datetime import datetime

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
)
from werkzeug.utils import secure_filename

from reportlab.lib.pagesizes import A4
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
SITE_URL = "https://drone-flight-report.com"

os.makedirs(GENERATED_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)

# Optional 天地图 key. When set, the report offers the official Chinese
# satellite basemap (CGCS2000, aligned with BeiDou/WGS-84) in addition to
# the keyless Esri and 高德 layers.
TIANDITU_KEY = os.environ.get("TIANDITU_KEY", "").strip()


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
    .faq-grid {
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

            </div>

        </form>


        <div id="status" class="status"></div>

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
                <a href="/privacy">Privacy</a>
                <a href="/contact">Contact</a>
            </div>

        </div>

        <p class="footer-base">
            Drone Flight Report &middot; Free &middot; no sign-up &middot;
            privacy-first. Your raw log is deleted after processing.
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
def parse_bin_log(path):
    """Parse an ArduPilot DataFlash BIN GPS stream with DFReader."""
    log = DFReader.DFReader_binary(path)
    rows = []

    while True:
        msg = log.recv_match(
            type=["GPS", "GPS2"],
            blocking=False
        )

        if msg is None:
            break

        try:
            lat = float(msg.Lat)
            lon = float(msg.Lng)

            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                continue

            # -------------------------------------------------
            # Altitude
            # Prefer RAlt because it represents relative flight
            # altitude. Fall back to GPS Alt if RAlt is unavailable.
            # -------------------------------------------------
            if hasattr(msg, "RAlt"):
                altitude_m = float(msg.RAlt)
            elif hasattr(msg, "Alt"):
                altitude_m = float(msg.Alt)
            else:
                altitude_m = np.nan

            row = {
                "latitude": lat,
                "longitude": lon,
                "altitude_m": altitude_m,
            }

            # -------------------------------------------------
            # GPS timestamp
            # GMS = milliseconds since start of GPS week
            # GWk = GPS week number
            # -------------------------------------------------
            if hasattr(msg, "GMS") and hasattr(msg, "GWk"):
                gps_epoch = pd.Timestamp(
                    "1980-01-06",
                    tz="UTC"
                )

                row["timestamp_utc"] = (
                    gps_epoch
                    + pd.to_timedelta(
                        int(msg.GWk),
                        unit="W"
                    )
                    + pd.to_timedelta(
                        float(msg.GMS),
                        unit="ms"
                    )
                    - pd.Timedelta(seconds=18)
                )

            # -------------------------------------------------
            # System elapsed time
            # TimeUS = microseconds since system startup
            # -------------------------------------------------
            if hasattr(msg, "TimeUS"):
                row["elapsed_seconds"] = (
                    float(msg.TimeUS) / 1_000_000.0
                )

            # -------------------------------------------------
            # Ground speed
            # ArduPilot GPS.Spd is already m/s.
            # -------------------------------------------------
            if hasattr(msg, "Spd"):
                row["speed_mps"] = float(msg.Spd)

            # -------------------------------------------------
            # Ground course / heading
            # -------------------------------------------------
            if hasattr(msg, "GCrs"):
                row["heading_deg"] = float(msg.GCrs)

            # -------------------------------------------------
            # GPS satellites
            # -------------------------------------------------
            if hasattr(msg, "NSats"):
                row["gps_satellites"] = float(msg.NSats)

            # -------------------------------------------------
            # GPS quality / HDOP
            # -------------------------------------------------
            if hasattr(msg, "HDop"):
                row["gps_quality"] = float(msg.HDop)

            rows.append(row)

        except Exception:
            continue

    if not rows:
        raise ValueError(
            "BIN file was read, but no valid GPS records "
            "were found in GPS/GPS2 messages."
        )

    return pd.DataFrame(rows)


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
    elapsed = pd.to_numeric(df["elapsed_seconds"], errors="coerce")
    speed = pd.to_numeric(df["speed_mps"], errors="coerce")
    distance_m = calculate_distance(df)

    duration = float(elapsed.max() - elapsed.min()) if elapsed.notna().any() else None
    return {
        "points": int(len(df)),
        "distance_m": distance_m,
        "distance_km": distance_m / 1000.0,
        "duration_s": duration,
        "max_altitude": float(altitude.max()) if altitude.notna().any() else None,
        "min_altitude": float(altitude.min()) if altitude.notna().any() else None,
        "mean_altitude": float(altitude.mean()) if altitude.notna().any() else None,
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
    image_path
):

    filename = (
        f"flight_report_{uuid.uuid4().hex}.pdf"
    )


    pdf_path = os.path.join(
        GENERATED_DIR,
        filename
    )


    c = canvas.Canvas(
        pdf_path,
        pagesize=A4
    )


    width, height = A4


    # -----------------------------------------------------
    # Page 1
    # -----------------------------------------------------

    c.setFont(
        "Helvetica-Bold",
        22
    )


    c.drawString(
        50,
        height - 60,
        "Drone Flight Report"
    )


    c.setFont(
        "Helvetica",
        11
    )


    y = height - 100


    lines = [

        f"GPS points: {stats['points']}",

        (
            f"Distance: "
            f"{stats['distance_km']:.3f} km"
        ),

        (
            f"Maximum altitude: "
            f"{stats['max_altitude']:.2f} m"
            if stats["max_altitude"] is not None
            else
            "Maximum altitude: N/A"
        ),

        (
            f"Minimum altitude: "
            f"{stats['min_altitude']:.2f} m"
            if stats["min_altitude"] is not None
            else
            "Minimum altitude: N/A"
        ),

        (
            f"Mean altitude: "
            f"{stats['mean_altitude']:.2f} m"
            if stats["mean_altitude"] is not None
            else
            "Mean altitude: N/A"
        ),

    ]


    for line in lines:

        c.drawString(
            50,
            y,
            line
        )

        y -= 22


    y -= 10


    c.setFont(
        "Helvetica-Bold",
        13
    )


    c.drawString(
        50,
        y,
        "Wind Reference"
    )


    y -= 25


    c.setFont(
        "Helvetica",
        11
    )


    if wind.get("speed") is not None:

        c.drawString(
            50,
            y,

            (
                f"Wind speed: "
                f"{wind['speed'] *3.6:.1f} km/h"
            )
        )

        y -= 20


        if wind.get("direction") is not None:

            c.drawString(
                50,
                y,

                (
                    f"Wind direction: "
                    f"{wind['direction']:.0f}°"
                )
            )

            y -= 20


        c.drawString(
            50,
            y,

            (
                f"Source: "
                f"{wind.get('source', 'Unknown')}"
            )
        )

    else:

        c.drawString(
            50,
            y,
            "Wind data unavailable."
        )


    y -= 45


    c.setFont(
        "Helvetica",
        9
    )


    c.drawString(
        50,
        y,

        (
            "Wind information is provided as a "
            "regional reference and is not a "
            "high-resolution local CFD simulation."
        )
    )


    c.showPage()


    # -----------------------------------------------------
    # Page 2 - trajectory
    # -----------------------------------------------------

    c.setFont(
        "Helvetica-Bold",
        16
    )


    c.drawString(
        50,
        height - 50,
        "Flight Trajectory"
    )


    image = ImageReader(
        image_path
    )


    image_width = width - 80

    image_height = (
        image_width
        * 0.65
    )


    c.drawImage(
        image,
        40,
        height - 80 - image_height,
        width=image_width,
        height=image_height,
        preserveAspectRatio=True,
        mask="auto"
    )


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


def save_deidentified_log(df):
    """Save a de-identified trajectory, not raw GPS coordinates or UTC time."""
    if len(df) < 1:
        return None

    lat0 = math.radians(float(df.iloc[0]["latitude"]))
    lon0 = math.radians(float(df.iloc[0]["longitude"]))
    radius = 6371000.0

    lat = np.radians(df["latitude"].to_numpy(dtype=float))
    lon = np.radians(df["longitude"].to_numpy(dtype=float))
    x_m = (lon - lon0) * math.cos(lat0) * radius
    y_m = (lat - math.radians(float(df.iloc[0]["latitude"]))) * radius

    safe = pd.DataFrame({
        "elapsed_seconds": df["elapsed_seconds"],
        "x_m": x_m,
        "y_m": y_m,
        "altitude_m": df["altitude_m"],
        "speed_mps": df["speed_mps"],
        "heading_deg": df["heading_deg"],
    })

    filename = f"deidentified_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}.csv"
    path = os.path.join(LOG_DIR, filename)
    safe.to_csv(path, index=False)
    return path
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

    {{ flight_date or "Date unavailable" }}

</div>


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
            Max Altitude
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
            Mean Altitude
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


<div class="card">

    <h2>Satellite Track Map</h2>

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

    var wgsGroup = trackGroup(points).addTo(map);
    var gcjGroup = trackGroup(gcjPoints);

    map.on("baselayerchange", function (event) {
        if (event.name.indexOf("高德") !== -1) {
            map.removeLayer(wgsGroup);
            gcjGroup.addTo(map);
        } else {
            map.removeLayer(gcjGroup);
            wgsGroup.addTo(map);
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
(metres from the first point), elapsed time, altitude, speed and heading.
Raw GPS coordinates and absolute UTC timestamps are removed.</p>

<h2>What we do not keep</h2>
<p>We do not retain your original filename, name, email, phone number or postal
address. We do not store your IP address with your flight data.</p>

<h2>Your choices</h2>
<p>Sharing de-identified data is <strong>off by default</strong> and requires an
explicit opt-in checkbox. You can request deletion of any shared data at any time.</p>

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


        if save_consent:

            save_deidentified_log(
                df
            )


        # -------------------------------------------------
        # Flight date
        # -------------------------------------------------

        flight_date = get_flight_date(
            df
        )
        print("Flight date:", flight_date)

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
                image_path
            )
        )


        return render_template_string(

            REPORT_HTML,

            stats=stats,

            wind=wind,

            map_points=map_points,

            tianditu_key=TIANDITU_KEY,

            image_filename=
                image_filename,

            pdf_filename=
                pdf_filename,

            flight_date=
                flight_date,

            health=health,

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
                image_path
            )
        )


        return render_template_string(

            REPORT_HTML,

            stats=stats,

            wind=wind,

            map_points=build_map_points(df),

            tianditu_key=TIANDITU_KEY,

            image_filename=
                image_filename,

            pdf_filename=
                pdf_filename,

            flight_date=
                flight_date,

            health=health,

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
         "Yes. Mention the approximate date and flight details in the form so the record can be located."),
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
