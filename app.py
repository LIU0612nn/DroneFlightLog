import os
import re
import math
import json
import uuid
import tempfile
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

<title>Drone Flight Report</title>

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
    padding: 30px 10px 10px;
    text-align: center;
    color: #64748b;
    font-size: 14px;
}

.privacy-footer {
    max-width: 850px;
    margin: 0 auto 25px;

    padding: 24px;

    border-top:
        1px solid rgba(148,163,184,.15);

    border-bottom:
        1px solid rgba(148,163,184,.10);

    line-height: 1.7;
}

.privacy-footer strong {
    display: block;

    color: #cbd5e1;

    font-size: 15px;

    margin-bottom: 12px;
}

.privacy-footer p {
    margin: 7px 0;
}

.privacy-note {
    margin-top: 15px !important;
}

.footer-brand {
    color: #475569;
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
            Upload your drone flight log and generate
            a flight trajectory, statistics, wind reference
            and professional report.
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

                    Allow anonymous flight data to be saved
                    for future analysis and service improvement.

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

<footer>

    <div class="privacy-footer">

        <strong>Privacy & Data Retention</strong>

        <p>
            Your original flight log is processed only
            to generate your report and is deleted after
            processing.
        </p >

        <p>
            If you choose to share data, only a
            de-identified version may be retained for
            up to 30 days.
        </p >

        <p>
            Generated PDF and image files are automatically
            removed after a limited retention period.
        </p >

        <p>
            We do not intentionally retain your original
            filename, name, phone number, email address,
            or postal address in the shared dataset.
        </p >

        <p class="privacy-note">
            Wind information is a regional historical
            weather reference and is not a local
            real-time wind measurement.
        </p >

    </div>

    <div class="footer-brand">

        Drone Flight Report

    </div>

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
}


def find_column(df, candidates):
    """
    Find a matching column in a DataFrame.
    """

    normalized = {
        col: normalize_column_name(col)
        for col in df.columns
    }

    # Exact match
    for col, norm in normalized.items():
        if norm in candidates:
            return col

    

    return None


def parse_altitude_column(df, altitude_col):
    """
    Convert altitude to meters when the source column
    explicitly uses feet.
    """

    if altitude_col is None:
        return pd.Series(
            [np.nan] * len(df),
            index=df.index,
            dtype=float,
        )

    normalized = normalize_column_name(
        altitude_col
    )

    altitude = pd.to_numeric(
        df[altitude_col],
        errors="coerce",
    )

    # Explicit feet
    if (
        "feet" in normalized
        or normalized.endswith("ft")
    ):
        return altitude / 3.28084

    # Explicit meters
    if (
        "meter" in normalized
        or normalized.endswith("m")
    ):
        return altitude

    # Common altitude fields
    if normalized in {
        "altitude",
        "alt",
        "height",
    }:
        return altitude
    
    return pd.Series(
        [np.nan] * len(df),
        index=df.index,
        dtype=float,
    )


def find_lat_lon_alt_datetime(df):
    """
    Find latitude, longitude, altitude and UTC datetime
    columns from a generic CSV/TXT flight log.
    """

    lat_col = find_column(
        df,
        LAT_NAMES,
    )

    lon_col = find_column(
        df,
        LON_NAMES,
    )

    datetime_col = find_column(
        df,
        DATETIME_NAMES,
    )

    altitude_candidates = [
        "heightabovetakeofffeet",
        "heightabovetakeoffmeter",
        "heightabovetakeoffmeters",

        "relativealtitudefeet",
        "relativealtitudemeter",
        "relativealtitudemeters",

        "altitudefeet",
        "altitudemeter",
        "altitudemeters",

        "altitudeabovesealevelfeet",
        "altitudeabovesealevelmeter",
        "altitudeabovesealevelmeters",

        "altitude",
        "altitudem",
        "alt",
        "height",
        "heightm",
    ]

    altitude_col = find_column(
        df,
        set(altitude_candidates),
    )

    return (
        lat_col,
        lon_col,
        altitude_col,
        datetime_col,
    )


def parse_csv_or_txt(path):
    """
    Read CSV/TXT flight logs.

    Tries several common encodings and separators.
    """

    encodings = [
        "utf-8-sig",
        "utf-8",
        "gb18030",
        "latin1",
    ]

    separators = [
        ",",
        "\t",
        ";",
    ]

    last_error = None

    for encoding in encodings:
        for separator in separators:
            try:
                df = pd.read_csv(
                    path,
                    encoding=encoding,
                    sep=separator,
                )

                if len(df.columns) >= 2:
                    return df

            except Exception as exc:
                last_error = exc

    raise ValueError(
        f"Could not read CSV/TXT file: {last_error}"
    )
