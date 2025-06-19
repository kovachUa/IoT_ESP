import network
import time
import machine
import urequests
import ubinascii
import usocket as socket
import ujson as json
import errno
from machine import I2C, Pin

import bme280
from bh1750 import BH1750

# WiFi конфігурація
SSID = ' '
PASSWORD = ' ' 

# UDP маячок
SERVER_BEACON_LISTEN_PORT = 50001
EXPECTED_SERVER_ID = "MY_UNIQUE_IOT_SERVER_V1"
BEACON_LISTEN_TIMEOUT_S = 15
RETRY_LISTEN_INTERVAL_S = 30

discovered_server_ip = None
discovered_server_port = None
mac_address_global = None

# I2C шина
i2c = I2C(0, scl=Pin(22), sda=Pin(21), freq=400000)

def connect_wifi():
    global mac_address_global
    sta_if = network.WLAN(network.STA_IF)
    if not sta_if.active():
        sta_if.active(True)
    if not sta_if.isconnected():
        print(f"Підключення до WiFi SSID: {SSID}...")
        if SSID == ' ' or PASSWORD == ' ' or SSID == 'YOUR_WIFI_SSID' or PASSWORD == 'YOUR_WIFI_PASSWORD':
            print("!!! ПОПЕРЕДЖЕННЯ: SSID або пароль не змінено з значень за замовчуванням або порожні !!!")
            print("Будь ласка, вкажіть реальні SSID та пароль у файлі main.py.")
            return False

        sta_if.connect(SSID, PASSWORD)
        for _ in range(20):
            if sta_if.isconnected():
                break
            print(".", end="")
            time.sleep(1)
        print()
    if sta_if.isconnected():
        print("WiFi підключено!")
        mac = sta_if.config('mac')
        mac_address_global = ubinascii.hexlify(mac).decode()
        print(f"MAC: {mac_address_global}")
        return True
    else:
        print("Не вдалося підключитись до WiFi")
        return False

def listen_for_server_beacon():
    global discovered_server_ip, discovered_server_port
    if not network.WLAN(network.STA_IF).isconnected():
        print("WiFi не підключено")
        return False

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(BEACON_LISTEN_TIMEOUT_S)
    try:
        sock.bind(('', SERVER_BEACON_LISTEN_PORT))
        print(f"Очікування маячка на порту {SERVER_BEACON_LISTEN_PORT} протягом {BEACON_LISTEN_TIMEOUT_S}с...")
        start_listen_time = time.ticks_ms()

        while time.ticks_diff(time.ticks_ms(), start_listen_time) < (BEACON_LISTEN_TIMEOUT_S * 1000):
            try:
                data, addr_info = sock.recvfrom(256) # addr_info is (ip_str, port_int)
                msg = data.decode()
                print(f"Отримано повідомлення від {addr_info}: {msg}")
                
                sender_ip = addr_info[0] # IP-адреса відправника маячка

                beacon = json.loads(msg)
                if beacon.get("id") == EXPECTED_SERVER_ID:
                    payload_ip = beacon.get("ip")
                    payload_port = beacon.get("port")

                    if payload_ip and isinstance(payload_port, int):
                        # Якщо IP в маячку є loopback, використовуємо IP відправника.
                        # В іншому випадку, довіряємо IP з маячка (на випадок складних мережевих конфігурацій).
                        if payload_ip == "127.0.0.1" or payload_ip.startswith("0."):
                            print(f"Інформація: IP в маячку ({payload_ip}) є loopback. Використовується IP відправника ({sender_ip}).")
                            discovered_server_ip = sender_ip
                        else:
                            discovered_server_ip = payload_ip
                        
                        discovered_server_port = payload_port
                        print(f"Знайдено сервер: {discovered_server_ip}:{discovered_server_port}")
                        return True
            except OSError as e:
                if e.args[0] == errno.ETIMEDOUT:
                    pass
                else:
                    print(f"Помилка сокета при очікуванні маячка: {e}")
            except (ValueError, TypeError) as e:
                print(f"Помилка розбору JSON з маячка: {e}, повідомлення: {msg}")
            except Exception as e:
                print(f"Неочікувана помилка при обробці маячка: {e}")

        print("Таймаут очікування маячка.")

    except Exception as e:
        print(f"Помилка налаштування сокета для маячка: {e}")
    finally:
        sock.close()

    discovered_server_ip = None
    discovered_server_port = None
    return False

def main():
    global discovered_server_ip, discovered_server_port, mac_address_global

    print("Ініціалізація пристрою...")

    if not connect_wifi():
        print("Перевірте налаштування WiFi. Перезапуск через 30 секунд...")
        time.sleep(30)
        machine.reset()

    bme_sensor = None
    try:
        bme_sensor = bme280.BME280(i2c=i2c, address=0x76)
        print("BME280 ініціалізовано")
    except Exception as e:
        print(f"Помилка ініціалізації BME280: {e}")
        time.sleep(2)


    light_sensor = None
    try:
        light_sensor = BH1750(i2c)
        print("BH1750 ініціалізовано")
    except Exception as e:
        print(f"Помилка ініціалізації BH1750: {e}")
        time.sleep(2)


    while True:
        if discovered_server_ip is None or discovered_server_port is None:
            print("Шукаю сервер...")
            if not listen_for_server_beacon():
                print(f"Сервер не знайдено, повторна спроба через {RETRY_LISTEN_INTERVAL_S}с...")
                time.sleep(RETRY_LISTEN_INTERVAL_S)
                continue
            else:
                print(f"Сервер успішно знайдено: {discovered_server_ip}:{discovered_server_port}")
                time.sleep(1) # Невелика затримка після знаходження сервера

        t, p_hpa, h = None, None, None
        if bme_sensor:
            try:
                temp, pres_hpa_val, hum = bme_sensor.read_compensated_data()
                t = float(temp)
                p_hpa = float(pres_hpa_val)
                h = float(hum)
                print(f"BME280: T={t:.1f}C, P={p_hpa:.1f}hPa, H={h:.1f}%")
            except Exception as e:
                print(f"Помилка читання BME280: {e}")

        lux = None
        if light_sensor:
            try:
                lux = light_sensor.luminance()
                print(f"BH1750: Lux={lux:.1f}")
            except Exception as e:
                print(f"Помилка читання BH1750: {e}")

        if discovered_server_ip and discovered_server_port:
            payload = {
                "mac": mac_address_global if mac_address_global else "UNKNOWN_MAC",
                "data": {
                    "temperature": round(t, 2) if t is not None else None,
                    "pressure_hpa": round(p_hpa, 2) if p_hpa is not None else None,
                    "humidity": round(h, 2) if h is not None else None,
                    "illumination_lux": round(lux, 2) if lux is not None else None
                }
            }
            try:
                url = f"http://{discovered_server_ip}:{discovered_server_port}/data"
                # Використовуємо json.dumps для коректного логування повного payload
                print(f"Відправка на {url}: {json.dumps(payload)}")
                headers = {'Content-Type': 'application/json'}
                res = urequests.post(url, json=payload, headers=headers)
                print(f"Статус відправки: {res.status_code}")
                res.close()
            except Exception as e:
                print(f"Помилка відправки даних: {e}")
                discovered_server_ip = None
                discovered_server_port = None
                print("З'єднання з сервером втрачено. Повторний пошук...")
                time.sleep(2)

        time.sleep(10)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("Зупинка користувачем")
    except Exception as e:
        print(f"Критична помилка в main: {e}")
        # machine.reset() # Розкоментуйте для автоматичного перезавантаження
