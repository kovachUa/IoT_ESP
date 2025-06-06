import json
import os
from datetime import datetime, timedelta
import random
# math не потрібен тут, він в utils

from flask import Flask, request, jsonify, render_template, url_for, flash, session, redirect
from waitress import serve
from functools import wraps
import time
import socket
import threading

import pandas as pd # Потрібен для pd.isna в weather_page
from neuralprophet import set_random_seed 

# Імпортуємо наші нові модулі
from utils import get_local_ip, calculate_dew_point
from ml_weather import (
    set_logs_dir,
    get_historical_data_for_model,
    train_model,
    make_prediction,
    generate_future_regressor_pattern,
    MODEL_DATA_FREQUENCY,
    model_exists_in_cache,
    get_trained_model_from_cache,
    clear_models_for_mac_from_cache
)


set_random_seed(0)

# --- Конфігурація ---
app = Flask(__name__)
app.secret_key = os.urandom(24)
USERNAME = "admin"; PASSWORD = "1234"
DATA_FILE = "devices.json"; LOGS_DIR_MAIN = "logs"; OFFLINE_TIMEOUT = 180
SERVER_BEACON_PORT = 50001; SERVER_BEACON_INTERVAL_S = 5
SERVER_HTTP_PORT = 5005; SERVER_BEACON_ID = "MY_UNIQUE_IOT_SERVER_V1"

set_logs_dir(LOGS_DIR_MAIN)

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
    print(f"[DEVICES PAGE] (Пере)навчання моделей з freq='{MODEL_DATA_FREQUENCY}'...")
    if devices and isinstance(devices, dict):
        for mac, dev_info in list(devices.items()):
            if dev_info and isinstance(dev_info, dict):
                device_data = dev_info.get("data", {})
                if device_data and isinstance(device_data, dict):
                    temp_sid, light_sid_actual = None, None
                    light_reg_name_model = "light_level" 
                    for sid_iter in device_data.keys():
                        if "temp" in sid_iter.lower() and temp_sid is None: temp_sid = sid_iter
                        if ("light" in sid_iter.lower() or "lux" in sid_iter.lower()) and light_sid_actual is None:
                            light_sid_actual = sid_iter
                    if temp_sid:
                        model_k = f"{mac}_{temp_sid}"
                        reg_conf = {light_reg_name_model: light_sid_actual} if light_sid_actual else {}
                        active_regs_model = [light_reg_name_model] if light_sid_actual and light_reg_name_model in reg_conf else []
                        
                        # print(f"[DEVICES PAGE] Обробка {model_k}. Регресори для завантаження: {reg_conf}")
                        hist_df = get_historical_data_for_model(mac, temp_sid, regressor_config=reg_conf, N_days=90)
                        
                        if hist_df is not None and not hist_df.empty:
                            ready_to_train = True
                            for reg in active_regs_model:
                                if reg not in hist_df.columns:
                                    print(f"⚠️ [DEVICES PAGE] Регресор {reg} відсутній в hist_df для {model_k}.")
                                    ready_to_train = False; break
                            if ready_to_train:
                                train_model(hist_df, model_k, regressor_names=active_regs_model, epochs=30)
                        elif model_k: 
                            train_model(pd.DataFrame(), model_k) # Передача порожнього DataFrame для видалення з кешу
                                 
    print("[DEVICES PAGE] Завершено.")
    return render_template("index.html", devices_data=devices, active_page="devices", OFFLINE_TIMEOUT=OFFLINE_TIMEOUT)

