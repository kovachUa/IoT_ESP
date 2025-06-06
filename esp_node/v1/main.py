import network
import time
import machine
import urequests
import ubinascii
import usocket as socket
import ujson as json
import errno
from machine import I2C, Pin

import bme280 # Assuming this is the correct bme280.py from above
from display import SH1106
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
        if SSID == 'YOUR_WIFI_SSID' or PASSWORD == 'YOUR_WIFI_PASSWORD':
            print("!!! ПОПЕРЕДЖЕННЯ: SSID або пароль не змінено з значень за замовчуванням !!!")
            print("Будь ласка, вкажіть реальні SSID та пароль.")
            return False # Зупинка, якщо облікові дані не встановлені

        sta_if.connect(SSID, PASSWORD)
        for _ in range(20): # Таймаут підключення 20 секунд
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
    sock.settimeout(BEACON_LISTEN_TIMEOUT_S) # Таймаут для операції recvfrom
    try:
        # Для MicroPython sock.bind(('0.0.0.0', PORT)) або ('', PORT)
        sock.bind(('', SERVER_BEACON_LISTEN_PORT)) 
        print(f"Очікування маячка на порту {SERVER_BEACON_LISTEN_PORT} протягом {BEACON_LISTEN_TIMEOUT_S}с...")
        start_listen_time = time.ticks_ms()
        
        while time.ticks_diff(time.ticks_ms(), start_listen_time) < (BEACON_LISTEN_TIMEOUT_S * 1000):
            try:
                # Встановлюємо таймаут для кожного recvfrom, щоб цикл міг перевіряти загальний час
                # sock.settimeout(1.0) # Таймаут для recvfrom в 1 секунду
                # Якщо BEACON_LISTEN_TIMEOUT_S вже встановлено для сокета, то окремий цикл не потрібен
                # Натомість, можна просто чекати на recvfrom
                
                data, addr = sock.recvfrom(256) # Буде блокувати до BEACON_LISTEN_TIMEOUT_S
                msg = data.decode()
                print(f"Отримано повідомлення від {addr}: {msg}")
                beacon = json.loads(msg)
                if beacon.get("id") == EXPECTED_SERVER_ID:
                    ip = beacon.get("ip")
                    port = beacon.get("port")
                    if ip and isinstance(port, int):
                        discovered_server_ip = ip
                        discovered_server_port = port
                        print(f"Знайдено сервер: {ip}:{port}")
                        return True # Сервер знайдено, виходимо
            except OSError as e:
                if e.args[0] == errno.ETIMEDOUT: # Таймаут recvfrom
                    # Просто продовжуємо, якщо ще є час у загальному таймауті
                    # Якщо sock.settimeout(BEACON_LISTEN_TIMEOUT_S) спрацював, цей цикл завершиться
                    pass 
                else:
                    print(f"Помилка сокета при очікуванні маячка: {e}")
            except (ValueError, TypeError) as e: # Помилка розбору JSON
                print(f"Помилка розбору JSON з маячка: {e}, повідомлення: {msg}")
            except Exception as e:
                print(f"Неочікувана помилка при обробці маячка: {e}")
        
        print("Таймаут очікування маячка (загальний час вийшов).")
        
    except Exception as e:
        print(f"Помилка налаштування сокета для маячка: {e}")
    finally:
        sock.close()
        
    discovered_server_ip = None
    discovered_server_port = None
    return False

