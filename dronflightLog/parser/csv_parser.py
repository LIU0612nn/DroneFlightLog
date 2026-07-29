import csv
def parse_csv(file_path):
    logs = []
    with open(file_path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            logs.append({
                'lat': float(row.get('lat', 0)),
                'lon': float(row.get('lon', 0)),
                'alt': float(row.get('alt', 0)),
                'volt': float(row.get('volt', 0))
            })
    return logs