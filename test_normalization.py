"""多格式「单位换算 + 字段对齐」测试：4 种不同写法的日志 → 同一套 canonical schema。"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import app as m

CANON = [
    "timestamp_utc", "elapsed_seconds", "latitude", "longitude",
    "altitude_m", "relative_altitude_m", "speed_mps",
    "heading_deg", "gps_satellites", "gps_quality",
]


def run(name, text, checks):
    path = os.path.join(tempfile.gettempdir(), name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    df = m.parse_flight_log(path)
    cols_ok = list(df.columns) == CANON
    print("== %s ==  columns_ok=%s  rows=%d" % (name, cols_ok, len(df)))
    if not cols_ok:
        FAILS.append(name + " columns")
    print("   lat0=%.6f lon0=%.6f alt0=%.3f m  speed0=%.4f m/s  ts0=%s" % (
        df["latitude"].iloc[0], df["longitude"].iloc[0], df["altitude_m"].iloc[0],
        df["speed_mps"].iloc[0], df["timestamp_utc"].iloc[0]))
    for label, got, want in checks(df):
        ok = abs(got - want) < 1e-3
        if not ok:
            FAILS.append(name + " " + label)
        print("   %-26s got=%-12.4f want=%-12.4f %s" % (
            label, got, want, "OK" if ok else "FAIL"))


FAILS = []


# 1) DJI-AirData 风格，英制：feet / mph / heading(deg)
v1 = "datetime(utc),latitude,longitude,height_above_takeoff(feet),speed(mph),heading(deg),satellites,hdop\n"
v1 += "2026-01-15 18:00:00,34.0522,-118.2437,100,10,90,12,0.8\n"
v1 += "2026-01-15 18:00:01,34.0523,-118.2436,110,12,91,12,0.8\n"
run("v1_dji_imperial.csv", v1, lambda d: [
    ("altitude 100ft->m", float(d["altitude_m"].iloc[0]), 100 / 3.28084),
    ("speed 10mph->m/s", float(d["speed_mps"].iloc[0]), 10 * 0.44704),
])

# 2) 通用公制，列名不同：lat / lon / altitude_m / speed(km/h) / course
v2 = "datetime,lat,lon,altitude_m,speed(km/h),course,satellites\n"
v2 += "2026-01-15T18:00:00Z,34.0522,-118.2437,40,36,180,14\n"
v2 += "2026-01-15T18:00:01Z,34.0523,-118.2436,45,36,181,14\n"
run("v2_generic_metric.csv", v2, lambda d: [
    ("speed 36km/h->m/s", float(d["speed_mps"].iloc[0]), 10.0),
    ("altitude 40m", float(d["altitude_m"].iloc[0]), 40.0),
])

# 3) 1e7 整数经纬度 + 毫秒时间戳
v3 = "datetime,gps_lat,gps_lon,altitude\n"
v3 += "1768500000000,340522000,-1182437000,40\n"
v3 += "1768500001000,340523000,-1182436000,42\n"
run("v3_scaled_int_epoch.csv", v3, lambda d: [
    ("lat 340522000/1e7", float(d["latitude"].iloc[0]), 34.0522),
    ("lon -1182437000/1e7", float(d["longitude"].iloc[0]), -118.2437),
])

# 4) 英制高度 + 节：altitude_ft / ground_speed_knots
v4 = "gps_lat,gps_lon,altitude_ft,ground_speed_knots\n"
v4 += "34.0522,-118.2437,100,10\n"
v4 += "34.0523,-118.2436,110,10\n"
run("v4_feet_knots.csv", v4, lambda d: [
    ("altitude 100ft->m", float(d["altitude_m"].iloc[0]), 100 / 3.28084),
    ("speed 10kt->m/s", float(d["speed_mps"].iloc[0]), 10 * 0.514444),
])

print("DONE")
sys.exit(1 if FAILS else 0)
