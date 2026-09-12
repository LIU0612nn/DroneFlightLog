from flask import Flask, request, render_template_string, send_file
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib import font_manager

# 强行指定 Windows 系统里的黑体字体路径（一劳永逸解决 Anaconda 找不到字体的问题）
font_path = "C:/Windows/Fonts/simhei.ttf"
my_font = font_manager.FontProperties(fname=font_path)

# 将强行加载的字体设置到全局
plt.rcParams['font.family'] = my_font.get_name()
plt.rcParams['axes.unicode_minus'] = False
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
    """把轨迹图 + 数据生成一份PDF报告"""
    c = canvas.Canvas(output_path, pagesize=A4)
    width, height = A4
    
    # 第一页：报告标题页
    c.setFont("Helvetica-Bold", 28)
    c.drawString(50, height - 60, "Drone Flight Report")
    c.setFont("Helvetica", 14)
    c.drawString(50, height - 120, f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    c.drawString(50, height - 150, f"Total Waypoints: {flight_data['points']}")
    c.drawString(50, height - 180, f"Max Altitude: {flight_data['max_alt']} m")
    
    # 第二页：轨迹图
    c.showPage()
    c.setFont("Helvetica-Bold", 18)
    c.drawString(50, height - 50, "Flight Path & Wind Field")
    if os.path.exists(image_path):
        c.drawImage(ImageReader(image_path), 50, 100, width=width-100, height=height-200)
    
    c.save()
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
    """从Open-Meteo获取风场数据（免费，无需API Key）"""
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat, "longitude": lon,
        "hourly": "wind_speed_10m,wind_direction_10m",
        "start_date": date_str, "end_date": date_str,
        "timezone": "Asia/Shanghai"
    }
    resp = requests.get(url, params=params).json()
    hourly = resp['hourly']
    return hourly['wind_speed_10m'][12], hourly['wind_direction_10m'][12]

def wind_to_uv(speed, direction_deg):
    """风向转U/V分量（画箭头用）"""
    rad = math.radians(direction_deg)
    return -speed * math.sin(rad), -speed * math.cos(rad)

@app.route('/download_report/<filename>')
def download_report(filename):
    # 你的环境是 Flask 1.1.2，所以依然要使用 attachment_filename
    return send_file(f'static/{filename}', as_attachment=True, attachment_filename=filename)
@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        file = request.files['file']
        if file:
            try:
                df = pd.read_csv(file)
                lat_col, lon_col = find_lat_lon(df)
                
                if lat_col and lon_col:
                    # ===== 1. 基础画图 =====
                    plt.figure(figsize=(10,6))
                    plt.plot(df[lon_col], df[lat_col], linewidth=2, color='#007AFF')
                    plt.xlabel('Longitude', fontsize=12)
                    plt.ylabel('Latitude', fontsize=12)
                    plt.title('Drone Flight Path', fontsize=16)
                    plt.ticklabel_format(style='plain', useOffset=False, axis='both')
                    
                    # ===== 2. 叠加风场 =====
                    try:
                        from datetime import datetime
                        lat0 = df[lat_col].iloc[0]
                        lon0 = df[lon_col].iloc[0]
                        date_str = datetime.now().strftime('%Y-%m-%d')
                        
                        wind_speed, wind_dir = get_wind_data(lat0, lon0, date_str)
                        u, v = wind_to_uv(wind_speed, wind_dir)
                        
                        step = max(1, len(df) // 8)
                        for i in range(0, len(df), step):
                            plt.quiver(df[lon_col].iloc[i], df[lat_col].iloc[i], u, v,
                                       color='#FF8C00', alpha=0.85,
                                       scale=30000, width=0.002,
                                       headwidth=3, headlength=4, headaxislength=3.5,
                                       angles='xy', scale_units='xy')
                        
                        plt.text(0.02, 0.95, f"Wind: {wind_speed} m/s, Dir: {wind_dir} deg",
                                 transform=plt.gca().transAxes, color='#FF8C00', fontsize=12)
                    except Exception as e:
                        print(f"风场数据获取失败: {e}")
                    
                    # ===== 3. 保存图片 =====
                    plt.grid(True, alpha=0.3)
                    plt.margins(0.1)
                    os.makedirs('static', exist_ok=True)
                    plt.savefig('static/track.png', dpi=150)
                    plt.close()
                    
                    # ===== 4. 生成 PDF 并返回下载页 =====
                    from datetime import datetime
                    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                    pdf_path = f'static/report_{timestamp}.pdf'
                    
                    flight_data = {
                        'points': len(df),
                        'max_alt': df['altitude'].max() if 'altitude' in df.columns else 'N/A'
                    }
                    generate_pdf_report('static/track.png', pdf_path, flight_data)
                    
                    # 返回带下载按钮的页面
                    return f'''
                    <html><body style="text-align:center; padding:50px; font-family:Arial; background:#f4f4f4;">
                        <h1>✅ Report Generated Successfully!</h1>
                        <img src="/static/track.png" style="max-width:80%; border:2px solid #ddd; border-radius:8px; box-shadow:0 4px 10px rgba(0,0,0,0.1); margin:20px 0;">
                        <br>
                        <a href="/download_report/report_{timestamp}.pdf" download style="background:#007AFF; color:white; padding:15px 40px; text-decoration:none; border-radius:50px; font-size:20px; font-weight:bold; display:inline-block;">📥 Download PDF Report</a >
                    </body></html>
                    '''
                    
                else:
                    return render_template_string(HTML, error=f"找不到经纬度列。列名：{', '.join(df.columns)}")
            
            except Exception as e:
                return render_template_string(HTML, error=f"读取文件出错：{str(e)}")
                
    return render_template_string(HTML, img_path=None, error=None)



if __name__ == '__main__':
    app.run(debug=True, port=5000)