def main():
    global discovered_server_ip, discovered_server_port, mac_address_global

    if not connect_wifi():
        print("Перевірте налаштування WiFi. Перезапуск через 30 секунд...")
        time.sleep(30)
        machine.reset()

    display = SH1106(128, 64, i2c, addr=0x3C)
    display.fill(0)
    display.text("Init display...", 0, 0)
    display.show()

    bme_sensor = None
    try:
        bme_sensor = bme280.BME280(i2c=i2c, address=0x76)
        print("BME280 ініціалізовано")
    except Exception as e:
        print(f"Помилка ініціалізації BME280: {e}")
        display.fill(0)
        display.text("BME280 Error", 0, 10)
        display.show()
        time.sleep(2)


    light_sensor = None
    try:
        light_sensor = BH1750(i2c)
        print("BH1750 ініціалізовано")
    except Exception as e:
        print(f"Помилка ініціалізації BH1750: {e}")
        display.fill(0)
        display.text("BH1750 Error", 0, 20)
        display.show()
        time.sleep(2)


    while True:
        if discovered_server_ip is None or discovered_server_port is None:
            display.fill(0)
            display.text("Шукаю сервер...", 0, 0)
            display.show()
            if not listen_for_server_beacon():
                print("Сервер не знайдено, повторна спроба...")
                display.fill(0)
                display.text("No Server", 0, 0)
                display.text(f"Retry {RETRY_LISTEN_INTERVAL_S}s", 0, 10)
                display.show()
                time.sleep(RETRY_LISTEN_INTERVAL_S)
                continue
            else:
                display.fill(0)
                display.text("Сервер знайдено!", 0, 0)
                display.text(f"{discovered_server_ip}", 0, 10)
                display.text(f":{discovered_server_port}", 0, 20)
                display.show()
                time.sleep(2)

        t, p_hpa, h = None, None, None # p_hpa - тиск в гектопаскалях
        if bme_sensor:
            try:
                temp, pres_hpa_val, hum = bme_sensor.read_compensated_data()
                t = float(temp)
                # 'pres_hpa_val' вже в hPa з bme280.read_compensated_data()
                # float() тут для певності, хоча read_compensated_data вже повертає float
                p_hpa = float(pres_hpa_val) 
                h = float(hum)
            except Exception as e:
                print(f"Помилка читання BME280: {e}")

        lux = None
        if light_sensor:
            try:
                lux = light_sensor.luminance()
            except Exception as e:
                print(f"Помилка читання BH1750: {e}")

        display.fill(0)
        display.text("ESP32 Monitor", 0, 0)
        if t is not None:
            display.text(f"T: {t:.1f} C", 0, 10)
        else:
            display.text("T: N/A", 0, 10)
        
        if p_hpa is not None:
            display.text(f"P: {p_hpa:.1f} hPa", 0, 20) # p_hpa тепер має правильне значення
        else:
            display.text("P: N/A", 0, 20)
            
        if h is not None:
            display.text(f"H: {h:.1f} %", 0, 30)
        else:
            display.text("H: N/A", 0, 30)

        if lux is not None:
            if lux < 5:
                display.text("Night mode", 0, 40)
            else:
                display.text(f"Lux: {lux:.1f}", 0, 40)
        else:
            display.text("Lux: N/A", 0, 40)

        if discovered_server_ip:
            display.text("Srv: Connected", 0, 50)
        else:
            display.text("Srv: Searching", 0, 50)
        display.show()

        if discovered_server_ip and discovered_server_port:
            payload = {
                "mac": mac_address_global if mac_address_global else "UNKNOWN_MAC",
                "data": {
                    "temperature": round(t, 2) if t is not None else None,
                    "pressure_hpa": round(p_hpa, 2) if p_hpa is not None else None, # Використовуємо p_hpa
                    "humidity": round(h, 2) if h is not None else None,
                    "illumination_lux": round(lux, 2) if lux is not None else None
                }
            }
            try:
                url = f"http://{discovered_server_ip}:{discovered_server_port}/data"
                print(f"Відправка на {url}: {payload}")
                headers = {'Content-Type': 'application/json'}
                res = urequests.post(url, json=payload, headers=headers)
                print(f"Статус відправки: {res.status_code}")
                res.close()
            except Exception as e:
                print(f"Помилка відправки даних: {e}")
                # Скидаємо інформацію про сервер, щоб спробувати знайти його знову
                discovered_server_ip = None
                discovered_server_port = None
                display.fill(0)
                display.text("Send Error", 0, 0)
                display.text("Srv Lost", 0, 10)
                display.show()
                time.sleep(2) # Невелика затримка перед повторним пошуком сервера

        time.sleep(10) # Інтервал між відправками даних

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("Зупинка користувачем")
    except Exception as e:
        print(f"Критична помилка в main: {e}")
        # Можна додати код для безпечного завершення або перезавантаження
        # machine.reset()
