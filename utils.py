# utils.py
import socket
import math
# from datetime import datetime, timedelta # Не використовується тут зараз

def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    ip_addr = '127.0.0.1' # Default
    try:
        s.connect(('8.8.8.8', 80)) 
        ip_addr = s.getsockname()[0]
    except Exception:
        try: 
            hostname = socket.gethostname()
            ip_h = socket.gethostbyname(hostname)
            if not ip_h.startswith("127."):
                ip_addr = ip_h
            else:
                addrs = socket.getaddrinfo(hostname, None)
                for item in addrs:
                    if item[0] == socket.AF_INET and not item[4][0].startswith("127."): ip_addr = item[4][0]; break
        except Exception:
            pass 
    finally:
        s.close()
    return ip_addr

def calculate_dew_point(temperature_c, relative_humidity_percent):
    if temperature_c is None or relative_humidity_percent is None:
        return None
    try:
        T = float(temperature_c)
        RH = float(relative_humidity_percent)
        if not (0 <= RH <= 100): 
             return None
        b = 17.62; c = 243.12
        gamma = (b * T / (c + T)) + math.log(RH / 100.0)
        dew_point = (c * gamma) / (b - gamma)
        return dew_point
    except (ValueError, TypeError, OverflowError, ZeroDivisionError) as e_dew:
        print(f"[DEW POINT CALC] Помилка розрахунку: {e_dew} для T={temperature_c}, RH={relative_humidity_percent}")
        return None
