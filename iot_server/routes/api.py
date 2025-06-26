# iot_server/routes/api.py
from flask import Blueprint, jsonify, request
from .web import login_required  # Імпортуємо декоратор з веб-маршрутів
from ..data_manager import device_manager

# Для API для сторонніх додатків в майбутньому тут можна буде додати
# аутентифікацію за токеном замість сесій
# from .auth_api import token_required

api_bp = Blueprint('api', __name__, url_prefix='/api')

@api_bp.route("/devices")
@login_required # Цей ендпоінт використовується фронтендом, тому вимагає логіну
def get_devices_api():
    """Повертає список пристроїв, попередньо видаливши застарілі."""
    device_manager.cleanup_offline_devices()
    all_devices = device_manager.get_all_devices()
    return jsonify(all_devices)

@api_bp.route("/data", methods=["POST"])
# @token_required - в майбутньому для захисту
def receive_data():
    """
    Приймає дані від IoT пристроїв.
    Цей ендпоінт не вимагає логіну, оскільки пристрої не мають сесії.
    Він має бути відкритим або захищеним іншим методом (API-ключ, токен).
    """
    if not request.is_json:
        return jsonify({"status": "error", "message": "JSON data expected"}), 400

    payload = request.get_json()
    success, message = device_manager.update_device_data(payload, request.remote_addr)

    if success:
        return jsonify({"status": "ok", "message": message}), 200
    else:
        return jsonify({"status": "error", "message": message}), 400
