# 海外上线清单（30 分钟）— Drone Flight Report

前提：域名已在阿里云买好；服务器还没有。
目标：把服务跑到**海外**，用你的域名 HTTPS 访问。

---

## 0. 买服务器（今天，10 分钟）

**首选：阿里云 · 轻量应用服务器 · 中国香港**
- 地域：**中国香港**（免备案、离大陆近、亚洲访问快）
- 镜像：系统镜像 → **Ubuntu 22.04**
- 规格：**2核 2G / 40G ESSD / 带宽 3~5Mbps** 起（出图吃一点 CPU）
- 时长：先买 **1 个月**试水，能动再说
- 买完在「实例详情」记下 **公网 IP**

**同等备选（都免备案）**
- Vultr：东京 / 新加坡，$6/月起，**按小时计费**、随时删，适合试
- 腾讯云轻量 · 香港；DigitalOcean；Hetzner（欧洲最便宜）
- 想要更贴大陆用户：阿里云/腾讯云 香港或新加坡

❌ **别选中国大陆地域** —— 绑域名要 ICP 备案，几天起步，且你面向海外没必要。

---

## 1. 放行端口（安全组 / 防火墙）
在阿里云控制台该实例的**防火墙 / 安全组**里放行：`22`(SSH)、`80`(HTTP)、`443`(HTTPS)。

---

## 2. 域名解析（阿里云「云解析 DNS」，5 分钟）
在你的域名下添加两条记录：

- 类型 `A`，主机记录 `@`，记录值 = **服务器公网 IP**
- 类型 `A`，主机记录 `www`，记录值 = **同一个 IP**

本机验证：`nslookup 你的域名`

> 可选更稳（面向海外）：把域名 **NS 换成 Cloudflare 免费版**，海外解析更稳，顺带 CDN/DDoS。

---

## 3. 上传代码（3 分钟）
在你电脑上（`projects/drone-flight-report` 旁）：

```bash
scp drone-flight-report.zip root@服务器IP:/opt/
ssh root@服务器IP
cd /opt && apt-get install -y unzip && unzip -o drone-flight-report.zip && cd drone-flight-report
```

---

## 4. 一键部署（3 分钟）
在服务器上、**项目目录内**执行：

```bash
DOMAIN=你的域名 EMAIL=你的邮箱 bash deploy/setup.sh
```

脚本会：装 python/nginx/certbot → 建 venv 装依赖 → systemd 服务(waitress:8080) → nginx 反代 → 申请 HTTPS。

---

## 5. 验证
- 浏览器开 `https://你的域名`
- `https://你的域名/health` → `{"status":"ok"}`
- 点 **Try Demo** 跑一遍，再真上传一个日志试

常用：日志 `journalctl -u drone-report -f`；更新 `git pull && systemctl restart drone-report`

---

## 6. 上线前最后检查
- [ ] `DEBUG=0`（脚本已默认）
- [ ] HTTPS 生效（certbot）
- [ ] 留存策略在跑：`generated/` 24h、`data/logs/` 30 天
- [ ] nginx access log 合规（别把 IP 和飞行数据关联）
- [ ] 加限流（nginx `limit_req`）防止被刷

---

## 附：暂时没服务器也能先给人看
本机 `python wsgi.py`，再开 Cloudflare Tunnel：
`cloudflared tunnel --url http://localhost:8080` → 秒得一个 `https://xxx.trycloudflare.com`。
适合先发帖/发朋友圈验证需求，正式上线仍走上面 6 步。
