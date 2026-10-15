# 多格式对齐 + 单位换算（Normalization）

回答你的问题：**"不同格式 → 单位换算 → 字段对齐" 做好了，而且在压缩包里。**
这一轮又补了 3 个坑：**knots 没换、1e7 经纬度没处理、数字时间戳单位没自动识别。**

## 一、支持的输入格式
- **CSV / TXT**：任意分隔符（`,` `\t` `;`）、多种编码（utf-8 / utf-8-sig / gb18030 / latin1）
- **ArduPilot DataFlash `.BIN`**
- **PX4 ULog `.ulg`**

（CSS/BIN/ULG 每条都先经过各自的解析器，再统一进下面的 schema。）

## 二、统一输出 schema（10 列，所有格式最终都长这样）
```
timestamp_utc, elapsed_seconds, latitude, longitude, altitude_m,
relative_altitude_m, speed_mps, heading_deg, gps_satellites, gps_quality
```

## 三、单位换算表

| 量 | 识别到的写法 | 换算 |
|---|---|---|
| 高度 | `...feet` / `...ft` | ÷ 3.28084 → m |
| 高度 | `...m` / `meter` | 不变 |
| 速度 | `...mph` | × 0.44704 → m/s |
| 速度 | `...kmh` / `km/h` | ÷ 3.6 → m/s |
| 速度 | `...knots` / `...kt` | × 0.514444 → m/s |
| 速度 | `...mps` / `m/s` | 不变 |
| 经纬度 | 整数 × 1e7 | ÷ 1e7 → 度 |
| 时间 | 数字（s / ms / µs / ns） | 按**数量级自动**判单位 → UTC |
| 时间 | 文本日期 | 解析为 UTC |
| 耗时 | DJI `time(millisecond)` | ÷ 1000 → 秒 |

## 四、字段识别策略
- 列名先**规范化**（去空格/符号、转小写，如 `速度 (km/h)` → `速度kmh`）。
- **先精确匹配，再子串匹配**（高度/速度/航向），提高容错。
- 覆盖 DJI AirData、ArduPilot、PX4、通用 CSV 的常见列名（中英文混排也能认）。

## 五、已验证（`test_normalization.py`，退出码 0）
4 种完全不同写法的日志，全部对齐到同一 schema 且换算正确：

| 用例 | 特征 | 校验 |
|---|---|---|
| v1 DJI 英制 | feet / mph / heading(deg) | 100ft→30.48m，10mph→4.4704m/s ✅ |
| v2 通用公制 | lat/lon/altitude_m/speed(km/h)/course | 36km/h→10m/s ✅ |
| v3 缩放整数 | gps_lat ×1e7 + 毫秒时间戳 | 340522000→34.0522 ✅ |
| v4 英尺+节 | altitude_ft / ground_speed_knots | 100ft→30.48m，10kt→5.1444m/s ✅ |

跑一遍自己看：
```bash
python test_normalization.py     # 打印每个用例的换算结果
```

## 六、还没做（诚实清单）
- 加速度（g）、电压等**非轨迹字段**没有进 canonical（目前只做飞行轨迹必需量）。
- `.tlog`（MAVLink 遥测）尚未接入——加一个 adapter 即可（见 `STANDARDIZATION.md`）。
- 高度单位除英尺/米外的少见写法（如厘米）暂未覆盖。
