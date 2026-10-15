# 最快上线路径（LAUNCH）— 15~30 分钟

目标：让「上传日志 → 出报告」这个免费工具**今天就能对外访问**。
（风数据库是第二步，别挡上线。先上线、先引流。）

---

## 你需要准备
- 一台 **VPS**（推荐 Ubuntu 22.04，海外地域如**香港/新加坡**，免备案）。记下**公网 IP**。
- 一个**域名**（你阿里云买了的那个）。

## 第 0 步 · 先本地确认能跑（可选，1 分钟）
```bash
pip install -r requirements.txt
python wsgi.py        # 打开 http://本机IP:8080 看首页
```

## 第 1 步 · 域名解析（阿里云，5 分钟）
阿里云控制台 → **云解析 DNS** → 你的域名 → 添加记录：
| 类型 | 主机记录 | 记录值 |
|---|---|---|
| A | `@` | 服务器公网 IP |
| A | `www` | 服务器公网 IP |

等几分钟，本机验证：`nslookup 你的域名`

## 第 2 步 · 把代码放上服务器（3 分钟）
```bash
ssh root@你的服务器IP
# 方式 A：从 GitHub
git clone https://github.com/你的用户名/drone-flight-report.git
cd drone-flight-report
# 方式 B：没有 GitHub，就 scp 上传 drone-flight-report.zip 再解压
```

## 第 3 步 · 一键部署（3 分钟）
```bash
DOMAIN=你的域名 EMAIL=你的邮箱 bash deploy/setup.sh
```
这个脚本会自动：装 python/nginx/certbot → 建 venv 装依赖 → 装 systemd 服务(waitress:8080)
→ 配 nginx 反代 → 申请 HTTPS 证书。

## 第 4 步 · 验证
- 浏览器打开 `https://你的域名`
- `/health` 返回 `{"status":"ok"}`
- 点 **Try Demo** 走一遍，再真上传一个日志试试

## 就绪后
- 日志：`journalctl -u drone-report -f`
- 更新：`cd /opt/drone-flight-report && git pull && systemctl restart drone-report`

## 常见坑
- **certbot 失败**：多半是域名还没解析到这台机 → 先 `nslookup` 确认，再重跑
  `certbot --nginx -d 你的域名 -d www.你的域名`
- **大陆节点要备案**：想省事就选香港/海外节点
- **出网**：风场要访问 Open-Meteo/NASA，确认服务器能出网
- **DEBUG**：生产保持 `DEBUG=0`（脚本已默认）

## 最快「先给别人看」的备选（没有服务器时）
本机 `python wsgi.py`，用内网穿透（Cloudflare Tunnel / ngrok）临时给个公网地址演示——
但**正式上线还是走上面 4 步**。