def parse_bin_log(path):
    """
    Parse an ArduPilot DataFlash BIN log.

    DataFlash BIN is NOT a MAVLink stream.
    Use pymavlink's DFReader instead.
    """

    log = DFReader.DFReader_binary(path)

    rows = []

    while True:
        msg = log.recv_match(
            type=["GPS", "GPS2"],
            blocking=False,
        )

        if msg is None:
            break

        try:
            lat = float(msg.Lat)
            lon = float(msg.Lng)
            alt = float(msg.Alt)

            if not (
                -90 <= lat <= 90
                and -180 <= lon <= 180
            ):
                continue

            row = {
                "latitude": lat,
                "longitude": lon,
                "altitude": alt,
                "altitude_reference": "MSL",
            }

            if hasattr(msg, "GWk") and hasattr(msg, "GMS"):
                try:
                    gps_week = int(msg.GWk)
                    gps_week_ms = float(msg.GMS)

                    gps_epoch = pd.Timestamp(
                        "1980-01-06",
                        tz="UTC",
                    )

                    timestamp = (
                        gps_epoch
                        + pd.to_timedelta(
                            gps_week,
                            unit="W",
                        )
                        + pd.to_timedelta(
                            gps_week_ms,
                            unit="ms",
                        )
                        - pd.Timedelta(
                            seconds=18
                        )
                    )

                    row["timestamp"] = timestamp

                except Exception:
                    pass

            rows.append(row)

        except Exception:
            continue

    if not rows:
        raise ValueError(
            "BIN file was read, but no valid GPS records "
            "were found in the DataFlash GPS/GPS2 messages."
        )

    return pd.DataFrame(rows)


def parse_ulg_log(path):
    """
    Parse a PX4 ULog GPS dataset.

    Supports:
        vehicle_gps_position
        sensor_gps
    """

    ulog = ULog(path)

    dataset = None

    for name in [
        "vehicle_gps_position",
        "sensor_gps",
    ]:
        try:
            dataset = ulog.get_dataset(name)
            break
        except Exception:
            continue

    if dataset is None:
        raise ValueError(
            "ULG file does not contain a supported GPS dataset."
        )

    data = dataset.data

    # Latitude / longitude
    if (
        "latitude_deg" in data
        and "longitude_deg" in data
    ):
        lat = pd.Series(
            data["latitude_deg"]
        )

        lon = pd.Series(
            data["longitude_deg"]
        )

    elif (
        "lat" in data
        and "lon" in data
    ):
        lat = pd.Series(
            data["lat"]
        ) / 1e7

        lon = pd.Series(
            data["lon"]
        ) / 1e7

    else:
        raise ValueError(
            "ULG GPS dataset does not contain "
            "supported latitude/longitude fields."
        )

    # Altitude
    altitude_reference = "UNKNOWN"
    
    if "altitude_msl_m" in data:
        altitude = pd.Series(
            data["altitude_msl_m"]
        )
    
        altitude_reference = "MSL"
    
    elif "alt" in data:
        altitude = (
            pd.Series(data["alt"])
            / 1000.0
        )
    
    else:
        altitude = pd.Series(
            [np.nan] * len(lat)
        )
    
    df = pd.DataFrame(
        {
            "latitude": lat,
            "longitude": lon,
            "altitude": altitude,
            "altitude_reference": altitude_reference,
        }
    )

    # UTC timestamp
    if "time_gps_usec" in data:
        try:
            df["timestamp"] = pd.to_datetime(
                data["time_gps_usec"],
                unit="us",
                utc=True,
            )
        except Exception:
            pass

    elif "timestamp" in data:
        timestamp_values = pd.Series(
            data["timestamp"]
        )

        try:
            if (
                len(timestamp_values)
                and timestamp_values.max() > 1e14
            ):
                df["timestamp"] = pd.to_datetime(
                    timestamp_values,
                    unit="us",
                    utc=True,
                )
        except Exception:
            pass

    return df

