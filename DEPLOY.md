# 部署上线指南 — Drone Flight Report

目标形态：

```
Internet ──► nginx (HTTPS, 443) ──► waitress (app, 8080) ──► 本地磁盘
                                                              generated/  (24h)
                                                              data/logs/  (30 天)
```

## 1. 服务器（面向海外）

- 建议选**海外/近距离地域**：香港、新加坡、日本、美西等。用户在哪就近放哪，再叠 CDN。
- 规格：2C2G 起步够用。注意每次出报告会吃一点 CPU（matplotlib/reportlab），
  风场是**出网调用**（Open-Meteo），确认服务器能访问外网。
- 不用 Docker 也能跑：纯 Python 依赖，`pip install -r requirements.txt` 即可。

## 2. 域名解析（阿里云）

你已经在阿里云买了域名，还差解析：

1. 阿里云控制台 → **云解析 DNS** → 你的域名 → **添加记录**：
   - 类型 `A`，主机记录 `@`，记录值 = 服务器**公网 IP**
   - 类型 `A`，主机记录 `www`，记录值 = 同一个 IP
2. 等待 TTL 生效（通常几分钟），本机验证：
   ```
   nslookup 你的域名
   ```
3. **备案提醒**：服务器在中国大陆节点 → 域名需 ICP 备案；选**香港/海外节点一般免备案**，
   对"面向海外"更省事。

## 3. 运行

```bash
# 开发（Flask 自带 server，仅本机调试）
python app.py

# 生产（waitress，跨平台）
pip install waitress
python wsgi.py            # 默认 0.0.0.0:8080

# 或 Docker
docker build -t drone-report .
docker run -d -p 8080:8080 --name drone-report drone-report
```

nginx 反代示例见 `deploy/nginx.conf`。

### systemd（可选，裸机）

```ini
[Unit]
Description=Drone Flight Report
After=network.target

[Service]
WorkingDirectory=/opt/drone-flight-report
Environment=PORT=8080 DEBUG=0
ExecStart=/usr/bin/python3 /opt/drone-flight-report/wsgi.py
Restart=always

[Install]
WantedBy=multi-user.target
```

## 4. HTTPS

```bash
sudo certbot --nginx -d 你的域名 -d www.你的域名
```

## 5. 环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `HOST` | `0.0.0.0` | 监听地址 |
| `PORT` | `8080`(wsgi) / `5000`(app) | 端口 |
| `DEBUG` | `0` | 只在本地调试设 `1` |
| `THREADS` | `4` | waitress 线程数 |

## 6. 上线前清单

- [ ] `DEBUG=0`，走 waitress/gunicorn（别用 Flask 自带 server 扛公网）
- [ ] 配 HTTPS（certbot）
- [ ] 加限流 / 反爬（nginx `limit_req` 或应用层）
- [ ] 确认留存策略生效：`generated/` 24h、`data/logs/` 30 天（已内置 `enforce_retention()`）
- [ ] 服务器日志**不要记录用户 IP 到飞行数据**（nginx 默认会记 access log，注意合规）
- [ ] 备份 / 监控（磁盘、出网、错误率）

## 7. 海外合规要点

- **GDPR（欧盟）/ CCPA（加州）**：站点已有 `/privacy`；正式上线前补充
  "数据控制者是谁 + 如何行使删除权"（可先留一个邮箱）。
- **数据最小化**：已经做到——原始日志处理完即删、默认不共享、共享部分去标识。
- **风数据源**：Open-Meteo 全球覆盖、免费、免 key、非美系，对"面向全球"很友好。
- **CDN**：静态资源其实很少（就一个上传页），主要瓶颈是出图；先不用急着上 CDN。
