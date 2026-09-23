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

        Drone Flight Report

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


# =========================================================
# Field name normalization
# =========================================================

def normalize_column_name(name):
    """
    Convert different column names into
    a comparable normalized form.

    Examples:

        Latitude
        latitude
        LAT
        latitude_deg
        latitude (deg)

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


# =========================================================
# Candidate field names
# =========================================================

LAT_NAMES = {
    "lat",
    "latitude",
    "latitude_deg",
    "latdeg",
    "gpslat",
    "gpslatitude",
    "latitudedeg",
}

LON_NAMES = {
    "lon",
    "lng",
    "longitude",
    "longitude_deg",
    "londeg",
    "lngdeg",
    "gpslon",
    "gpslng",
    "gpslongitude",
    "longitudedeg",
}

ALT_NAMES = {
    "alt",
    "altitude",
    "altitude_m",
    "altitudem",
    "alt_m",
    "altm",
    "gpsalt",
    "gpsaltitude",
    "relativealtitude",
    "absolutealtitude",
    "height",
    "heightm",
}

TIME_NAMES = {
    "time",
    "timestamp",
    "datetime",
    "date",
    "gps_time",
    "gpstime",
    "timeutc",
    "utctime",
}


# =========================================================
# Find column
# =========================================================

def find_column(df, candidates):

    normalized = {}

    for col in df.columns:

        normalized[
            normalize_column_name(col)
        ] = col


    # Exact match first
    for candidate in candidates:

        candidate_norm = normalize_column_name(
            candidate
        )

        if candidate_norm in normalized:

            return normalized[candidate_norm]


    # Substring fallback
    for norm_name, original_name in normalized.items():

        for candidate in candidates:

            candidate_norm = normalize_column_name(
                candidate
            )

            if (
                candidate_norm in norm_name
                or norm_name in candidate_norm
            ):

                return original_name


    return None


# =========================================================
# Find GPS / altitude / time fields
# =========================================================

def find_lat_lon_alt_time(df):

    lat_col = find_column(
        df,
        LAT_NAMES
    )

    lon_col = find_column(
        df,
        LON_NAMES
    )

    alt_col = find_column(
        df,
        ALT_NAMES
    )

    time_col = find_column(
        df,
        TIME_NAMES
    )

    return (
        lat_col,
        lon_col,
        alt_col,
        time_col
    )


# =========================================================
# CSV / TXT parser
# =========================================================

def parse_csv_or_txt(path):

    errors = []

    encodings = [
        "utf-8",
        "utf-8-sig",
        "latin1",
        "cp1252",
    ]


    for encoding in encodings:

        try:

            df = pd.read_csv(
                path,
                encoding=encoding,
                sep=None,
                engine="python"
            )

            if len(df.columns) > 1:

                return df

        except Exception as exc:

            errors.append(str(exc))


    separators = [
        ",",
        "\t",
        ";",
        r"\s+",
    ]


    for encoding in encodings:

        for sep in separators:

            try:

                df = pd.read_csv(
                    path,
                    encoding=encoding,
                    sep=sep,
                    engine="python"
                )

                if len(df.columns) > 1:

                    return df

            except Exception as exc:

                errors.append(str(exc))


    raise ValueError(
        "Unable to read CSV/TXT file. "
        "Please check the file format."
    )
# =========================================================
# BIN parser
# =========================================================

def parse_bin_log(path):

    master = mavutil.mavlink_connection(
        path
    )

    rows = []


    while True:

        msg = master.recv_match(
            type="GLOBAL_POSITION_INT",
            blocking=False
        )

        if msg is None:
            break


        try:

            lat = float(msg.lat) / 1e7
            lon = float(msg.lon) / 1e7

            # GLOBAL_POSITION_INT:
            # relative_alt is millimeters
            alt = float(msg.relative_alt) / 1000.0

        except Exception:

            continue


        # Ignore invalid GPS
        if (
            not math.isfinite(lat)
            or not math.isfinite(lon)
        ):
            continue


        if (
            abs(lat) > 90
            or abs(lon) > 180
        ):
            continue


        if lat == 0 and lon == 0:
            continue


        timestamp = None

        try:

            if hasattr(msg, "_timestamp"):

                timestamp = msg._timestamp

        except Exception:

            timestamp = None


        rows.append({
            "latitude": lat,
            "longitude": lon,
            "altitude": alt,
            "timestamp": timestamp,
        })


    if not rows:

        raise ValueError(
            "BIN file was read, but no valid "
            "GLOBAL_POSITION_INT GPS records "
            "were found."
        )


    return pd.DataFrame(rows)


# =========================================================
# ULG parser
# =========================================================

def parse_ulg_log(path):

    ulg = ULog(path)

    dataset_names = {
        d.name
        for d in ulg.data_list
    }


    if "vehicle_gps_position" not in dataset_names:

        raise ValueError(
            "ULG file does not contain "
            "vehicle_gps_position."
        )


    data = ulg.get_dataset(
        "vehicle_gps_position"
    ).data


    columns = set(data.keys())


    # Latitude
    if "lat" not in columns:

        raise ValueError(
            "ULG vehicle_gps_position "
            "does not contain latitude."
        )


    # Longitude
    if "lon" not in columns:

        raise ValueError(
            "ULG vehicle_gps_position "
            "does not contain longitude."
        )


    result = pd.DataFrame()


    result["latitude"] = pd.to_numeric(
        data["lat"],
        errors="coerce"
    ) / 1e7


    result["longitude"] = pd.to_numeric(
        data["lon"],
        errors="coerce"
    ) / 1e7


    # -----------------------------------------------------
    # Altitude
    # -----------------------------------------------------

    altitude_column = None

    for name in [
        "alt",
        "alt_ellipsoid",
    ]:

        if name in columns:

            altitude_column = name
            break


    if altitude_column is not None:

        result["altitude"] = pd.to_numeric(
            data[altitude_column],
            errors="coerce"
        )

    else:

        result["altitude"] = float("nan")


    # -----------------------------------------------------
    # Timestamp
    # -----------------------------------------------------

    if "timestamp" in columns:

        result["timestamp"] = data[
            "timestamp"
        ]

    elif "timestamp_sample" in columns:

        result["timestamp"] = data[
            "timestamp_sample"
        ]

    else:

        result["timestamp"] = None


    return result


# =========================================================
# Normalize flight data
# =========================================================

def normalize_flight_data(df):

    if df is None or len(df) == 0:

        raise ValueError(
            "Flight log contains no data."
        )


    (
        lat_col,
        lon_col,
        alt_col,
        time_col
    ) = find_lat_lon_alt_time(df)


    if lat_col is None:

        raise ValueError(
            "Latitude field was not detected. "
            "Supported examples include: "
            "lat, latitude, latitude_deg, GPSLat."
        )


    if lon_col is None:

        raise ValueError(
            "Longitude field was not detected. "
            "Supported examples include: "
            "lon, lng, longitude, longitude_deg."
        )


    result = pd.DataFrame()


    result["latitude"] = pd.to_numeric(
        df[lat_col],
        errors="coerce"
    )


    result["longitude"] = pd.to_numeric(
        df[lon_col],
        errors="coerce"
    )


    # -----------------------------------------------------
    # Automatic altitude detection
    # -----------------------------------------------------

    if alt_col is not None:

        result["altitude"] = pd.to_numeric(
            df[alt_col],
            errors="coerce"
        )

    else:

        result["altitude"] = float("nan")


    # -----------------------------------------------------
    # Automatic time detection
    # -----------------------------------------------------

    if time_col is not None:

        result["timestamp"] = df[
            time_col
        ]

    else:

        result["timestamp"] = None


    # -----------------------------------------------------
    # Remove invalid GPS rows
    # -----------------------------------------------------

    result = result.dropna(
        subset=[
            "latitude",
            "longitude"
        ]
    ).copy()


    result = result[
        result["latitude"].between(
            -90,
            90
        )
        &
        result["longitude"].between(
            -180,
            180
        )
    ]


    result = result[
        ~(
            (result["latitude"] == 0)
            &
            (result["longitude"] == 0)
        )
    ]


    result = result.reset_index(
        drop=True
    )


    if len(result) < 2:

        raise ValueError(
            "Not enough valid GPS points "
            "were found in the flight log."
        )


    return result


# =========================================================
# Main parser
# =========================================================

def parse_flight_log(path):

    extension = (
        os.path.splitext(path)[1]
        .lower()
    )


    if extension in [
        ".csv",
        ".txt",
    ]:

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
        "Unsupported file type. "
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
            df.iloc[i - 1]["latitude"],
            df.iloc[i - 1]["longitude"],
            df.iloc[i]["latitude"],
            df.iloc[i]["longitude"],
        )


    return total


def calculate_statistics(df):

    distance_m = calculate_distance(
        df
    )


    altitude = pd.to_numeric(
        df["altitude"],
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

        lat_pad = max(lat_span * 0.6, 0.005)
        lon_pad = max(lon_span * 0.6, 0.005)

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
            "speed": 0,
            "direction": 0,
            "source": "Unavailable",
            "grid": [],
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


    c.save()


    return filename


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

            "longitude":
                lon,

            "altitude":
                altitude,

            "timestamp":
                None,
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

    <h2>Wind Reference</h2>


    {% if wind.speed is not none %}

        <p>

            Wind speed:
            <strong>
                {{ "%.1f"|format(wind.speed) }}
                km/h
            </strong>

        </p >


        {% if wind.direction is not none %}

            <p>

                Wind direction:
                <strong>
                    {{ "%.0f"|format(wind.direction) }}°
                </strong>

            </p >

        {% endif %}


        <p class="small">

            Source:
            {{ wind.source }}

        </p >

    {% else %}

        <p>
            Wind data unavailable.
        </p >

    {% endif %}

</div>


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


        # -------------------------------------------------
        # Wind
        # -------------------------------------------------

        first_lat = float(
            df.iloc[0]["latitude"]
        )


        first_lon = float(
            df.iloc[0]["longitude"]
        )


        wind = get_wind_field(
            df,
            flight_date,
            grid_size=9
        )
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
        download_name=filename,
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


        wind = get_wind_data(

            float(
                df.iloc[0]["latitude"]
            ),

            float(
                df.iloc[0]["longitude"]
            ),

            flight_date

        )


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