def normalize_flight_data(df):
    """
    将所有来源的飞行数据统一成内部标准格式。
    """
    # ===== 诊断代码 =====
    print("========== 输入的列名: ", list(df.columns) if df is not None else "None")
    # ===================

    if df is None or df.empty:
        return pd.DataFrame()

    df = df.copy()

    # 统一列名
    df.columns = [
        str(c).strip().lower().replace(" ", "_")
        for c in df.columns
    ]

    # 找经纬度
    lat_candidates = ["latitude_deg", "latitude", "lat", "gps_lat", "gps_latitude"]
    lon_candidates = ["longitude_deg", "longitude", "lon", "lng", "gps_lon", "gps_longitude"]

    def find_col(candidates):
        for name in candidates:
            if name in df.columns:
                return name
        return None

    lat_col = find_col(lat_candidates)
    lon_col = find_col(lon_candidates)

    if lat_col is None or lon_col is None:
        raise ValueError(
            f"无法识别 GPS 经纬度字段。当前列名：{list(df.columns)}"
        )

    df["latitude_deg"] = pd.to_numeric(df[lat_col], errors="coerce")
    df["longitude_deg"] = pd.to_numeric(df[lon_col], errors="coerce")

    # 处理 1e7 整数
    lat_valid = df["latitude_deg"].dropna()
    lon_valid = df["longitude_deg"].dropna()

    if not lat_valid.empty and lat_valid.abs().median() > 180:
        df["latitude_deg"] = df["latitude_deg"] / 1e7
    if not lon_valid.empty and lon_valid.abs().median() > 180:
        df["longitude_deg"] = df["longitude_deg"] / 1e7

    # 高度
    alt_candidates = ["altitude_m", "altitude", "alt", "height", "height_m", "relative_altitude"]
    alt_ft_candidates = ["altitude_ft", "alt_ft", "height_ft", "relative_altitude_ft"]

    alt_m_col = find_col(alt_candidates)
    alt_ft_col = find_col(alt_ft_candidates)

    df["altitude_m"] = np.nan
    df["altitude_reference"] = "UNKNOWN"

    if alt_m_col is not None:
        df["altitude_m"] = pd.to_numeric(df[alt_m_col], errors="coerce")
        name = str(alt_m_col).lower()
        if "relative" in name or "takeoff" in name:
            df["altitude_reference"] = "AGL"
        elif "msl" in name:
            df["altitude_reference"] = "MSL"
    elif alt_ft_col is not None:
        df["altitude_m"] = pd.to_numeric(df[alt_ft_col], errors="coerce") * 0.3048
        name = str(alt_ft_col).lower()
        if "relative" in name or "takeoff" in name:
            df["altitude_reference"] = "AGL"

    # 时间
    time_candidates = ["timestamp_utc", "timestamp", "time", "datetime", "date_time", "utc_time", "time_utc"]
    time_col = find_col(time_candidates)

    if time_col is not None:
        raw_time = df[time_col]
        parsed = pd.to_datetime(raw_time, errors="coerce", utc=True)
        numeric = pd.to_numeric(raw_time, errors="coerce")

        if numeric.notna().sum() > 0:
            median_value = numeric.dropna().abs().median()
            if median_value > 1e17:
                numeric_time = pd.to_datetime(numeric, unit="ns", errors="coerce", utc=True)
            elif median_value > 1e14:
                numeric_time = pd.to_datetime(numeric, unit="us", errors="coerce", utc=True)
            elif median_value > 1e11:
                numeric_time = pd.to_datetime(numeric, unit="ms", errors="coerce", utc=True)
            elif median_value > 1e8:
                numeric_time = pd.to_datetime(numeric, unit="s", errors="coerce", utc=True)
            else:
                numeric_time = pd.Series(pd.NaT, index=df.index)
            parsed = parsed.fillna(numeric_time)

        df["timestamp_utc"] = parsed
    else:
        df["timestamp_utc"] = pd.NaT

    # 速度
    speed_mps_col = find_col(["speed_mps", "speed_ms", "ground_speed_mps", "ground_speed_ms", "velocity_mps"])
    speed_kmh_col = find_col(["speed_kmh", "ground_speed_kmh", "velocity_kmh"])
    speed_mph_col = find_col(["speed_mph", "ground_speed_mph", "velocity_mph"])
    speed_knots_col = find_col(["speed_knots", "speed_kt", "ground_speed_knots", "velocity_knots"])
    speed_generic_col = find_col(["speed", "velocity", "ground_speed", "groundspeed"])

    df["speed_mps"] = np.nan

    if speed_mps_col is not None:
        df["speed_mps"] = pd.to_numeric(df[speed_mps_col], errors="coerce")
    elif speed_kmh_col is not None:
        df["speed_mps"] = pd.to_numeric(df[speed_kmh_col], errors="coerce") / 3.6
    elif speed_mph_col is not None:
        df["speed_mps"] = pd.to_numeric(df[speed_mph_col], errors="coerce") * 0.44704
    elif speed_knots_col is not None:
        df["speed_mps"] = pd.to_numeric(df[speed_knots_col], errors="coerce") * 0.514444
    elif speed_generic_col is not None:
        df["speed_mps"] = pd.to_numeric(df[speed_generic_col], errors="coerce")

    # 航向
    heading_col = find_col(["heading_deg", "heading", "yaw_deg", "yaw", "course_deg", "course", "track_deg", "track"])
    df["heading_deg"] = np.nan
    if heading_col is not None:
        df["heading_deg"] = pd.to_numeric(df[heading_col], errors="coerce") % 360

    # ===== 兼容旧代码（必须在 for 循环外面！）=====
    df["latitude"] = df["latitude_deg"]
    df["longitude"] = df["longitude_deg"]
    df["altitude"] = df["altitude_m"]
    df["timestamp"] = df["timestamp_utc"]

    # 过滤无效 GPS 数据
    valid_gps = (
        df["latitude_deg"].between(-90, 90)
        & df["longitude_deg"].between(-180, 180)
    )
    df = df.loc[valid_gps].copy()

    if df.empty:
        raise ValueError("没有找到有效的 GPS 经纬度数据。")

    df = df.reset_index(drop=True)

    print("========== 输出列名: ", list(df.columns))
    print("========== 有效行数: ", len(df))

    return df
