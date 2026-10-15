# 一键：Windows 本地 -> 海外服务器 上传并部署
# 用法（在 drone-flight-report.zip 所在目录打开 PowerShell）：
#   .\deploy-from-windows.ps1 -ServerIp 1.2.3.4 -Domain example.com -Email me@example.com
# 需要本机已装 OpenSSH 客户端（Win10/11 默认自带 ssh / scp）。
# 首次连接会提示确认指纹并输入服务器密码。

param(
    [Parameter(Mandatory=$true)][string]$ServerIp,
    [Parameter(Mandatory=$true)][string]$Domain,
    [Parameter(Mandatory=$true)][string]$Email,
    [string]$User = "root",
    [string]$ZipPath = "drone-flight-report.zip"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $ZipPath)) {
    throw "找不到 $ZipPath —— 请在 drone-flight-report.zip 所在目录运行本脚本。"
}

Write-Host "==> [1/3] 上传代码到 $User@$ServerIp" -ForegroundColor Cyan
scp $ZipPath "${User}@${ServerIp}:/opt/"

Write-Host "==> [2/3] 服务器上解压" -ForegroundColor Cyan
ssh "${User}@${ServerIp}" "apt-get update -y >/dev/null 2>&1; apt-get install -y unzip >/dev/null 2>&1; cd /opt && unzip -o drone-flight-report.zip -d drone-flight-report >/dev/null && echo OK"

Write-Host "==> [3/3] 一键部署（装依赖 + nginx + HTTPS）" -ForegroundColor Cyan
ssh "${User}@${ServerIp}" "cd /opt/drone-flight-report && DOMAIN=$Domain EMAIL=$Email bash deploy/setup.sh"

Write-Host ""
Write-Host "==== 完成 ====" -ForegroundColor Green
Write-Host "打开： https://$Domain     健康检查： https://$Domain/health"
Write-Host "提醒：域名要先解析到 $ServerIp，且安全组放行 22/80/443。"
