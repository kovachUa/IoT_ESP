import json
import os
from datetime import datetime
from flask import Flask, request, jsonify, render_template, url_for, flash, session, redirect
from waitress import serve
from functools import wraps
import time
import socket
import threading

# pandas видалено, оскільки більше не використовується
# neuralprophet видалено
# ml_weather модуль видалено

# Імпортуємо наш модуль utils
from utils import get_local_ip

# set_random_seed(0) # Видалено

# --- Конфігурація ---
app = Flask(__name__)
app.secret_key = os.urandom(24)
USERNAME = "admin"; PASSWORD = "1234"
DATA_FILE = "devices.json"; LOGS_DIR_MAIN = "logs"; OFFLINE_TIMEOUT = 180
SERVER_BEACON_PORT = 50001; SERVER_BEACON_INTERVAL_S = 5
SERVER_HTTP_PORT = 5005; SERVER_BEACON_ID = "MY_UNIQUE_IOT_SERVER_V1"

# set_logs_dir(LOGS_DIR_MAIN) # Видалено, оскільки set_logs_dir була в ml_weather

devices = {}
if os.path.exists(DATA_FILE):
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f: devices = json.load(f)
    except json.JSONDecodeError: print(f"⚠️ JSON помилка в {DATA_FILE}.")
if not os.path.exists(LOGS_DIR_MAIN):
    os.makedirs(LOGS_DIR_MAIN); print(f"📁 Створено каталог логів: {os.path.abspath(LOGS_DIR_MAIN)}")

@app.context_processor
def inject_now(): return {'now': datetime.utcnow()}

