"""
wind_extract.py — 从飞行日志里抽取「实测风」样本（路线 A：读日志里已有的 EKF 风估计）。

已按真实样例日志对齐字段：
  - PX4 ULog   : topic `wind_estimate` → `windspeed_north` / `windspeed_east` (m/s)
                 （兼容 3 轴 `windspeed_ned`）
  - ArduPilot  : DataFlash BIN 的 EKF 风 → `NKF2` / `XKF2` 的 `VWN` / `VWE` (m/s)

输出统一为「风样本」列表，可直接喂给网格化入库（见 WIND-DATABASE.md）。
"""

import math


def _dir_from_ne(north, east):
    """气象风向（风从哪来）——度数 0-360。"""
    return (math.degrees(math.atan2(-east, -north)) + 360.0) % 360.0


def _make_sample(t_us, north, east, source):
    speed = math.hypot(north, east)
    return {
        "t_us": t_us,
        "wind_north": north,
        "wind_east": east,
        "wind_speed": speed,
        "wind_dir": _dir_from_ne(north, east),
        "source": source,
    }


def extract_wind_from_ulog(path):
    """PX4 ULog → 风样本列表。没有 wind_estimate 主题时返回 []。"""
    from pyulog import ULog

    ulog = ULog(path)
    names = {d.name for d in ulog.data_list}
    if "wind_estimate" not in names:
        return []

    data = ulog.get_dataset("wind_estimate").data
    times = data.get("timestamp", [])

    if "windspeed_north" in data and "windspeed_east" in data:
        north = data["windspeed_north"]
        east = data["windspeed_east"]
    elif "windspeed_ned" in data:
        ned = data["windspeed_ned"]  # shape (n, 3)
        north = [row[0] for row in ned]
        east = [row[1] for row in ned]
    else:
        return []

    samples = []
    for i in range(len(north)):
        t_us = int(times[i]) if i < len(times) else None
        samples.append(
            _make_sample(t_us, float(north[i]), float(east[i]), "px4_wind_estimate")
        )
    return samples


def extract_wind_from_bin(path):
    """ArduPilot DataFlash BIN → 风样本列表（EKF 风：NKF2/XKF2 的 VWN/VWE）。"""
    from pymavlink import DFReader

    log = DFReader.DFReader_binary(path)
    samples = []
    seen_types = set()

    while True:
        msg = log.recv_match(blocking=False)
        if msg is None:
            break

        if hasattr(msg, "VWN") and hasattr(msg, "VWE"):
            mtype = msg.get_type()
            seen_types.add(mtype)
            t_us = getattr(msg, "TimeUS", None)
            samples.append(
                _make_sample(
                    int(t_us) if t_us is not None else None,
                    float(msg.VWN),
                    float(msg.VWE),
                    "ardupilot_ekf_%s" % mtype,
                )
            )

    return samples


def extract_wind(path):
    """按扩展名分派。"""
    ext = path.lower().rsplit(".", 1)[-1]
    if ext == "ulg":
        return extract_wind_from_ulog(path)
    if ext in ("bin", "log"):
        return extract_wind_from_bin(path)
    raise ValueError("unsupported log type for wind extraction: .%s" % ext)


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
