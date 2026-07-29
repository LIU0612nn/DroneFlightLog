import struct
def parse_bin_light(file_path):
    logs = []
    with open(file_path, 'rb') as f:
        data = f.read()
        idx = 0
        while idx + 8 <= len(data):
            if data[idx] == 0xA3 and data[idx+1] == 0x95:
                msg_len = struct.unpack('<H', data[idx+2:idx+4])[0]
                if idx + 8 + msg_len > len(data):
                    break
                msg_type = struct.unpack('<H', data[idx+4:idx+6])[0]
                if msg_type == 0x02:  # GPS消息示例
                    lat = struct.unpack('<i', data[idx+8:idx+12])[0] / 1e7
                    lon = struct.unpack('<i', data[idx+12:idx+16])[0] / 1e7
                    logs.append({'lat': lat, 'lon': lon, 'alt': 0, 'volt': 0})
                idx += 8 + msg_len
            else:
                idx += 1
    return logs