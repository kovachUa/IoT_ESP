# iot_server/config.py
import os

# App Config
SECRET_KEY = os.urandom(24)

# Credentials
USERNAME = "admin"
PASSWORD = "1234"

# File Paths
DATA_FILE = "devices.json"
LOGS_DIR_MAIN = "logs"

# Server Settings
OFFLINE_TIMEOUT = 180
SERVER_HTTP_PORT = 5005

# Beacon Settings
SERVER_BEACON_PORT = 50001
SERVER_BEACON_INTERVAL_S = 5
SERVER_BEACON_ID = "MY_UNIQUE_IOT_SERVER_V1"