# --- udp_server_beacon_broadcaster, login_required, login, logout (як раніше) ---
def udp_server_beacon_broadcaster():
    b_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    b_sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    b_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_ip_adv = get_local_ip() 
    if server_ip_adv.startswith("127."): print(f"⚠️ Маячок анонсує IP: {server_ip_adv}")
    payload = { "id": SERVER_BEACON_ID, "ip": server_ip_adv, "port": SERVER_HTTP_PORT }
    msg_bytes = json.dumps(payload).encode('utf-8')
    print(f"📢 Маячок: ('<broadcast>', {SERVER_BEACON_PORT}), інтервал: {SERVER_BEACON_INTERVAL_S}с. Дані: {payload}")
    while True:
        try:
            b_sock.sendto(msg_bytes, ('<broadcast>', SERVER_BEACON_PORT))
        except socket.error as e:
            print(f"❌ Маячок err: {e}")
            new_ip_adv = get_local_ip()
            if new_ip_adv != server_ip_adv:
                server_ip_adv = new_ip_adv; payload["ip"] = server_ip_adv
                msg_bytes = json.dumps(payload).encode('utf-8')
        except Exception as e_gen: print(f"❌ Маячок err загальний: {e_gen}")
        time.sleep(SERVER_BEACON_INTERVAL_S)

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session:
            flash("Будь ласка, увійдіть.", "warning"); return redirect(url_for('login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username"); password = request.form.get("password")
        if username == USERNAME and password == PASSWORD:
            session["logged_in"] = True; session.permanent = True; flash("Вхід виконано!", "success")
            return redirect(request.args.get('next') or url_for("monitor_page"))
        else: flash("Невірний логін/пароль.", "danger")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.pop("logged_in", None); flash("Ви вийшли.", "info"); return redirect(url_for("login"))

# --- Маршрути Flask ---
@app.route("/")
@login_required
def monitor_page(): return render_template("monitor.html", active_page="monitor", OFFLINE_TIMEOUT=OFFLINE_TIMEOUT)

@app.route("/devices")
@login_required
def devices_page():
    # Вся логіка навчання моделей видалена звідси
    print(f"[DEVICES PAGE] Сторінка пристроїв завантажена.")
    # MODEL_DATA_FREQUENCY більше не існує, тому видалено з логування
    return render_template("index.html", devices_data=devices, active_page="devices", OFFLINE_TIMEOUT=OFFLINE_TIMEOUT)

# Маршрут /weather та функція weather_page() були видалені раніше

# --- API endpoints ---
@app.route("/api/devices")
@login_required
def get_devices_api():
    now = datetime.now(); to_delete = []
    current_devices_snapshot = list(devices.items()) 
    for mac, dev_info in current_devices_snapshot:
        if not isinstance(dev_info, dict): continue
        last_seen_str = dev_info.get("last_seen")
        if last_seen_str:
            try:
                if (now - datetime.strptime(last_seen_str, "%Y-%m-%d %H:%M:%S")).total_seconds() > OFFLINE_TIMEOUT: to_delete.append(mac)
            except ValueError: to_delete.append(mac) 
        else: to_delete.append(mac)
    updated = False
    for mac_to_del in to_delete:
        if mac_to_del in devices: 
            # clear_models_for_mac_from_cache(mac_to_del) # Видалено, кешу моделей більше немає
            print(f"[API DEVICES] Видалення пристрою {mac_to_del} через таймаут.") # Додано лог для ясності
            del devices[mac_to_del]; updated = True
    if updated:
        try:
            with open(DATA_FILE, "w", encoding="utf-8") as f: json.dump(devices, f, indent=2, ensure_ascii=False)
        except IOError: pass 
    return jsonify(devices)

@app.route("/data", methods=["POST"])
def receive_data():
    if not request.is_json: return jsonify({"status": "error", "message": "JSON expected"}), 400
    payload = request.get_json()
    if not payload or not isinstance(payload, dict) or "mac" not in payload:
        return jsonify({"status": "error", "message": "'mac' required"}), 400
    mac_raw = payload.get("mac")
    if not isinstance(mac_raw, str): return jsonify({"status": "error", "message": "'mac' must be str"}), 400
    mac_raw = mac_raw.upper()
    if len(mac_raw) == 12 and ':' not in mac_raw and '-' not in mac_raw: mac_std = ":".join(mac_raw[i:i+2] for i in range(0,12,2))
    else: mac_std = mac_raw.replace("-",":")
    if len(mac_std) != 17 or mac_std.count(':') != 5: return jsonify({"status": "error", "message": f"Invalid MAC: {mac_raw}"}), 400
    mac_key = mac_std
    name = payload.get("name", devices.get(mac_key, {}).get("name", f"Node_{mac_key.replace(':','')[-6:]}"))
    data = payload.get("data", {})
    if not isinstance(data, dict): data = {}
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_file_mac = mac_key.replace(":", "").lower()
    log_path = os.path.join(LOGS_DIR_MAIN, f"{log_file_mac}.log") # LOGS_DIR_MAIN все ще актуальний
    try:
        with open(log_path, "a", encoding="utf-8") as lf:
            lf.write(json.dumps({"timestamp": now_str, "data": data, "name_in_payload": payload.get("name")}, ensure_ascii=False) + "\n")
    except IOError: pass
    devices[mac_key] = {"name": name, "data": data if data else devices.get(mac_key, {}).get("data",{}), "last_seen": now_str, "ip": request.remote_addr}
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as df_f: json.dump(devices, df_f, indent=2, ensure_ascii=False)
    except IOError: pass
    return jsonify({"status": "ok", "message": "Data received"}), 200

# --- Запуск ---
if __name__ == "__main__":
    beacon_thread = threading.Thread(target=udp_server_beacon_broadcaster, daemon=True); beacon_thread.start()
    HOST = "0.0.0.0"; SERVER_IP_FOR_PRINT = get_local_ip()
    print(f"🌍 Веб-сервер запускається на http://{SERVER_IP_FOR_PRINT}:{SERVER_HTTP_PORT} (або http://{HOST}:{SERVER_HTTP_PORT})")
    print(f"🔑 Логін: {USERNAME}, Пароль: {PASSWORD}")
    print(f"💾 Файл даних пристроїв: {os.path.abspath(DATA_FILE)}")
    print(f"📜 Каталог логів: {os.path.abspath(LOGS_DIR_MAIN)}")
    # Підказки про моделі та MODEL_DATA_FREQUENCY видалені
    serve(app, host=HOST, port=SERVER_HTTP_PORT, threads=10)
