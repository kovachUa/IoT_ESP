# iot_server/routes/web.py
from flask import Blueprint, render_template, request, flash, session, redirect, url_for
from functools import wraps
from .. import config
from ..data_manager import device_manager

# Рядок template_folder видалено звідси.
# Flask автоматично знайде папку templates у каталозі iot_server.
web_bp = Blueprint(
    'web',
    __name__
)

# --- Authentication ---
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session:
            flash("Будь ласка, увійдіть.", "warning")
            return redirect(url_for('web.login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function

@web_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        if username == config.USERNAME and password == config.PASSWORD:
            session["logged_in"] = True
            session.permanent = True
            flash("Вхід виконано!", "success")
            next_url = request.args.get('next') or url_for("web.monitor_page")
            return redirect(next_url)
        else:
            flash("Невірний логін/пароль.", "danger")
    return render_template("login.html")

@web_bp.route("/logout")
def logout():
    session.pop("logged_in", None)
    flash("Ви вийшли.", "info")
    return redirect(url_for("web.login"))

# --- Web Pages ---
@web_bp.route("/")
@login_required
def monitor_page():
    return render_template("monitor.html", active_page="monitor", OFFLINE_TIMEOUT=config.OFFLINE_TIMEOUT)

@web_bp.route("/devices")
@login_required
def devices_page():
    return render_template("index.html", active_page="devices", OFFLINE_TIMEOUT=config.OFFLINE_TIMEOUT)
