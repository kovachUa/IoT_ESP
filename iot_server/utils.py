# iot_server/utils.py
import socket

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
