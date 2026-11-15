"""Extract flight-controller wind estimates, never measured ambient wind.

Supported sources:
  - PX4 ULog: `wind` / `estimator_wind` / legacy `wind_estimate` topics.
  - ArduPilot DataFlash: EKF `NKF2` / `XKF2` `VWN` / `VWE` components.

All values are flight-controller estimates with their boot timestamps and source.
"""

import math
from bisect import bisect_left


def _dir_from_ne(north, east):
    """气象风向（风从哪来）——度数 0-360。"""
    return (math.degrees(math.atan2(-east, -north)) + 360.0) % 360.0


def _make_sample(t_us, north, east, source, variance=None):
    if t_us is None or not all(math.isfinite(v) for v in (north, east)):
        return None
    speed = math.hypot(north, east)
    return {
        "t_us": t_us,
        "wind_north": north,
        "wind_east": east,
        "wind_speed": speed,
        "wind_dir": _dir_from_ne(north, east),
        "source": source,
        "variance": variance if variance is not None and math.isfinite(variance) and variance >= 0 else None,
    }


def extract_wind_from_ulog(path):
    """PX4 ULog: prefer current Wind topic, then legacy estimator topics."""
    from pyulog import ULog

    ulog = ULog(path)
    names = {d.name for d in ulog.data_list}
    topic = next((name for name in ("wind", "estimator_wind", "wind_estimate") if name in names), None)
    if topic is None:
        return []

    data = ulog.get_dataset(topic).data
    times = data.get("timestamp", [])

    if "windspeed_north" in data and "windspeed_east" in data:
        north = data["windspeed_north"]
        east = data["windspeed_east"]
    elif "wind_north" in data and "wind_east" in data:
        north = data["wind_north"]
        east = data["wind_east"]
    elif "windspeed_ned" in data:
        ned = data["windspeed_ned"]  # shape (n, 3)
        north = [row[0] for row in ned]
        east = [row[1] for row in ned]
    else:
        return []

    samples = []
    for i in range(min(len(north), len(east), len(times))):
        try:
            variance_fields = (data.get("variance_north"), data.get("variance_east"))
            variance = sum(float(field[i]) for field in variance_fields) if all(field is not None and i < len(field) for field in variance_fields) else None
            if variance is not None and variance <= 0:
                continue  # PX4 marks an unestimated wind variance as zero.
            sample = _make_sample(int(times[i]), float(north[i]), float(east[i]), "px4_ekf_" + topic, variance)
            if sample is not None:
                samples.append(sample)
        except (TypeError, ValueError, OverflowError):
            continue
    return samples


def extract_wind_from_bin(path):
    """ArduPilot DataFlash BIN → 风样本列表（EKF 风：NKF2/XKF2 的 VWN/VWE）。"""
    from pymavlink import DFReader

    log = DFReader.DFReader_binary(path)
    samples = []

    while True:
        msg = log.recv_match(blocking=False)
        if msg is None:
            break

        mtype = msg.get_type()
        if mtype in ("XKF2", "NKF2") and hasattr(msg, "VWN") and hasattr(msg, "VWE"):
            # One EKF core per output point; do not mix core estimates.
            core = getattr(msg, "C", 0)
            if core not in (0, None):
                continue
            t_us = getattr(msg, "TimeUS", None)
            try:
                sample = _make_sample(
                    int(t_us) if t_us is not None else None,
                    float(msg.VWN),
                    float(msg.VWE),
                    "ardupilot_ekf_%s" % mtype,
                )
                if sample is not None:
                    samples.append(sample)
            except (TypeError, ValueError, OverflowError):
                continue

    return samples


def extract_wind(path):
    """按扩展名分派。"""
    ext = path.lower().rsplit(".", 1)[-1]
    if ext == "ulg":
        return extract_wind_from_ulog(path)
    if ext in ("bin", "log"):
        return extract_wind_from_bin(path)
    raise ValueError("unsupported log type for wind extraction: .%s" % ext)


def attach_wind_estimates(frame, samples, max_gap_seconds=2.0):
    """Match EKF estimates to GPS rows on the same monotonic boot clock.

    No match is emitted outside the tolerance or when either clock is absent.
    Existing wind columns from a CSV are preserved.
    """
    if not samples or "elapsed_seconds" not in frame:
        return frame
    matched = sorted((s for s in samples if s.get("t_us") is not None), key=lambda s: s["t_us"])
    if not matched:
        return frame
    times = [s["t_us"] / 1_000_000.0 for s in matched]
    frame = frame.copy()
    for column in ("wind_speed_mps", "wind_direction_deg", "wind_source", "wind_variance_mps2"):
        if column not in frame:
            frame[column] = None
    for index, raw_time in frame["elapsed_seconds"].items():
        try:
            stamp = float(raw_time)
            if not math.isfinite(stamp):
                continue
        except (TypeError, ValueError):
            continue
        position = bisect_left(times, stamp)
        candidates = [matched[j] for j in (position - 1, position) if 0 <= j < len(matched)]
        if not candidates:
            continue
        sample = min(candidates, key=lambda s: abs(s["t_us"] / 1_000_000.0 - stamp))
        if abs(sample["t_us"] / 1_000_000.0 - stamp) > max_gap_seconds:
            continue
        if frame.at[index, "wind_speed_mps"] is not None:
            continue
        frame.at[index, "wind_speed_mps"] = sample["wind_speed"]
        frame.at[index, "wind_direction_deg"] = sample["wind_dir"]
        frame.at[index, "wind_source"] = sample["source"]
        frame.at[index, "wind_variance_mps2"] = sample["variance"]
    return frame


def summarize(samples):
    """给一批风样本一个汇总（标量均值 + 矢量平均风向）。"""
    if not samples:
        return {"n": 0, "mean_speed": None, "mean_dir": None}

    speeds = [s["wind_speed"] for s in samples]
    u = sum(-math.sin(math.radians(s["wind_dir"])) * s["wind_speed"] for s in samples)
    v = sum(-math.cos(math.radians(s["wind_dir"])) * s["wind_speed"] for s in samples)
    u /= len(samples)
    v /= len(samples)
    return {
        "n": len(samples),
        "mean_speed": sum(speeds) / len(speeds),
        "mean_dir": (math.degrees(math.atan2(-u, -v)) + 360.0) % 360.0,
    }


if __name__ == "__main__":
    import sys

    for path in sys.argv[1:]:
        samples = extract_wind(path)
        print(path, "->", summarize(samples))
        print("   first:", samples[0] if samples else None)