@app.route("/weather")
@login_required
def weather_page():
    print(f"--- [WEATHER PAGE V6] /weather: Початок (freq='{MODEL_DATA_FREQUENCY}') ---")
    loc_name, cur_temp, cur_hum, cur_press, dew_p, press_trend = "Невідомо", None, None, None, None, "N/A"
    model_k_np, mac_tgt, temp_sid_tgt = None, None, None
    light_reg_name_model = "light_level"
    forecast_list = []

    active_dev_cands = []
    if devices and isinstance(devices, dict):
        for mac_iter, dev_info_iter in list(devices.items()):
            if dev_info_iter and isinstance(dev_info_iter, dict) and \
               dev_info_iter.get("data") and isinstance(dev_info_iter.get("data"), dict) and \
               dev_info_iter.get("last_seen"):
                try:
                    last_seen_dt = datetime.strptime(dev_info_iter["last_seen"], "%Y-%m-%d %H:%M:%S")
                    if (datetime.now() - last_seen_dt).total_seconds() <= OFFLINE_TIMEOUT:
                        device_data_iter = dev_info_iter["data"]
                        temp_val, hum_val, press_val, temp_sens_id_iter, light_sens_id_iter = None, None, None, None, None
                        for s_id, val_raw in device_data_iter.items():
                            val_float = None; 
                            if isinstance(val_raw, str): 
                                try: val_float = float(val_raw)
                                except ValueError: pass
                            elif isinstance(val_raw, (int, float)): val_float = float(val_raw)
                            
                            if val_float is not None:
                                if "temp" in s_id.lower() and temp_val is None: temp_val, temp_sens_id_iter = val_float, s_id
                                if "hum" in s_id.lower() and hum_val is None: hum_val = val_float
                                if "press" in s_id.lower() and press_val is None: press_val = val_float
                                if ("light" in s_id.lower() or "lux" in s_id.lower()) and light_sens_id_iter is None: light_sens_id_iter = s_id
                        if temp_val is not None:
                            active_dev_cands.append({
                                "mac": mac_iter, "temp_sensor_id": temp_sens_id_iter, "temperature": temp_val,
                                "humidity": hum_val, "pressure": press_val, 
                                "light_sensor_id_actual": light_sens_id_iter,
                                "device_name": dev_info_iter.get("name", mac_iter)
                            })
                except ValueError: pass
    
    if active_dev_cands:
        active_dev_cands.sort(key=lambda x: x['mac'])
        chosen_dev = active_dev_cands[0]
        mac_tgt, temp_sid_tgt = chosen_dev.get('mac'), chosen_dev.get('temp_sensor_id')
        loc_name, cur_temp, cur_hum, cur_press = chosen_dev.get('device_name'), chosen_dev.get('temperature'), chosen_dev.get('humidity'), chosen_dev.get('pressure')
        actual_light_id_for_chosen_dev = chosen_dev.get('light_sensor_id_actual')

        if mac_tgt and temp_sid_tgt: model_k_np = f"{mac_tgt}_{temp_sid_tgt}"
        if isinstance(cur_temp, (int,float)) and isinstance(cur_hum, (int,float)):
            dew_p = calculate_dew_point(cur_temp, cur_hum)
        
        press_sid_found = None
        if mac_tgt and devices.get(mac_tgt) and isinstance(devices[mac_tgt].get("data"), dict):
            for s_id_p in devices[mac_tgt]['data'].keys():
                if 'press' in s_id_p.lower(): press_sid_found = s_id_p; break
        if press_sid_found:
            hist_press_df = get_historical_data_for_model(mac_tgt, press_sid_found, N_days=1)
            if hist_press_df is not None and not hist_press_df.empty and len(hist_press_df) >= 2:
                try:
                    df_p_idx = hist_press_df.set_index('ds') if 'ds' in hist_press_df.columns else hist_press_df
                    if not df_p_idx.empty and not df_p_idx['y'].isnull().all():
                        last_data_time = df_p_idx.index[-1]
                        recent_p = df_p_idx[df_p_idx.index > (last_data_time - timedelta(hours=3))]
                        if len(recent_p) >= 2:
                            last_p, first_p = recent_p['y'].iloc[-1], recent_p['y'].iloc[0]
                            p_diff = last_p - first_p
                            if cur_press is None: cur_press = last_p 
                            if abs(p_diff) < 0.5: press_trend = "Стабільний"
                            elif p_diff > 1.5: press_trend = "Швидко зростає"
                            elif p_diff > 0.5: press_trend = "Повільно зростає"
                            elif p_diff < -1.5: press_trend = "Швидко падає"
                            elif p_diff < -0.5: press_trend = "Повільно падає"
                            else: press_trend = "Коливання"
                        else: press_trend = "Мало даних (тиск)"
                    else: press_trend = "Історія тиску порожня"
                except Exception as e_pt: print(f"Помилка аналізу тенденції тиску: {e_pt}"); press_trend = "Помилка (тиск)"
            else: press_trend = "Історія тиску відсутня"
        elif cur_press is not None: press_trend = "Історія тиску відсутня (є поточний)"

        full_forecast_df = None
        if model_k_np and model_exists_in_cache(model_k_np):
            model_inst = get_trained_model_from_cache(model_k_np)
            if model_inst:
                model_expects_light = light_reg_name_model in (model_inst.regressors.keys() if model_inst.regressors else [])
                periods_3d = 0
                try:
                    val_freq_int = int(MODEL_DATA_FREQUENCY[:-1]) if MODEL_DATA_FREQUENCY[:-1].isdigit() else 1
                    if MODEL_DATA_FREQUENCY.endswith(('T', 'min')): periods_per_hour = 60 / val_freq_int
                    elif MODEL_DATA_FREQUENCY.endswith('H'): periods_per_hour = 1.0
                    else: periods_per_hour = 1.0/24.0 
                    periods_3d = int(3 * 24 * periods_per_hour) + int(12 * periods_per_hour) 
                except (ValueError, TypeError, ZeroDivisionError): periods_3d = (3*24)+12 # Заглушка для 'H'
                
                future_df_construct = None
                if model_expects_light and actual_light_id_for_chosen_dev:
                    future_df_construct = generate_future_regressor_pattern(datetime.now(), periods=periods_3d, model_regressor_name=light_reg_name_model)
                else:
                     future_dates_ds = pd.date_range(start=datetime.now(), periods=periods_3d, freq=MODEL_DATA_FREQUENCY)
                     future_df_construct = pd.DataFrame({'ds': future_dates_ds})
                     if model_expects_light:
                         future_df_construct[light_reg_name_model] = 500 
                if future_df_construct is not None:
                    full_forecast_df = make_prediction(model_k_np, future_df_construct)
        else: print(f"[WEATHER PAGE] Модель {model_k_np} не готова.")

        if full_forecast_df is not None and not full_forecast_df.empty:
            if 'ds' in full_forecast_df.columns: full_forecast_df = full_forecast_df.set_index('ds')
            else: # Якщо 'ds' немає, прогноз невірний
                print("⚠️ [WEATHER PAGE] full_forecast_df не містить колонки 'ds' після прогнозування!"); full_forecast_df = None

        if full_forecast_df is not None and not full_forecast_df.empty: # Повторна перевірка
            day_hr_start, day_hr_end = 7, 18
            for i in range(3):
                day_label = ["Завтра", "Післязавтра", "Через 2 дні"][i]
                start_fc_day = (datetime.now() + timedelta(days=i+1)).replace(hour=0, minute=0, second=0, microsecond=0)
                end_fc_day = start_fc_day + timedelta(days=1)
                
                # Переконуємося, що індекс є DatetimeIndex
                if not isinstance(full_forecast_df.index, pd.DatetimeIndex):
                    print("⚠️ [WEATHER PAGE] Індекс full_forecast_df не є DatetimeIndex! Пропуск агрегації.")
                    break 
                
                day_fc_slice_series = full_forecast_df[(full_forecast_df.index >= start_fc_day) & (full_forecast_df.index < end_fc_day)]
                
                temp_h_d, temp_l_n, avg_temp_cond = None, None, None
                if not day_fc_slice_series.empty and 'yhat1' in day_fc_slice_series.columns:
                    day_fc_slice = day_fc_slice_series['yhat1']
                    if not day_fc_slice.dropna().empty: # Працюємо тільки якщо є не-NaN значення
                        day_temps = day_fc_slice[(day_fc_slice.index.hour >= day_hr_start) & (day_fc_slice.index.hour <= day_hr_end)]
                        night_temps = day_fc_slice[(day_fc_slice.index.hour < day_hr_start) | (day_fc_slice.index.hour > day_hr_end)]
                        
                        if not day_temps.dropna().empty: temp_h_d = day_temps.max()
                        elif not day_fc_slice.dropna().empty: temp_h_d = day_fc_slice.max() 
                        
                        if not night_temps.dropna().empty: temp_l_n = night_temps.min()
                        elif not day_fc_slice.dropna().empty: temp_l_n = day_fc_slice.min()
                        
                        avg_temp_cond = day_temps.mean() if not day_temps.dropna().empty else \
                                       (day_fc_slice.mean() if not day_fc_slice.dropna().empty else None)
                    else: # Якщо всі значення в day_fc_slice є NaN
                        avg_temp_cond = cur_temp if isinstance(cur_temp, (int, float)) else 15.0
                else: avg_temp_cond = cur_temp if isinstance(cur_temp, (int, float)) else 15.0
                
                cond_f, icon_f, press_eff = "Мінл. хмарн.", "bi-cloud-sun", ""
                if press_trend == "Швидко падає": cond_f, icon_f, press_eff = "Ймовірні опади", "bi-cloud-drizzle", "(тиск↓)"
                elif isinstance(avg_temp_cond, (int,float)) and avg_temp_cond < 10 and "опади" not in cond_f: cond_f, icon_f = "Прохолодно", "bi-snow"
                elif isinstance(avg_temp_cond, (int,float)) and avg_temp_cond > 25 and "опади" not in cond_f: cond_f, icon_f = "Спекотно", "bi-thermometer-sun"
                
                forecast_list.append({"day": day_label, "icon": icon_f, 
                                    "temp_high": f"{temp_h_d:.1f}°C" if pd.notna(temp_h_d) and isinstance(temp_h_d, (int,float)) else "N/A", 
                                    "temp_low": f"{temp_l_n:.1f}°C" if pd.notna(temp_l_n) and isinstance(temp_l_n, (int,float)) else "N/A", 
                                    "condition": cond_f, "pressure_trend_effect": press_eff})
            
            while len(forecast_list) < 3:
                idx = len(forecast_list); base_t_dummy = cur_temp if isinstance(cur_temp, (int, float)) else 15.0
                forecast_list.append({"day": ["Завтра", "Післязавтра", "Через 2 дні"][idx], "icon": "bi-question-circle", "temp_high": f"{base_t_dummy + idx + 1:.1f}°C", "temp_low": f"{base_t_dummy - idx:.1f}°C", "condition": "Дані відсутні (заглушка)", "pressure_trend_effect": ""})

    current_weather_data = {
        "location": loc_name,
        "temperature": f"{cur_temp:.1f}°C" if isinstance(cur_temp, (int,float)) else "N/A",
        "condition": "На основі даних датчика" if loc_name != "Невідомо" else "Дані відсутні",
        "icon": "bi-thermometer-half",
        "humidity": f"{cur_hum:.1f}%" if isinstance(cur_hum, (int,float)) else "N/A",
        "pressure": f"{cur_press:.1f} гПа" if isinstance(cur_press, (int,float)) else "N/A",
        "pressure_trend": press_trend,
        "dew_point": f"{dew_p:.1f}°C" if isinstance(dew_p, (int,float)) else "N/A",
    }
    if not forecast_list:
        base_t_dummy = cur_temp if isinstance(cur_temp, (int, float)) else 15.0
        for i in range(3):
            forecast_list.append({"day": ["Завтра", "Післязавтра", "Через 2 дні"][i], "icon": "bi-question-lg", "temp_high": f"{base_t_dummy + i + random.uniform(0,1):.1f}°C", "temp_low": f"{base_t_dummy - i - random.uniform(0,1):.1f}°C", "condition": "Прогноз недоступний", "pressure_trend_effect": ""})

    print(f"[WEATHER PAGE V6] Дані для шаблону: current={current_weather_data}, forecast={forecast_list}")
    return render_template("weather.html", active_page="weather",
                           current_weather=current_weather_data, forecast_data=forecast_list)

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
            clear_models_for_mac_from_cache(mac_to_del)
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
    log_path = os.path.join(LOGS_DIR_MAIN, f"{log_file_mac}.log")
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
    print(f"💡 Підказка: моделі NeuralProphet навчаються при відвідуванні сторінки 'Пристрої'.")
    print(f"💡 Частота даних для NP (MODEL_DATA_FREQUENCY в ml_weather.py): {MODEL_DATA_FREQUENCY} (ВАЖЛИВО налаштувати!)")
    serve(app, host=HOST, port=SERVER_HTTP_PORT, threads=10)
