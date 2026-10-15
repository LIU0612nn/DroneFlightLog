import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import app as m

print("import OK")

# 1. demo data + stats + validation
df = m.create_demo_flight()
print("demo rows:", len(df), "| cols:", list(df.columns))
m.validate_flight_data(df)
stats = m.calculate_statistics(df)
print("stats:", {k: stats[k] for k in ("points", "distance_km", "max_altitude")})
health = m.detect_flight_health(df)
print("health:", health["score"], health["verdict"], health["flags"])

# 2. wind must degrade to None (not 0) when network fails
def boom(*a, **k):
    raise RuntimeError("no network in test")

m.requests.get = boom
w = m.get_wind_field(df, m.get_flight_date(df), grid_size=4)
print("wind on failure -> speed:", w["speed"], "| direction:", w["direction"], "| source:", w["source"])

# 3. plot must not crash on unavailable wind
img = m.generate_flight_plot(df, w)
print("plot file:", img)

# 4. CSV parse path (DJI-like column names)
csv = "datetime(utc),latitude,longitude,altitude(m),speed(mph),heading\n"
for i in range(5):
    csv += "2026-01-15 18:0{}:00,34.0522,{},{},5.0,90\n".format(
        i, -118.2437 + i * 0.0001, 40 + i
    )
tmp = os.path.join(HERE, "data", "_smoke.csv")
with open(tmp, "w", encoding="utf-8") as f:
    f.write(csv)
parsed = m.parse_flight_log(tmp)
print("csv parsed rows:", len(parsed), "| speed_mps[0]:", round(float(parsed["speed_mps"].iloc[0]), 4))

# 5. Flask test client: health, home, full upload flow
client = m.app.test_client()
r = client.get("/health")
print("/health ->", r.status_code, r.get_json())
r = client.get("/")
print("/ ->", r.status_code, "| bytes:", len(r.data))
with open(tmp, "rb") as fh:
    r = client.post("/", data={"file": (fh, "_smoke.csv")}, content_type="multipart/form-data")
print("POST / ->", r.status_code, "| bytes:", len(r.data), "| 'Wind data unavailable' shown:", b"Wind data unavailable" in r.data)

# 6. retention + privacy page
m.enforce_retention()
print("enforce_retention OK")
r = client.get("/privacy")
print("/privacy ->", r.status_code, "| bytes:", len(r.data))
print("ALL SMOKE TESTS PASSED")
