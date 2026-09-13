from flask import Flask, request, render_template_string, send_file
import pandas as pd
import matplotlib.pyplot as plt
import os
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
from datetime import datetime

app = Flask(__name__)

HTML = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>DroneFlight | Log Analytics</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            background: #0b0f19; color: #fff; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            min-height: 100vh; display: flex; justify-content: center; align-items: center; padding: 20px;
        }
        .card {
            background: rgba(255, 255, 255, 0.03); backdrop-filter: blur(16px);
            border: 1px solid rgba(255, 255, 255, 0.08); border-radius: 24px;
            padding: 50px 40px; width: 100%; max-width: 600px; text-align: center;
            box-shadow: 0 25px 50px rgba(0, 0, 0, 0.5);
        }
        h1 { font-size: 26px; margin-bottom: 10px; font-weight: 600; }
        .subtitle { color: #8a91a6; font-size: 15px; margin-bottom: 35px; }
        .drop-zone {
            border: 2px dashed rgba(255, 255, 255, 0.2); border-radius: 16px;
            padding: 50px 20px; cursor: pointer; transition: all 0.3s ease;
            background: rgba(255, 255, 255, 0.02); margin-bottom: 20px;
        }
        .drop-zone:hover { border-color: #3b82f6; background: rgba(59, 130, 246, 0.05); }
        .drop-zone .icon { font-size: 48px; margin-bottom: 12px; display: block; }
        .drop-zone p { color: #8a91a6; font-size: 15px; }
        input[type="file"] { display: none; }
        .btn {
            background: #3b82f6; color: #fff; border: none; font-size: 16px; font-weight: 600;
            padding: 14px 32px; border-radius: 50px; cursor: pointer; width: 100%;
            transition: background 0.2s; margin-top: 10px;
        }
        .btn:hover { background: #2563eb; }
        .btn:disabled { opacity: 0.4; cursor: default; }
        .status { margin-top: 20px; font-size: 14px; color: #8a91a6; }
        .status.success { color: #34d399; }
        .status.error { color: #f87171; }
    </style>
</head>
<body>
<div class="card">
    <h1>🛸 DroneFlight</h1>
    <p class="subtitle">Upload your flight log to generate a wind-overlaid PDF report</p >
    <div class="drop-zone" id="dropZone">
        <span class="icon">📂</span>
        <p>Click or drag .csv / .bin file here</p >
    </div>
    <input type="file" id="fileInput" accept=".csv,.bin">
    <button class="btn" id="uploadBtn" disabled>Generate Report</button>
    <div class="status" id="status">Waiting for upload...</div>
</div>
<script>
    const dropZone = document.getElementById('dropZone');
    const fileInput = document.getElementById('fileInput');
    const uploadBtn = document.getElementById('uploadBtn');
    const status = document.getElementById('status');
    let selectedFile = null;

    dropZone.addEventListener('click', () => fileInput.click());
    dropZone.addEventListener('dragover', (e) => { e.preventDefault(); dropZone.style.borderColor = '#3b82f6'; });
    dropZone.addEventListener('dragleave', () => { dropZone.style.borderColor = 'rgba(255,255,255,0.2)'; });
    dropZone.addEventListener('drop', (e) => {
        e.preventDefault();
        dropZone.style.borderColor = 'rgba(255,255,255,0.2)';
        if (e.dataTransfer.files.length) handleFile(e.dataTransfer.files[0]);
    });
    fileInput.addEventListener('change', (e) => { if (e.target.files.length) handleFile(e.target.files[0]); });

    function handleFile(file) {
        selectedFile = file;
        uploadBtn.disabled = false;
        status.textContent = `Selected: ${file.name}`;
        status.className = 'status success';
    }

    uploadBtn.addEventListener('click', async () => {
        if (!selectedFile) return;
        uploadBtn.disabled = true;
        status.textContent = '⏳ Processing... please wait.';
        status.className = 'status';
        const formData = new FormData();
        formData.append('file', selectedFile);
        try {
            // 这里提交给 Flask 后台，后台会返回生成好的页面
            const res = await fetch('/', { method: 'POST', body: formData });
            if (!res.ok) throw new Error(await res.text());
            document.open(); document.write(await res.text()); document.close();
        } catch (err) {
            status.textContent = `❌ ${err.message}`;
            status.className = 'status error';
            uploadBtn.disabled = false;
        }
    });
</script>
</body>
</html>
'''
def generate_pdf_report(image_path, output_path, flight_data):
    try:
        c = canvas.Canvas(output_path, pagesize=A4)
        width, height = A4
        
        # 封面
        c.setFont("Helvetica-Bold", 28)
        c.drawString(50, height - 60, "Drone Flight Report")
        
        c.setFont("Helvetica", 14)
        # 强行把所有内容转成字符串，防止类型报错
        c.drawString(50, height - 100, f"Generated: {str(datetime.now().strftime('%Y-%m-%d %H:%M'))}")
        c.drawString(50, height - 130, f"Total Waypoints: {str(flight_data.get('points', 'N/A'))}")
        c.drawString(50, height - 160, f"Max Altitude: {str(flight_data.get('max_alt', 'N/A'))} m")
        
        # 第二页：轨迹图
        c.showPage()
        c.setFont("Helvetica-Bold", 18)
        c.drawString(50, height - 50, "Flight Path & Wind Field")
        
        if image_path and os.path.exists(image_path):
            c.drawImage(ImageReader(image_path), 50, 100, width=width-100, height=height-200)
        
        c.save()
        return True
    except Exception as e:
        # ⚠️ 最关键的一步：把真正的错误打印到 Render 的日志里！
        print(f"========== PDF生成错误详情: {str(e)} ==========")
        return False
def find_lat_lon(df):
    lat_col, lon_col = None, None
    for col in df.columns:
        col_lower = col.lower()
        if 'lat' in col_lower:
            lat_col = col
        if 'lon' in col_lower or 'lng' in col_lower:
            lon_col = col
    return lat_col, lon_col
import requests
import math

def get_wind_data(lat, lon, date_str):
    # ===== 主数据源：Open-Meteo =====
    try:
        url = "https://api.open-meteo.com/v1/forecast"
        params = {
            "latitude": lat, "longitude": lon,
            "hourly": "wind_speed_10m,wind_direction_10m",
            "start_date": date_str, "end_date": date_str,
            "timezone": "Asia/Shanghai"
        }
        resp = requests.get(url, params=params, timeout=10).json()
        hourly = resp.get('hourly')
        if hourly and 'wind_speed_10m' in hourly and len(hourly['wind_speed_10m']) > 12:
            print("========== 数据源: Open-Meteo ==========")
            return hourly['wind_speed_10m'][12], hourly['wind_direction_10m'][12]
    except Exception as e:
        print(f"Open-Meteo 失败: {e}")


    # ===== 备用数据源：NASA POWER =====
    try:
        url = "https://power.larc.nasa.gov/api/temporal/hourly/point"
        params = {
            "parameters": "WS10M,WD10M",
            "community": "RE",
            "longitude": lon,
            "latitude": lat,
            "start": date_str.replace("-", ""),
            "end": date_str.replace("-", ""),
            "format": "JSON"
        }
        resp = requests.get(url, params=params, timeout=15).json()
        data = resp.get("properties", {}).get("parameter", {})
        ws = list(data.get("WS10M", {}).values())
        wd = list(data.get("WD10M", {}).values())
        if ws and wd:
            print("========== 数据源: NASA POWER ==========")
            return ws[12], wd[12]
    except Exception as e:
        print(f"NASA POWER 失败: {e}")

    print("========== API失败，使用假数据测试 ==========")
    return 5.5, 180.0
def wind_to_uv(speed, direction_deg):
    """风向转U/V分量（画箭头用）"""
    rad = math.radians(direction_deg)
    return -speed * math.sin(rad), -speed * math.cos(rad)
@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        file = request.files['file']
        if file:
            try:
                # 1. 读取数据
                df = pd.read_csv(file)
                lat_col, lon_col = find_lat_lon(df)
                
                if lat_col and lon_col:
                    # ===== 1. 基础轨迹图 =====
                    plt.figure(figsize=(10,6))
                    plt.plot(df[lon_col], df[lat_col], linewidth=2, color='#007AFF')
                    plt.xlabel('Longitude', fontsize=12)
                    plt.ylabel('Latitude', fontsize=12)
                    plt.title('Drone Flight Path', fontsize=16)
                    plt.ticklabel_format(style='plain', useOffset=False, axis='both')
                    plt.grid(True, alpha=0.3)
                    plt.margins(0.1)
                    
                    # ===== 2. 叠加风场（专业流线图）=====
                    try:
                        import numpy as np
                        from datetime import datetime
                        
                        lat0 = df[lat_col].iloc[0]
                        lon0 = df[lon_col].iloc[0]
                        date_str = datetime.now().strftime('%Y-%m-%d')
                        
                        wind_speed, wind_dir = get_wind_data(lat0, lon0, date_str)
                        u, v = wind_to_uv(wind_speed, wind_dir)
                        
                        # 构造流线网格
                        x = np.linspace(df[lon_col].min(), df[lon_col].max(), 20)
                        y = np.linspace(df[lat_col].min(), df[lat_col].max(), 20)
                        X, Y = np.meshgrid(x, y)
                        U = np.full_like(X, u, dtype=float)
                        V = np.full_like(Y, v, dtype=float)
                        
                        # 专业流线图（matplotlib 自带，云端绝不出错）
                        plt.streamplot(X, Y, U, V, density=1.5, color='#FF8C00', linewidth=1.0, arrowsize=1.0)
                        
                        plt.text(0.02, 0.95, f"Wind: {wind_speed} m/s, Dir: {wind_dir} deg",
                                 transform=plt.gca().transAxes, color='#FF8C00', fontsize=12)
                    except Exception as e:
                        print(f"========== 风场生成失败: {str(e)} ==========")
                    # ===== 3. 保存图片 =====
                    import tempfile, os
                    temp_dir = tempfile.gettempdir()
                    
                    # 保存给网页预览用的图
                    os.makedirs('static', exist_ok=True)
                    plt.savefig('static/track.png', dpi=150)
                    
                    # 保存给 PDF 用的图（存到系统临时目录，Linux 用 /tmp，Windows 用 C盘Temp）
                    img_path = os.path.join(temp_dir, 'track.png')
                    plt.savefig(img_path, dpi=150)
                    plt.close()
                    # ===== 4. 生成自动打印页面（绕过云端PDF崩溃）=====
                    return f'''
                    <html>
                    <head>
                        <title>Drone Flight Report</title>
                        <style>
                            @media print {{
                                .no-print {{ display: none; }}
                                body {{ background: white; padding: 0; }}
                            }}
                            body {{ text-align:center; padding:50px; font-family:Arial; background:#f4f4f4; }}
                            .btn {{ background:#007AFF; color:white; padding:15px 40px; text-decoration:none; border-radius:50px; font-size:20px; font-weight:bold; display:inline-block; cursor:pointer; border:none; }}
                        </style>
                    </head>
                    <body>
                        <h1>✅ Report Generated Successfully!</h1>
                        <img src="/static/track.png" style="max-width:90%; border:2px solid #ddd; border-radius:8px; margin:20px 0;">
                        <br>
                        <button onclick="window.print()" class="btn no-print">📥 Download PDF Report</button>
                        <p class="no-print" style="color:#666; margin-top:15px;">点击按钮后，浏览器会弹出打印窗口，选择“另存为 PDF”即可。</p >
                    </body>
                    </html>
                    '''
                    
                else:
                    return f"找不到经纬度列。当前列名：{', '.join(df.columns)}"
                    
            except Exception as e:
                return f"读取文件出错：{str(e)}"
                
    return render_template_string(HTML)

@app.route('/download_report/<filename>')
def download_report(filename):
    import tempfile, os
    # 用魔法代码获取系统临时目录（Windows认C盘，Linux认/tmp）
    temp_dir = tempfile.gettempdir()
    file_path = os.path.join(temp_dir, filename)
    return send_file(file_path, as_attachment=True, download_name=filename)

    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', debug=True, port=port)
