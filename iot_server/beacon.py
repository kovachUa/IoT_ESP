# iot_server/beacon.py
import socket
import time
import json
from . import config, utils

def udp_server_beacon_broadcaster():
    b_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    b_sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    b_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    server_ip_adv = utils.get_local_ip()
    if server_ip_adv.startswith("127."):
        print(f"⚠️ Маячок анонсує локальний IP: {server_ip_adv}. Пристрої в мережі можуть його не побачити.")

    payload = {"id": config.SERVER_BEACON_ID, "ip": server_ip_adv, "port": config.SERVER_HTTP_PORT}
    msg_bytes = json.dumps(payload).encode('utf-8')

    print(f"📢 Маячок запущено: ('<broadcast>', {config.SERVER_BEACON_PORT}), інтервал: {config.SERVER_BEACON_INTERVAL_S}с. Дані: {payload}")

    while True:
        try:
            b_sock.sendto(msg_bytes, ('<broadcast>', config.SERVER_BEACON_PORT))
        except socket.error as e:
            print(f"❌ Помилка сокета маячка: {e}")
            new_ip_adv = utils.get_local_ip()
            if new_ip_adv != server_ip_adv:
                server_ip_adv = new_ip_adv
                payload["ip"] = server_ip_adv
                msg_bytes = json.dumps(payload).encode('utf-8')
                print(f"📢 IP маячка оновлено на {server_ip_adv}")
        except Exception as e_gen:
            print(f"❌ Загальна помилка маячка: {e_gen}")
        time.sleep(config.SERVER_BEACON_INTERVAL_S)
