# Drone Flight Report

无人机飞行日志服务（Flask）。上传日志 → 解析归一化 → 统计 → 区域风场 → 轨迹图 + PDF。
**跨厂商**（DJI CSV/TXT、ArduPilot `.bin`、PX4 `.ulg`）、**隐私优先**、浏览器免注册即可出报告。
报告内置**交互式卫星轨迹地图**：Esri 全球影像、高德中国影像，配置 `TIANDITU_KEY` 后
还可切换**天地图卫星底图（CGCS2000，与北斗/WGS-84 对齐）**。

## 快速开始

```bash
pip install -r requirements.txt
python app.py            # 默认 0.0.0.0:5000，DEBUG=0
# 本地调试： DEBUG=1 python app.py
# 冒烟测试： python test_smoke.py
```

生产用 WSGI（不要用 Flask 自带 server 扛公网）：

```bash
python wsgi.py                                  # waitress，默认 0.0.0.0:8080
# 或： waitress-serve --host 0.0.0.0 --port 8080 wsgi:app
```

Docker：

```bash
docker build -t drone-report .
docker run -d -p 8080:8080 --name drone-report drone-report
```

## 目录

| 文件 | 说明 |
|---|---|
| `app.py` | **主应用**：上传→解析→风场→绘图→PDF，含交互卫星地图 / 隐私页 / 留存策略 / 飞行健康检测 |
| `flightlog_pipeline.py` | 标准化 7 级管线（parse→normalize→validate→analyze→wind→plot→report）+ 格式适配器注册表 |
| `wind_extract.py` | 风场抽取（日志内 `wind_estimate` 优先，姿态/油门反推兜底） |
| `wsgi.py` | 生产入口（waitress） |
| `Dockerfile` / `deploy/` | Docker、nginx 反代、一条命令 `setup.sh`、上线 runbook、Windows 一键部署脚本 |
| `make_demo.py` | 生成一份 demo 报告（真实风场） |
| `test_smoke.py` / `test_normalization.py` | 端到端冒烟 + 归一化单测（CI 自动跑） |
| `STANDARDIZATION.md` | 标准化管线设计 + 数据契约 + 扩展点 |
| `NORMALIZATION.md` | 归一化 schema 说明 |
| `DEPLOY.md` | 部署上线指南（阿里云 DNS + 海外合规） |
| `.env.example` | 环境变量示例 |
| `requirements.txt` | 依赖清单 |

## 设计要点

- **统一数据契约**：所有格式先归一化成 canonical schema（`time/lat/lon/alt/speed/…`），后面统计/绘图/报告都不感知来源格式。
- **加新格式 = 一行**：在 `flightlog_pipeline.py` 的适配器注册表 `register_format(...)` 注册即可。
- **隐私**：原始日志处理完即删；生成物 24h、去标识轨迹 30 天自动清理（`/privacy` 有说明）。
- **风场**：Open-Meteo 全球覆盖、免费免 key；分层风廓线按各高度停留时间加权。

## 环境变量

见 `.env.example`：`HOST` / `PORT` / `DEBUG` / `THREADS` / `TIANDITU_KEY`（可选）。

`TIANDITU_KEY` 在 [天地图控制台](https://console.tianditu.gov.cn/) 免费申请；
填写后报告地图会多出「卫星 · 天地图（北斗 / CGCS2000）」图层，未填写则用 Esri + 高德。

## 上线前 TODO

- [ ] 上传限流 / 反爬 / 文件内容校验（目前 100MB 上限 + 扩展名）
- [ ] 风场请求加缓存 / 失败快速降级（现为同步调用）
- [ ] 可选：把纯逻辑抽成 `flightlog/` 包（见 `STANDARDIZATION.md`）
- [ ] 账号 / 机队 / 数据库（下一步产品化）
