from pymavlink import mavutil
def parse_bin_mavlink(file_path):
    logs = {'gps': [], 'att': [], 'bat': []}
    mlog = mavutil.mavlink_connection(file_path)
    while True:
        msg = mlog.recv_match()
        if not msg:
            break
        if msg.get_type() == 'GPS_RAW_INT':
            logs['gps'].append({'lat': msg.lat/1e7, 'lon': msg.lon/1e7, 'alt': msg.alt/1000})
        elif msg.get_type() == 'ATTITUDE':
            logs['att'].append({'roll': msg.roll, 'pitch': msg.pitch, 'yaw': msg.yaw})
        elif msg.get_type() == 'BATTERY_STATUS':
            logs['bat'].append({'volt': msg.voltages[0]/1000})
    return logs