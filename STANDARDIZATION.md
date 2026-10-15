# 标准化流程设计 — 无人机飞行日志服务

> 目标：把「什么格式的日志」和「怎么处理」解耦，让新增机型/格式 = 加一个适配器，
> 其余管线不动。这是把单机脚本变成「可对外的标准化服务」的关键。

## 一、总管线（7 级）

```
上传
 └─► [1] parse       格式适配器：原厂日志 → raw DataFrame
      └─► [2] normalize  raw → canonical schema（统一字段契约）
           └─► [3] validate  结构校验（点数/经纬度范围/时间可重建）
                └─► [4] analyze   统计（距离/时长/高度/速度）
                     └─► [5] wind      区域风场（网格矢量）
                          └─► [6] plot      轨迹图（ENU 米制）
                               └─► [7] report    PDF 报告
```

实现见 `flightlog_pipeline.py`：`run_pipeline(path)` 串起全部 7 级；
`describe()` 输出自描述（支持格式 / 字段契约 / 分级）。

## 二、数据契约（canonical schema）

任何格式，解析后**必须**映射到这套字段——这是整个标准化的"普通话"：

| 字段 | 含义 | 单位 |
|---|---|---|
| `timestamp_utc` | UTC 时间 | datetime(UTC) |
| `elapsed_seconds` | 相对起飞耗时 | s |
| `latitude` / `longitude` | 坐标 | deg (WGS84) |
| `altitude_m` | 海拔/相对高度 | m |
| `relative_altitude_m` | 相对首点高度 | m |
| `speed_mps` | 地速 | m/s |
| `heading_deg` | 航向 | deg |
| `gps_satellites` | 卫星数 | 个 |
| `gps_quality` | HDOP / fix type | - |

## 三、格式适配器注册表（扩展点）

```python
register_format(".csv", ".txt")(parse_csv_or_txt)
register_format(".bin")(parse_bin_log)   # ArduPilot DataFlash
register_format(".ulg")(parse_ulg_log)   # PX4 ULog
register_format(".tsv")(parse_csv_or_txt)  # 加一种格式＝一行
```

- 适配器的唯一职责：**path → raw DataFrame**（可以带任意原厂列名）。
- normalize 负责把原厂列名翻译成契约字段（大小写/单位/中英列名都能认）。
- 已支持：`.csv/.txt/.bin/.ulg`，注册表可动态扩展。

## 四、为什么这套能撑得起"对外服务"

1. **机队多机型**：大疆/ArduPilot/PX4 各写一个 adapter，管线与报告完全复用。
2. **可测试**：管线是纯函数链，`test_smoke.py` 不联网可跑（强制风场失败也不崩）。
3. **可演进**：以后接 ML 异常检测（见 `research/uav-flight-log-papers-2026-10-14.md`），
   只需在 `analyze` 后插一级，不动 parse/report。

## 五、建议的下一步（按投入排序）

1. **抽包**：把 app.py 里的纯逻辑抽成 `flightlog/` 包
   （`schema.py` / `adapters/` / `pipeline.py` / `report.py`），Web 层只调用管线。
2. **加一级 `detect`**：在 analyze 后插入异常/健康检测（电池 SoH、电机/ESC 漂移、GPS 异常），
   输出"机队健康评分"，对应研究里的预测性维护切口。
3. **接入认证 + 机队概念**：用户 → 机队 → 飞行记录，才有订阅价值。
4. **异步化**：管线里 wind/plot/report 目前同步跑，量大时改成任务队列。
5. **数据留存策略**：原始日志处理完即删（已做）；去标识轨迹保留期可配。
