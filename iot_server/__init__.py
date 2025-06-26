# iot_server/__init__.py
from flask import Flask
from datetime import datetime
from . import config

def create_app():
    app = Flask(__name__)
    app.config['SECRET_KEY'] = config.SECRET_KEY

    @app.context_processor
    def inject_now():
        return {'now': datetime.utcnow()}

    # Реєстрація Blueprints
    from .routes.web import web_bp
    from .routes.api import api_bp

    app.register_blueprint(web_bp)
    app.register_blueprint(api_bp)

    print("✅ Додаток Flask створено та сконфігуровано.")
    return app
