import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import app as m

df = m.create_demo_flight()
stats = m.calculate_statistics(df)
fd = m.get_flight_date(df)
wind = m.get_wind_field(df, fd, grid_size=6)
print("flight_date:", fd)
print("wind speed/dir/source:", wind.get("speed"), wind.get("direction"), wind.get("source"))
print("grid points:", len(wind.get("grid", [])))

img = m.generate_flight_plot(df, wind)
img_path = os.path.join(m.GENERATED_DIR, img)
pdf = m.generate_pdf_report(df, stats, wind, img_path)
pdf_path = os.path.join(m.GENERATED_DIR, pdf)
print("IMG:", img_path)
print("PDF:", pdf_path)
print("IMG_EXISTS:", os.path.exists(img_path), os.path.getsize(img_path))
print("PDF_EXISTS:", os.path.exists(pdf_path), os.path.getsize(pdf_path))