def parse_flight_log(path):
    """
    Dispatch the uploaded file to the
    appropriate parser.
    """

    extension = os.path.splitext(
        path
    )[1].lower()

    if extension in {
        ".csv",
        ".txt",
    }:
        raw_df = parse_csv_or_txt(
            path
        )

        return normalize_flight_data(
            raw_df
        )

    if extension == ".bin":
        raw_df = parse_bin_log(
            path
        )

        return normalize_flight_data(
            raw_df
        )

    if extension == ".ulg":
        raw_df = parse_ulg_log(
            path
        )

        return normalize_flight_data(
            raw_df
        )

    raise ValueError(
        "Unsupported file type."
        "Supported formats: "
        "CSV, TXT, BIN, ULG."
    )



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

    if len(df) < 2:

        return 0.0


    total = 0.0


    for i in range(1, len(df)):

        total += haversine_distance(
        df.iloc[i - 1]["latitude_deg"],
            df.iloc[i - 1]["longitude_deg"],
            df.iloc[i]["latitude_deg"],
            df.iloc[i]["longitude_deg"]
        )


    return total


def calculate_statistics(df):

    distance_m = calculate_distance(
        df
    )


    altitude = pd.to_numeric(
        df["altitude_m"],
        errors="coerce"
    )


    stats = {

        "points": int(len(df)),

        "distance_m":
            float(distance_m),

        "distance_km":
            float(distance_m / 1000.0),

        "max_altitude":
            float(
                altitude.max()
            )
            if altitude.notna().any()
            else None,

        "min_altitude":
            float(
                altitude.min()
            )
            if altitude.notna().any()
            else None,

        "mean_altitude":
            float(
                altitude.mean()
            )
            if altitude.notna().any()
            else None,
    }


    return stats


# =========================================================
# Flight date
# =========================================================

def get_flight_date(df):

    if (
        "timestamp" not in df.columns
        or df["timestamp"].isna().all()
    ):

        return datetime.utcnow().strftime(
            "%Y-%m-%d"
        )


    try:

        values = pd.to_datetime(
            df["timestamp"],
            errors="coerce"
        )


        values = values.dropna()


        if len(values):

            return values.iloc[0].strftime(
                "%Y-%m-%d"
            )

    except Exception:

        pass


    return datetime.utcnow().strftime(
        "%Y-%m-%d"
    )
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
                "wind_speed_10m,wind_direction_10m,"
                "wind_speed_100m,wind_direction_100m",

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

        vertical_profile = []
        for altitude_m in (10, 100):
            level_speeds = hourly.get(f"wind_speed_{altitude_m}m", [])
            level_directions = hourly.get(f"wind_direction_{altitude_m}m", [])
            level_valid = []
            for speed, direction in zip(level_speeds, level_directions):
                if speed is None or direction is None:
                    continue
                try:
                    level_valid.append((float(speed), float(direction)))
                except (TypeError, ValueError):
                    continue
            if level_valid:
                level_u = []
                level_v = []
                for speed, direction in level_valid:
                    u, v = wind_to_uv(speed, direction)
                    level_u.append(u)
                    level_v.append(v)
                mean_level_u = sum(level_u) / len(level_u)
                mean_level_v = sum(level_v) / len(level_v)
                mean_level_speed = math.sqrt(mean_level_u ** 2 + mean_level_v ** 2)
                mean_level_direction = (
                    math.degrees(math.atan2(-mean_level_u, -mean_level_v)) + 360
                ) % 360
                vertical_profile.append({
                    "altitude_m": altitude_m,
                    "speed": mean_level_speed,
                    "direction": mean_level_direction,
                    "source": "Open-Meteo Historical Weather model",
                })


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
def direction_to_chinese(direction):
    """
    Convert meteorological wind direction (FROM direction)
    into an easy-to-read Chinese 8-point direction.
    """
    if direction is None:
        return None

    direction = float(direction) % 360

    directions = [
        "北",
        "东北",
        "东",
        "东南",
        "南",
        "西南",
        "西",
        "西北",
    ]

    index = int(
        ((direction + 22.5) % 360) // 45
    )

    return directions[index]


