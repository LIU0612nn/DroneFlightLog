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
<link rel="canonical" href="https://droneflight-report.com/">

<meta property="og:type" content="website">
<meta property="og:site_name" content="Drone Flight Report">
<meta property="og:title" content="Drone Flight Report — Free Drone Flight Log Analyzer">
<meta property="og:description" content="Upload DJI / ArduPilot / PX4 flight logs and get a trajectory map, statistics, wind reference, flight-health check and a PDF report. Free, no sign-up, privacy-first.">
<meta property="og:url" content="https://droneflight-report.com/">

<meta name="twitter:card" content="summary">
<meta name="twitter:title" content="Drone Flight Report — Free Drone Flight Log Analyzer">
<meta name="twitter:description" content="Upload DJI / ArduPilot / PX4 logs to get a flight track, stats, wind reference, health check and a PDF report.">

<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "WebApplication",
  "name": "Drone Flight Report",
  "url": "https://droneflight-report.com/",
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

footer {
    margin-top: 50px;
    text-align: center;
    color: #64748b;
    font-size: 14px;
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

        Drone Flight Report &middot;
        <a href="/privacy" style="color:#60a5fa;text-decoration:none;">Privacy</a>
        &middot; Guides:
        <a href="/dji-flight-log" style="color:#60a5fa;text-decoration:none;">DJI</a>
        <a href="/ardupilot-bin" style="color:#60a5fa;text-decoration:none;">ArduPilot</a>
        <a href="/px4-ulg" style="color:#60a5fa;text-decoration:none;">PX4</a>
        <a href="/vs-airdata" style="color:#60a5fa;text-decoration:none;">vs AirData</a>
        <a href="/vs-flight-reader" style="color:#60a5fa;text-decoration:none;">vs Flight Reader</a>
        <a href="/vs-px4-review" style="color:#60a5fa;text-decoration:none;">vs PX4 Review</a>

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
<link rel="canonical" href="https://droneflight-report.com%%PATH%%">
<style>
body { margin:0; font-family: Inter, system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif; background:#0b1220; color:#e2e8f0; line-height:1.75; }
.wrap { max-width:760px; margin:0 auto; padding:48px 22px; }
h1 { font-size:30px; line-height:1.25; margin:0 0 10px; }
h2 { font-size:20px; margin:30px 0 8px; }
p, li { color:#cbd5e1; }
code { background:#1e293b; padding:2px 6px; border-radius:6px; }
a.cta { display:inline-block; margin:26px 0; padding:14px 24px; background:#2563eb; color:#fff; text-decoration:none; border-radius:12px; font-weight:600; }
.muted { color:#94a3b8; font-size:14px; }
footer { margin-top:44px; color:#64748b; font-size:13px; }
</style>
</head>
<body>
<div class="wrap">
<p class="muted"><a href="/" style="color:#60a5fa;text-decoration:none;">&larr; Drone Flight Report</a></p>
<h1>%%H1%%</h1>
%%BODY%%
<a class="cta" href="/">Analyze a flight log free &rarr;</a>
<footer>Free &middot; no sign-up &middot; privacy-first &middot; <a href="/privacy" style="color:#60a5fa;text-decoration:none;">Privacy</a></footer>
</div>
</body>
</html>
"""


def render_seo_page(title, desc, path, h1, body):
    return (SEO_PAGE_TEMPLATE
            .replace("%%TITLE%%", title)
            .replace("%%DESC%%", desc)
            .replace("%%PATH%%", path)
            .replace("%%H1%%", h1)
            .replace("%%BODY%%", body))


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
    },

}


def _seo_view(path):
    p = SEO_PAGES[path]
    return render_seo_page(p["title"], p["desc"], path, p["h1"], p["body"])


@app.route("/dji-flight-log")
def seo_dji():
    return _seo_view("/dji-flight-log")


@app.route("/ardupilot-bin")
def seo_ardupilot():
    return _seo_view("/ardupilot-bin")


@app.route("/px4-ulg")
def seo_px4():
    return _seo_view("/px4-ulg")


@app.route("/vs-airdata")
def seo_vs_airdata():
    return _seo_view("/vs-airdata")


@app.route("/vs-flight-reader")
def seo_vs_flight_reader():
    return _seo_view("/vs-flight-reader")


@app.route("/vs-px4-review")
def seo_vs_px4_review():
    return _seo_view("/vs-px4-review")


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
        "Sitemap: https://droneflight-report.com/sitemap.xml\n"
    )
    return Response(body, mimetype="text/plain")


@app.route("/sitemap.xml")
def sitemap_xml():
    urls = [
        ("/", "1.0", "weekly"),
        ("/dji-flight-log", "0.8", "monthly"),
        ("/ardupilot-bin", "0.8", "monthly"),
        ("/px4-ulg", "0.8", "monthly"),
        ("/vs-airdata", "0.6", "monthly"),
        ("/vs-flight-reader", "0.6", "monthly"),
        ("/vs-px4-review", "0.6", "monthly"),
        ("/privacy", "0.3", "yearly"),
    ]
    parts = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for loc, prio, freq in urls:
        parts.append(
            "  <url><loc>https://droneflight-report.com%s</loc>"
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
