# DroneFlightLog
无人机飞行日志双模式工具：离线本地记录+飞控日志解析，支持ArduPilot .bin/.csv格式，生成可视化报告

## 功能
1. **离线日志**：单HTML文件，手机/电脑直接打开，记录SN/飞行员/地点/时间，导出PDF/JSON
2. **日志解析**：上传.bin/.csv飞控日志，自动生成航线/高度/电池图表，导出多格式报告
3. **预留功能**：风场估计算法模块，后续支持农业无人机风速解算

## 快速使用
### 离线模式
双击 `offline-log.html` 直接运行，无需安装

### 解析模式
1. 安装依赖：`pip install -r requirements.txt`
2. 启动服务：`python web_server/app.py`
3. 访问：http://localhost:5000

## 开源协议
MIT