def get_wind_field(df, flight_date, grid_size=5):
    """
    Regional historical wind reference.

    This is NOT a local CFD wind model.
    It is only a regional weather reference.
    """

    if not flight_date:
        return {
            "speed": None,
            "direction": None,
            "direction_cn": None,
            "source": "Unavailable: flight date not available",
            "grid": [],
        }

    try:

        # -----------------------------------------
        # Use the center of the actual flight path
        # -----------------------------------------

        latitude = float(
            df["latitude"].mean()
        )

        longitude = float(
            df["longitude"].mean()
        )

        # -----------------------------------------
        # Historical weather
        # -----------------------------------------

        url = (
            "https://archive-api.open-meteo.com/v1/archive"
        )

        params = {
            "latitude": latitude,
            "longitude": longitude,
            "start_date": flight_date,
            "end_date": flight_date,
            "hourly":
                "wind_speed_10m,wind_direction_10m",
            "wind_speed_unit": "ms",
            "timezone": "UTC",
        }

        response = requests.get(
            url,
            params=params,
            timeout=20
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

        valid = []

        for speed, direction in zip(
            speeds,
            directions
        ):

            if (
                speed is None
                or direction is None
            ):
                continue

            try:
                valid.append(
                    (
                        float(speed),
                        float(direction)
                    )
                )
            except Exception:
                continue

        if not valid:
            raise ValueError(
                "No valid historical wind data."
            )

        # -----------------------------------------
        # Average by vector, NOT raw degrees
        # -----------------------------------------

        u_values = []
        v_values = []

        for speed, direction in valid:

            u, v = wind_to_uv(
                speed,
                direction
            )

            u_values.append(u)
            v_values.append(v)

        mean_u = (
            sum(u_values)
            / len(u_values)
        )

        mean_v = (
            sum(v_values)
            / len(v_values)
        )

        mean_speed = math.sqrt(
            mean_u ** 2
            +
            mean_v ** 2
        )

        mean_direction = (
            math.degrees(
                math.atan2(
                    -mean_u,
                    -mean_v
                )
            )
            + 360
        ) % 360

        direction_cn = (
            direction_to_chinese(
                mean_direction
            )
        )

        # -----------------------------------------
        # One regional reference vector
        # -----------------------------------------

        grid = [{
            "lat": latitude,
            "lon": longitude,
            "u": mean_u,
            "v": mean_v,
            "speed": mean_speed,
            "direction": mean_direction,
        }]

        return {
            "speed": mean_speed,
            "direction": mean_direction,
            "direction_cn": direction_cn,
            "source":
                "Open-Meteo Historical Weather",
            "grid": grid,
            "vertical_profile": vertical_profile,
        }

    except Exception as e:

        print(
            "Wind reference error:",
            repr(e)
        )

        return {
            "speed": None,
            "direction": None,
            "direction_cn": None,
            "source":
                "Historical wind data unavailable",
            "grid": [],
            "vertical_profile": [],
        }

# =========================================================
# Generate flight plot
# =========================================================

def generate_flight_plot(
    df,
    wind
):

    fig, ax = plt.subplots(
        figsize=(10, 7)
    )
# Normal GPS coordinate formatting
    ax.xaxis.set_major_formatter(FormatStrFormatter('%.4f'))
    ax.yaxis.set_major_formatter(FormatStrFormatter('%.4f'))

    # -----------------------------------------------------
    # Flight trajectory
    # -----------------------------------------------------

    ax.plot(
        df["longitude"],
        df["latitude"],
        linewidth=2.2,
        label="Flight trajectory"
    )


    # -----------------------------------------------------
    # Start / end
    # -----------------------------------------------------

    ax.scatter(
        df.iloc[0]["longitude"],
        df.iloc[0]["latitude"],
        s=80,
        marker="o",
        label="Start"
    )


    ax.scatter(
        df.iloc[-1]["longitude"],
        df.iloc[-1]["latitude"],
        s=80,
        marker="X",
        label="End"
    )


    # -----------------------------------------------------
    # Wind reference arrows
    # -----------------------------------------------------

    if (
        wind.get("speed") is not None
        and wind.get("direction") is not None
    ):

        speed = wind["speed"]

        direction = wind["direction"]


        u, v = wind_to_uv(
            speed,
            direction
        )


        lon_min = df[
            "longitude"
        ].min()


        lon_max = df[
            "longitude"
        ].max()


        lat_min = df[
            "latitude"
        ].min()


        lat_max = df[
            "latitude"
        ].max()


        lon_span = max(
            lon_max - lon_min,
            0.0001
        )


        lat_span = max(
            lat_max - lat_min,
            0.0001
        )
# ---------------------------------------------------------
# Macro wind field
# Each grid point uses its own u / v vector
# ---------------------------------------------------------

    grid = wind.get("grid", [])

    if grid:
        lons = [float(p["lon"]) for p in grid]
        lats = [float(p["lat"]) for p in grid]
        us = [float(p["u"]) for p in grid]
        vs = [float(p["v"]) for p in grid]

        max_speed = max(
            (float(p.get("speed", 0)) for p in grid),
            default=1.0
        )

        lon_span = max(lons) - min(lons)
        lat_span = max(lats) - min(lats)

        display_span = min(
            lon_span if lon_span > 0 else 0.001,
            lat_span if lat_span > 0 else 0.001
        )

        arrow_scale = (
            display_span * 0.12
            / max(max_speed, 0.1)
        )

        arrow_u = [
            u * arrow_scale
            for u in us
        ]

        arrow_v = [
            v * arrow_scale
            for v in vs
        ]

        ax.quiver(
            lons,
            lats,
            arrow_u,
            arrow_v,
            angles="xy",
            scale_units="xy",
            scale=1,
            width=0.002,
            headwidth=3,
            headlength=4,
            headaxislength=3.5,
            alpha=0.65
        )

        

        


        ax.text(
            0.02,
            0.97,

            (
                f"Reference wind: "
                f"{speed:.1f} km/h"
                f" @ "
                f"{direction:.0f}°"
            ),

            transform=ax.transAxes,

            verticalalignment="top",

            fontsize=10
        )


    else:

        ax.text(
            0.02,
            0.97,

            "Wind data unavailable",

            transform=ax.transAxes,

            verticalalignment="top",

            fontsize=10
        )


    # -----------------------------------------------------
    # Labels
    # -----------------------------------------------------

    ax.set_title(
        "Drone Flight Trajectory"
    )


    ax.set_xlabel(
        "Longitude"
    )


    ax.set_ylabel(
        "Latitude"
    )


    ax.grid(
        True,
        alpha=0.25
    )


    ax.legend()


    fig.tight_layout()


    filename = (
        f"flight_{uuid.uuid4().hex}.png"
    )


    filepath = os.path.join(
        GENERATED_DIR,
        filename
    )


    fig.savefig(
        filepath,
        dpi=180,
        bbox_inches="tight"
    )


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
                f"{wind['speed']:.1f} km/h"
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


    c.showPage()
    c.setFont("Helvetica-Bold", 16)
    c.drawString(50, height - 50, "Data Quality & Methodology")
    c.setFont("Helvetica", 10)
    method_lines = [
        "Telemetry values shown in this report come from the uploaded flight log.",
        "Missing altitude, speed, battery, and wind values are not fabricated.",
        "Wind values are labeled as regional model references when available.",
        "They are not direct local measurements at the aircraft.",
        "",
        f"Recorded GPS points: {stats.get('points', 'N/A')}",
        f"Wind source: {wind.get('source', 'Missing') if wind else 'Missing'}",
        f"Vertical wind levels available: {len(wind.get('vertical_profile', [])) if wind else 0}",
        "",
        "Altitude semantics follow the parser's recorded fields.",
        "The vertical profile is displayed only for model levels returned by the source.",
        "It is not a substitute for an independent in-situ wind measurement.",
    ]
    y = height - 90
    for line in method_lines:
        if len(line) > 112:
            line = line[:109] + "..."
        c.drawString(50, y, line)
        y -= 18

    c.save()


    return filename


# =========================================================
# P1 browser analysis payload
# =========================================================

def _safe_float(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def build_analysis_payload(df, wind):
    """Build P1 browser data from recorded telemetry and labeled wind references."""
    rows = []
    grid = (wind or {}).get("grid", [])
    for index, row in df.iterrows():
        lat = _safe_float(row.get("latitude"))
        lon = _safe_float(row.get("longitude"))
        if lat is None or lon is None:
            continue
        nearest = None
        if grid:
            nearest = min(
                grid,
                key=lambda point: (float(point.get("lat", lat)) - lat) ** 2
                + (float(point.get("lon", lon)) - lon) ** 2,
            )
        wind_speed = _safe_float(nearest.get("speed")) if nearest else _safe_float((wind or {}).get("speed"))
        wind_direction = _safe_float(nearest.get("direction")) if nearest else _safe_float((wind or {}).get("direction"))
        rows.append({
            "index": int(index),
            "lat": lat,
            "lon": lon,
            "altitude_m": _safe_float(row.get("altitude_m")),
            "speed_mps": _safe_float(row.get("speed_mps")),
            "elapsed_seconds": _safe_float(row.get("elapsed_seconds")),
            "wind_speed_mps": wind_speed,
            "wind_direction_deg": wind_direction,
            "wind_source": (wind or {}).get("source") if wind_speed is not None else "missing",
        })
    if len(rows) > 360:
        stride = max(1, len(rows) // 360)
        rows = rows[::stride]
        last = df.iloc[-1]
        if rows and rows[-1]["index"] != int(df.index[-1]):
            rows.append({
                "index": int(df.index[-1]),
                "lat": _safe_float(last.get("latitude")),
                "lon": _safe_float(last.get("longitude")),
                "altitude_m": _safe_float(last.get("altitude_m")),
                "speed_mps": _safe_float(last.get("speed_mps")),
                "elapsed_seconds": _safe_float(last.get("elapsed_seconds")),
                "wind_speed_mps": _safe_float((wind or {}).get("speed")),
                "wind_direction_deg": _safe_float((wind or {}).get("direction")),
                "wind_source": (wind or {}).get("source", "missing"),
            })
    has_time = bool(rows) and all(item["elapsed_seconds"] is not None for item in rows)
    x = [item["elapsed_seconds"] if has_time else item["index"] for item in rows]
    events = []
    if rows:
        events.extend([
            {"kind": "derived", "label": "Trajectory start", "index": rows[0]["index"], "x": x[0]},
            {"kind": "derived", "label": "Trajectory end", "index": rows[-1]["index"], "x": x[-1]},
        ])
    if (wind or {}).get("speed") is not None and rows:
        events.append({"kind": "reference", "label": "Regional wind reference available", "index": rows[0]["index"], "x": x[0]})
    return {
        "nodes": rows,
        "series": {
            "x_label": "elapsed_seconds" if has_time else "sample_index",
            "x": x,
            "altitude_m": [item["altitude_m"] for item in rows],
            "speed_mps": [item["speed_mps"] for item in rows],
            "battery_percent": [None for _ in rows],
        },
        "events": events,
        "vertical_profile": (wind or {}).get("vertical_profile", []),
    }


# =========================================================
# Save anonymous flight data
# =========================================================

def save_deidentified_log(df):

    """
    Save only normalized flight fields.

    No original filename or other raw columns
    are stored.
    """

    filename = (
        f"anonymous_"
        f"{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_"
        f"{uuid.uuid4().hex[:8]}.csv"
    )


    path = os.path.join(
        LOG_DIR,
        filename
    )


    columns = [
        "latitude",
        "longitude",
        "altitude",
        "timestamp",
    ]


    available = [
        col
        for col in columns
        if col in df.columns
    ]


    df[
        available
    ].to_csv(
        path,
        index=False
    )


    return path
# =========================================================
# Demo flight
# =========================================================

def create_demo_flight():

    points = 80


    center_lat = 34.0522
    center_lon = -118.2437


    rows = []


    for i in range(points):

        angle = (
            2
            * math.pi
            * i
            / (points - 1)
        )


        radius = 0.006


        lat = (
            center_lat
            + radius
            * math.sin(angle)
        )


        lon = (
            center_lon
            + radius
            * math.cos(angle)
        )


        altitude = (
            40
            + 15
            * math.sin(angle * 2)
        )


        rows.append({

            "latitude":
                lat,

            "latitude_deg":
                lat,

            "longitude":
                lon,

            "longitude_deg":
                lon,

            "altitude":
                altitude,

            "altitude_m":
                altitude,

            "speed_mps":
                8.0 + 2.0 * math.sin(angle),

            "elapsed_seconds":
                float(i),

            "timestamp":
                datetime.utcnow() + timedelta(seconds=i),
        })


    return pd.DataFrame(
        rows
    )


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
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">

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

#flight-map { width:100%; height:430px; border-radius:12px; background:#0b1220; }
.analysis-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:18px; }
.analysis-panel { background:#0b1220; border:1px solid rgba(148,163,184,.15); border-radius:14px; padding:18px; }
.analysis-panel h3 { margin-top:0; }
.event-row { display:flex; gap:12px; border-left:2px solid #38bdf8; padding:8px 0 8px 12px; }
.event-kind { color:#94a3b8; font-size:12px; }
@media (max-width:760px) { .analysis-grid { grid-template-columns:1fr; } }

</style>

</head>


<body>

<div class="container">

<h1>Drone Flight Report</h1>

<div class="subtitle">

    {{ flight_date }}

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

    <h2>Flight Trajectory</h2>

    <img
        src="/generated/{{ image_filename }}"
        alt="Flight trajectory"
    >

</div>


<div class="card">
    <h2>Flight Map &amp; Timeline</h2>
    <div id="flight-map"></div>
    <div id="node-detail" class="small" style="margin-top:14px;">Select a trajectory node to inspect recorded telemetry and wind provenance.</div>
</div>

<div class="analysis-grid">
    <div class="analysis-panel">
        <h3>Event Timeline</h3>
        {% if analysis_events %}
            {% for event in analysis_events %}
            <div class="event-row"><div><strong>{{ event.label }}</strong><div class="event-kind">{{ event.kind }} · x={{ event.x }}</div></div></div>
            {% endfor %}
        {% else %}<div class="small">No derived or source events were recorded.</div>{% endif %}
    </div>
    <div class="analysis-panel">
        <h3>Vertical Wind Profile</h3>
        {% if vertical_profile %}
            {% for level in vertical_profile %}
            <div class="event-row"><div><strong>{{ level.altitude_m }} m AGL</strong><div class="event-kind">{{ "%.1f"|format(level.speed * 3.6) }} km/h · FROM {{ "%.0f"|format(level.direction) }}° · model reference</div></div></div>
            {% endfor %}
        {% else %}<div class="small">No vertical wind profile is available in the source data.</div>{% endif %}
    </div>
</div>

<div class="card">
    <h2>Telemetry Charts</h2>
    <svg id="telemetry-chart" viewBox="0 0 760 260" role="img" aria-label="Altitude and speed chart" style="width:100%;height:auto;"></svg>
    <div class="small">Battery data is shown only when recorded by the uploaded log; this report does not infer battery values.</div>
</div>

<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
const nodes = {{ analysis_nodes|tojson }};
const series = {{ analysis_series|tojson }};
const mapEl = document.getElementById('flight-map');
const detail = document.getElementById('node-detail');
const map = L.map(mapEl).setView([0, 0], 2);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {maxZoom:19, attribution:'&copy; OpenStreetMap'}).addTo(map);
function showNode(node) {
    detail.innerHTML = '<strong>Sample '+node.index+'</strong> · '+node.lat.toFixed(6)+', '+node.lon.toFixed(6)+
        '<br>Altitude: '+(node.altitude_m===null?'N/A':node.altitude_m.toFixed(1)+' m')+
        ' · Speed: '+(node.speed_mps===null?'N/A':node.speed_mps.toFixed(1)+' m/s')+
        '<br>Wind: '+(node.wind_speed_mps===null?'missing':(node.wind_speed_mps*3.6).toFixed(1)+' km/h FROM '+node.wind_direction_deg.toFixed(0)+'°')+
        ' · Source: '+(node.wind_source||'missing');
}
if (nodes.length) {
    const points = nodes.map(n=>[n.lat,n.lon]);
    L.polyline(points,{color:'#38bdf8',weight:4}).addTo(map);
    nodes.forEach((node,i)=>L.circleMarker([node.lat,node.lon],{radius:i===0||i===nodes.length-1?7:4,color:'#fbbf24',fillOpacity:.85}).addTo(map).on('click',()=>showNode(node)));
    map.fitBounds(L.latLngBounds(points).pad(.15));
    showNode(nodes[0]);
} else { mapEl.innerHTML='<div style="padding:24px;color:#94a3b8;">Map preview unavailable for this log.</div>'; }
const svg=document.getElementById('telemetry-chart');
const values=(series.altitude_m||[]).concat(series.speed_mps||[]).filter(v=>v!==null);
if (!values.length) svg.innerHTML='<text x="24" y="40" fill="#94a3b8">No altitude or speed telemetry was recorded.</text>';
else {
    const left=48,right=18,top=18,bottom=32,width=760,height=260,max=Math.max.apply(null,values.concat([1])),count=Math.max((series.x||[]).length-1,1);
    function pathFor(data,color){const pts=data.map((v,i)=>v===null?null:(left+(i/count)*(width-left-right)).toFixed(1)+','+(top+(height-top-bottom)*(1-v/max)).toFixed(1));let d='';pts.forEach(p=>{if(p)d+=(d?'L':'M')+p;});return '<path d="'+d+'" fill="none" stroke="'+color+'" stroke-width="2.5"/>';}
    svg.innerHTML='<line x1="48" y1="228" x2="742" y2="228" stroke="#334155"/><line x1="48" y1="18" x2="48" y2="228" stroke="#334155"/>'+pathFor(series.altitude_m||[],'#38bdf8')+pathFor(series.speed_mps||[],'#fbbf24')+'<text x="58" y="248" fill="#94a3b8" font-size="12">'+series.x_label+'</text><text x="600" y="30" fill="#38bdf8" font-size="12">altitude</text><text x="670" y="30" fill="#fbbf24" font-size="12">speed</text>';
}
</script>


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


        # -------------------------------------------------
        # Statistics
        # -------------------------------------------------

        stats = calculate_statistics(
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

        flight_date = get_flight_date(df)
        first_lat = float(df.iloc[0]["latitude"])
        first_lon = float(df.iloc[0]["longitude"])

        if save_consent:
            save_deidentified_log(df)
            # 调用真实气象API拿数据（不展示，只存）
            wind_for_training = get_wind_field(df, flight_date, grid_size=9)

            # 保存风场快照
            try:
                import json
                wind_record = {
                    "timestamp": datetime.utcnow().isoformat(),
                    "latitude": first_lat,
                    "longitude": first_lon,
                    "wind_speed": wind_for_training.get("speed"),
                    "wind_direction": wind_for_training.get("direction"),
                    "wind_source": wind_for_training.get("source"),
                    "flight_date": flight_date,
                }
                wind_record_path = os.path.join(
                    LOG_DIR,
                    f"wind_{uuid.uuid4().hex[:8]}.json"
                )
                with open(wind_record_path, "w") as f:
                    json.dump(wind_record, f)
                print(f"========== 风场快照已保存: {wind_record_path} ==========")
            except Exception as e:
                print(f"========== 风场快照保存失败: {e} ==========")

            wind = {
                "speed": wind_for_training.get("speed"),
                "direction": wind_for_training.get("direction"),
                "direction_cn": wind_for_training.get("direction_cn"),
                "source": wind_for_training.get("source", "Disabled"),
                "grid": wind_for_training.get("grid", []),
                "vertical_profile": wind_for_training.get("vertical_profile", []),
            }
        else:
            wind = {
                "speed": None,
                "direction": None,
                "direction_cn": None,
                "source": "Disabled",
                "grid": [],
                "vertical_profile": [],
            }

        print(
            "Wind field grid points:",
            len(wind.get("grid", []))
        )

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

        analysis = build_analysis_payload(df, wind)


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

            analysis_nodes=analysis["nodes"],
            analysis_series=analysis["series"],
            analysis_events=analysis["events"],
            vertical_profile=analysis["vertical_profile"],

        )


    except Exception as exc:

        error_message = str(exc)


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
    # 删除临时上传文件
       if temp_path and os.path.exists(temp_path):
        try:
            os.remove(temp_path)
        except Exception:
            pass
    
    # 清理超过24小时的生成文件
    try:
        now = datetime.utcnow()
        for f in os.listdir(GENERATED_DIR):
            fpath = os.path.join(GENERATED_DIR, f)
            if os.path.isfile(fpath):
                age_hours = (now - datetime.utcfromtimestamp(os.path.getmtime(fpath))).total_seconds() / 3600
                if age_hours > 24:
                    os.remove(fpath)
    except Exception:
        pass


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


        flight_date = (
            datetime.utcnow()
            .strftime("%Y-%m-%d")
        )


        wind = {"speed": None, "direction": None, "direction_cn": None, "source": "Disabled", "grid": [], "vertical_profile": []}


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

        analysis = build_analysis_payload(df, wind)


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

            analysis_nodes=analysis["nodes"],
            analysis_series=analysis["series"],
            analysis_events=analysis["events"],
            vertical_profile=analysis["vertical_profile"],

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

    app.run(

        host="0.0.0.0",

        port=int(
            os.environ.get(
                "PORT",
                5000
            )
        ),

        debug=True

    )
