"""
flightlog_pipeline.py — 标准化飞行日志处理流程

设计目标：把「上传的是什么格式的日志」和「怎么处理」解耦。
新增一种机型 / 格式 = 写一个 adapter + 注册一行，流程其余部分完全不动。

    parse(适配器) -> normalize(统一 schema) -> validate -> analyze -> wind -> plot -> report

当前 adapter 复用 app.py 里已验证的解析函数；下一步建议抽成独立 `flightlog/`
包，让「Web 层」和「处理管线」彻底分离。
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import app as m

# ---------------------------------------------------------------------------
# 数据契约：所有格式最终都必须落到这一套字段（canonical schema）
# ---------------------------------------------------------------------------
CANONICAL_COLUMNS = m.CANONICAL_COLUMNS

# ---------------------------------------------------------------------------
# Stage 1 — 格式适配器注册表
# 一个 adapter 的职责：path -> "raw DataFrame"（列名可以是任意原厂列名）
# ---------------------------------------------------------------------------
FORMAT_ADAPTERS = {}


def register_format(*extensions):
    """把某个解析函数绑定到一个或多个扩展名上。"""
    def decorator(fn):
        for ext in extensions:
            FORMAT_ADAPTERS[ext.lower()] = fn
        return fn
    return decorator


def supported_formats():
    return sorted(FORMAT_ADAPTERS)


def parse_any(path):
    ext = os.path.splitext(path)[1].lower()
    if ext not in FORMAT_ADAPTERS:
        raise ValueError(
            f"不支持的文件类型：{ext}；当前支持 {supported_formats()}"
        )
    return FORMAT_ADAPTERS[ext](path)


# 内置适配器（复用 app.py 已验证实现）
register_format(".csv", ".txt")(m.parse_csv_or_txt)
register_format(".bin")(m.parse_bin_log)
register_format(".ulg")(m.parse_ulg_log)


# ---------------------------------------------------------------------------
# Stage 2..N — 固定管线（与格式无关）
# ---------------------------------------------------------------------------
PIPELINE_STAGES = [
    "parse",       # 适配器 -> raw
    "normalize",   # raw -> canonical schema
    "validate",    # 结构校验
    "analyze",     # 统计
    "detect",      # 健康 / 异常筛查
    "wind",        # 区域风场
    "plot",        # 轨迹图
    "report",      # PDF
]


def run_pipeline(path, *, want_report=True):
    """对任意受支持格式跑完整流程，返回结构化结果。"""
    raw = parse_any(path)                                   # parse
    df = m.normalize_flight_data(raw)                       # normalize
    df = m.validate_flight_data(df)                         # validate
    stats = m.calculate_statistics(df)                      # analyze
    health = m.detect_flight_health(df)                     # detect
    flight_date = m.get_flight_date(df)
    wind = m.get_wind_ensemble(df, flight_date, grid_size=6)   # wind (multi-source)
    image_filename = m.generate_flight_plot(df, wind)       # plot
    image_path = os.path.join(m.GENERATED_DIR, image_filename)
    pdf_path = None
    if want_report:                                         # report
        pdf_filename = m.generate_pdf_report(df, stats, wind, image_path)
        pdf_path = os.path.join(m.GENERATED_DIR, pdf_filename)
    return {
        "points": int(len(df)),
        "stats": stats,
        "health": health,
        "flight_date": flight_date,
        "wind": wind,
        "image_path": image_path,
        "pdf_path": pdf_path,
    }


def describe():
    """给用户 / 前端看的自描述：支持什么、字段是什么、分几步。"""
    return {
        "canonical_columns": CANONICAL_COLUMNS,
        "supported_formats": supported_formats(),
        "stages": PIPELINE_STAGES,
    }


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import json

    print("== pipeline describe ==")
    print(json.dumps(describe(), ensure_ascii=False, indent=2))

    # 写一个 DJI 风格的样例 CSV
    sample = os.path.join(m.DATA_DIR, "sample_dji.csv")
    lines = ["datetime(utc),latitude,longitude,altitude(m),speed(mph),heading"]
    for i in range(30):
        import math
        ang = 2 * math.pi * i / 29
        lines.append(
            "2026-01-15 18:{:02d}:00,{:.6f},{:.6f},{:.1f},{:.1f},{:.1f}".format(
                i,
                34.0522 + 0.003 * math.sin(ang),
                -118.2437 + 0.003 * math.cos(ang),
                40 + 10 * math.sin(ang),
                5.0,
                90,
            )
        )
    with open(sample, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print("\n== run pipeline on sample CSV ==")
    result = run_pipeline(sample)
    print("points:", result["points"])
    print("distance_km:", round(result["stats"]["distance_km"], 4))
    print("health:", result["health"]["score"], result["health"]["verdict"], result["health"]["flags"])
    print("flight_date:", result["flight_date"])
    print("wind:", result["wind"]["speed"], result["wind"]["direction"], result["wind"]["source"])
    print("image:", result["image_path"])
    print("pdf:", result["pdf_path"])
    print("OK")

    # 演示「扩展一种新格式只需一行」：把 .tsv 也指向 CSV 适配器
    register_format(".tsv")(m.parse_csv_or_txt)
    print("\n== after register_format('.tsv') ==")
    print("supported_formats:", supported_formats())
