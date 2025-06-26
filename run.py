# run.py
import threading
from waitress import serve
from iot_server import create_app, config, utils
from iot_server.beacon import udp_server_beacon_broadcaster
import os

app = create_app()

if __name__ == "__main__":
    # Запускаємо UDP маячок в окремому потоці
    beacon_thread = threading.Thread(target=udp_server_beacon_broadcaster, daemon=True)
    beacon_thread.start()

    # Виводимо інформацію про запуск
    HOST = "0.0.0.0"
    server_ip_for_print = utils.get_local_ip()
    print(f"🌍 Веб-сервер запускається на http://{server_ip_for_print}:{config.SERVER_HTTP_PORT} (або http://{HOST}:{config.SERVER_HTTP_PORT})")
    print(f"🔑 Логін: {config.USERNAME}, Пароль: {config.PASSWORD}")
    print(f"💾 Файл даних пристроїв: {os.path.abspath(config.DATA_FILE)}")
    print(f"📜 Каталог логів: {os.path.abspath(config.LOGS_DIR_MAIN)}")

    # Запускаємо веб-сервер
    serve(app, host=HOST, port=config.SERVER_HTTP_PORT, threads=10)
