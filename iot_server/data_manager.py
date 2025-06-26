# iot_server/data_manager.py
import json
import os
from datetime import datetime
from . import config

class DeviceManager:
    def __init__(self, data_file, logs_dir):
        self.data_file = data_file
        self.logs_dir = logs_dir
        self.devices = {}
        self._load_devices()
        self._ensure_logs_dir()

    def _load_devices(self):
        if os.path.exists(self.data_file):
            try:
                with open(self.data_file, "r", encoding="utf-8") as f:
                    self.devices = json.load(f)
                print(f"✅ Пристрої завантажено з {self.data_file}")
            except json.JSONDecodeError:
                print(f"⚠️ JSON помилка читання {self.data_file}. Файл буде перезаписано.")
        else:
            print(f"ℹ️ Файл {self.data_file} не знайдено, буде створено новий.")

    def _save_devices(self):
        try:
            with open(self.data_file, "w", encoding="utf-8") as f:
                json.dump(self.devices, f, indent=2, ensure_ascii=False)
        except IOError as e:
            print(f"❌ Не вдалося зберегти дані пристроїв: {e}")

    def _ensure_logs_dir(self):
        if not os.path.exists(self.logs_dir):
            os.makedirs(self.logs_dir)
            print(f"📁 Створено каталог логів: {os.path.abspath(self.logs_dir)}")

    def get_all_devices(self):
        return self.devices

    def cleanup_offline_devices(self):
        now = datetime.now()
        to_delete = []
        # Створюємо копію для безпечної ітерації
        current_devices_snapshot = list(self.devices.items())

        for mac, dev_info in current_devices_snapshot:
            if not isinstance(dev_info, dict): continue
            last_seen_str = dev_info.get("last_seen")
            if last_seen_str:
                try:
                    last_seen_dt = datetime.strptime(last_seen_str, "%Y-%m-%d %H:%M:%S")
                    if (now - last_seen_dt).total_seconds() > config.OFFLINE_TIMEOUT:
                        to_delete.append(mac)
                except ValueError:
                    to_delete.append(mac) # Видаляємо, якщо дата некоректна
            else:
                to_delete.append(mac) # Видаляємо, якщо немає last_seen

        if not to_delete:
            return False # Нічого не змінилось

        for mac_to_del in to_delete:
            if mac_to_del in self.devices:
                print(f"[DATA MANAGER] Видалення пристрою {mac_to_del} через таймаут.")
                del self.devices[mac_to_del]

        self._save_devices()
        return True # Були оновлення

    def update_device_data(self, payload, remote_addr):
        if not payload or not isinstance(payload, dict) or "mac" not in payload:
            return False, "'mac' required"

        mac_raw = payload.get("mac")
        if not isinstance(mac_raw, str):
            return False, "'mac' must be a string"

        mac_raw = mac_raw.upper()
        if len(mac_raw) == 12 and ':' not in mac_raw and '-' not in mac_raw:
            mac_std = ":".join(mac_raw[i:i+2] for i in range(0, 12, 2))
        else:
            mac_std = mac_raw.replace("-", ":")

        if len(mac_std) != 17 or mac_std.count(':') != 5:
            return False, f"Invalid MAC format: {mac_raw}"

        mac_key = mac_std
        name = payload.get("name", self.devices.get(mac_key, {}).get("name", f"Node_{mac_key.replace(':', '')[-6:]}"))
        data = payload.get("data", {})
        if not isinstance(data, dict):
            data = {}

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_file_mac = mac_key.replace(":", "").lower()
        log_path = os.path.join(self.logs_dir, f"{log_file_mac}.log")
        try:
            with open(log_path, "a", encoding="utf-8") as lf:
                log_entry = {"timestamp": now_str, "data": data, "name_in_payload": payload.get("name")}
                lf.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
        except IOError as e:
            print(f"❌ Не вдалося записати лог для {mac_key}: {e}")

        # Оновлюємо тільки якщо є нові дані, інакше зберігаємо старі
        current_data = self.devices.get(mac_key, {}).get("data", {})
        if data:
            current_data.update(data)

        self.devices[mac_key] = {
            "name": name,
            "data": current_data,
            "last_seen": now_str,
            "ip": remote_addr
        }
        self._save_devices()
        return True, "Data received"

# Створюємо єдиний екземпляр менеджера, який будемо імпортувати в інших місцях
device_manager = DeviceManager(data_file=config.DATA_FILE, logs_dir=config.LOGS_DIR_MAIN)
