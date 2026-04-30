import os
import re
import uuid
import random
import unicodedata
from datetime import datetime
from io import BytesIO
from urllib.parse import quote

from flask import (
    Flask, render_template, request, redirect, url_for, flash, session,
    send_file, abort, send_from_directory
)
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
INSTANCE_DIR = os.path.join(BASE_DIR, "instance")
UPLOAD_FOLDER = os.environ.get("MEDIA_FOLDER", os.path.join(INSTANCE_DIR, "uploads"))
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app = Flask(__name__, instance_path=INSTANCE_DIR)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "cambia-esta-clave-en-render")

raw_database_url = os.environ.get("DATABASE_URL")
if raw_database_url:
    if raw_database_url.startswith("postgres://"):
        raw_database_url = raw_database_url.replace("postgres://", "postgresql://", 1)
    app.config["SQLALCHEMY_DATABASE_URI"] = raw_database_url
else:
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///el_rasho.db"

app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}

db = SQLAlchemy(app)


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False)  # admin, driver, passenger
    full_name = db.Column(db.String(140), nullable=False)
    phone = db.Column(db.String(30), nullable=True)
    email = db.Column(db.String(140), nullable=True)
    active = db.Column(db.Boolean, default=True)
    permission = db.Column(db.String(20), default="reader")  # reader/editor
    owner_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    public_token = db.Column(db.String(64), unique=True, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    owner = db.relationship("User", remote_side=[id], backref="owned_users")

    def set_password(self, raw_password: str):
        self.password_hash = generate_password_hash(raw_password)

    def check_password(self, raw_password: str) -> bool:
        return check_password_hash(self.password_hash, raw_password)


class Trip(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    passenger_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    owner_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    origin = db.Column(db.String(180), nullable=False)
    destination = db.Column(db.String(180), nullable=False)
    price = db.Column(db.Float, default=0)
    status = db.Column(db.String(20), default="pending")  # pending, paid, cancelled
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    passenger = db.relationship("User", foreign_keys=[passenger_id], backref="trips")
    owner = db.relationship("User", foreign_keys=[owner_id])


class Advance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    passenger_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    owner_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    amount = db.Column(db.Float, default=0)
    note = db.Column(db.String(220), default="")
    created_by = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    passenger = db.relationship("User", foreign_keys=[passenger_id], backref="advances")
    owner = db.relationship("User", foreign_keys=[owner_id])
    creator = db.relationship("User", foreign_keys=[created_by])


class PaymentProfile(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer, db.ForeignKey("user.id"), unique=True, nullable=False)
    titular = db.Column(db.String(140), default="")
    payment_number = db.Column(db.String(40), default="")
    payment_message = db.Column(db.String(220), default="Paga aquí tus carreras pendientes")
    qr_filename = db.Column(db.String(255), nullable=True)
    color_primary = db.Column(db.String(20), default="#e10600")
    color_secondary = db.Column(db.String(20), default="#ffc400")
    card_title = db.Column(db.String(120), default="Pago El Rasho")
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    owner = db.relationship("User", backref="payment_profile")


# ----------------------------- Helpers -----------------------------

def current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    return db.session.get(User, user_id)


@app.context_processor
def inject_globals():
    return {
        "current_user": current_user(),
        "now": datetime.now(),
    }


def login_required(roles=None):
    def decorator(fn):
        from functools import wraps

        @wraps(fn)
        def wrapper(*args, **kwargs):
            user = current_user()
            if not user:
                flash("Primero inicia sesión.", "warning")
                return redirect(url_for("index"))
            if not user.active:
                session.clear()
                flash("Tu acceso está bloqueado. Comunícate con el administrador.", "danger")
                return redirect(url_for("index"))
            if roles and user.role not in roles:
                abort(403)
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def save_qr_file(file_storage):
    if not file_storage or file_storage.filename == "":
        return None
    if not allowed_file(file_storage.filename):
        flash("El QR debe ser imagen PNG, JPG, JPEG o WEBP.", "danger")
        return None
    filename = secure_filename(file_storage.filename)
    ext = filename.rsplit(".", 1)[1].lower()
    final_name = f"qr_{uuid.uuid4().hex}.{ext}"
    path = os.path.join(UPLOAD_FOLDER, final_name)
    file_storage.save(path)
    return final_name


def ensure_payment_profile(owner_id):
    profile = PaymentProfile.query.filter_by(owner_id=owner_id).first()
    if not profile:
        profile = PaymentProfile(owner_id=owner_id)
        db.session.add(profile)
        db.session.commit()
    return profile


def normalize_phone(phone):
    if not phone:
        return ""
    digits = "".join(ch for ch in str(phone) if ch.isdigit())
    if digits.startswith("51"):
        return digits
    if len(digits) == 9:
        return "51" + digits
    return digits


def slugify_text(text):
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-zA-Z0-9\s_-]", "", text).strip().lower()
    text = re.sub(r"[\s_-]+", "_", text)
    return text or "usuario"


def unique_username(base):
    base = slugify_text(base)[:20] or "usuario"
    candidate = base
    index = 1
    while User.query.filter_by(username=candidate).first():
        candidate = f"{base}_{index}"
        index += 1
    return candidate


def auto_credentials(full_name, phone, role):
    words = [w for w in slugify_text(full_name).split("_") if w]
    first = words[0] if words else role
    second = words[1] if len(words) > 1 else ""
    digits = "".join(ch for ch in str(phone or "") if ch.isdigit())
    end_digits = digits[-3:] if len(digits) >= 3 else f"{random.randint(100, 999)}"

    if role == "passenger":
        username_base = f"{first}_{end_digits}"
        password = f"{first}{end_digits}"
    elif role == "driver":
        username_base = f"{first}_{second or 'taxi'}_{end_digits}"
        password = f"taxi{end_digits}"
    else:
        username_base = f"{first}_{end_digits}"
        password = f"admin{end_digits}"

    return unique_username(username_base), password


def can_manage_passenger(actor, passenger):
    if not actor or not passenger or passenger.role != "passenger":
        return False
    if actor.role == "admin":
        return True
    if actor.role == "driver" and passenger.owner_id == actor.id:
        return True
    return False


def passenger_owner(passenger):
    if passenger and passenger.owner_id:
        owner = db.session.get(User, passenger.owner_id)
        if owner:
            return owner
    return User.query.filter_by(role="admin").first()


def trip_pending_total(passenger_id):
    trips = Trip.query.filter_by(passenger_id=passenger_id, status="pending").all()
    return sum(float(t.price or 0) for t in trips)


def advances_total(passenger_id):
    advances = Advance.query.filter_by(passenger_id=passenger_id).all()
    return sum(float(a.amount or 0) for a in advances)


def balance_total(passenger_id):
    return max(0.0, trip_pending_total(passenger_id) - advances_total(passenger_id))


def passenger_breakdown(passenger_id):
    pending = trip_pending_total(passenger_id)
    advances = advances_total(passenger_id)
    final_total = max(0.0, pending - advances)
    return {
        "pending": pending,
        "advances": advances,
        "total": final_total,
        "has_advance": advances > 0,
    }


def build_public_url(passenger):
    return url_for("public_passenger", token=passenger.public_token, _external=True)


def build_whatsapp_url(passenger):
    phone = normalize_phone(passenger.phone)
    totals = passenger_breakdown(passenger.id)
    text = (
        "Hola, te comparto el detalle de tus carreras:\n"
        f"{build_public_url(passenger)}.\n"
        f"Total pendiente: *S/ {totals['total']:.2f}*"
    )
    return f"https://wa.me/{phone}?text={quote(text)}" if phone else "#"


def get_owned_passengers(owner_id):
    return User.query.filter_by(role="passenger", owner_id=owner_id).order_by(User.created_at.desc()).all()


def get_driver_passenger_count(driver):
    return User.query.filter_by(role="passenger", owner_id=driver.id).count()


def create_user(username, password, role, full_name, phone=None, email=None, owner_id=None, permission="reader"):
    requested_username = (username or "").strip()
    requested_password = (password or "").strip()

    generated_username = False
    generated_password = False

    if not requested_username or not requested_password:
        auto_user, auto_pass = auto_credentials(full_name, phone, role)
        if not requested_username:
            requested_username = auto_user
            generated_username = True
        if not requested_password:
            requested_password = auto_pass
            generated_password = True

    requested_username = requested_username.strip()
    if not requested_username:
        raise ValueError("El usuario es obligatorio.")
    if User.query.filter_by(username=requested_username).first():
        raise ValueError("Ese usuario ya existe. Usa otro usuario.")

    user = User(
        username=requested_username,
        role=role,
        full_name=(full_name or "").strip() or requested_username,
        phone=(phone or "").strip(),
        email=(email or "").strip(),
        owner_id=owner_id,
        permission=permission if permission in ["reader", "editor"] else "reader",
        public_token=uuid.uuid4().hex if role == "passenger" else None,
    )
    user.set_password(requested_password)
    db.session.add(user)
    db.session.commit()
    if role in ["admin", "driver"]:
        ensure_payment_profile(user.id)
    return user, requested_username, requested_password, generated_username, generated_password


# ----------------------------- Routes -----------------------------

@app.route("/")
def index():
    user = current_user()
    if user and user.active:
        if user.role == "admin":
            return redirect(url_for("admin_dashboard"))
        if user.role == "driver":
            return redirect(url_for("driver_dashboard"))
        if user.role == "passenger":
            return redirect(url_for("passenger_dashboard"))
    return render_template("login.html")


@app.route("/login", methods=["POST"])
def login():
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    user = User.query.filter_by(username=username).first()
    if not user or not user.check_password(password):
        flash("Usuario o contraseña incorrectos.", "danger")
        return redirect(url_for("index"))
    if not user.active:
        flash("Tu acceso está bloqueado. Comunícate con el administrador.", "danger")
        return redirect(url_for("index"))
    session["user_id"] = user.id
    if user.role == "admin":
        return redirect(url_for("admin_dashboard"))
    if user.role == "driver":
        return redirect(url_for("driver_dashboard"))
    return redirect(url_for("passenger_dashboard"))


@app.route("/logout")
def logout():
    session.clear()
    flash("Sesión cerrada correctamente.", "info")
    return redirect(url_for("index"))


@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)


@app.route("/admin")
@login_required(["admin"])
def admin_dashboard():
    admin = current_user()
    drivers = User.query.filter_by(role="driver").order_by(User.created_at.desc()).all()
    own_passengers = get_owned_passengers(admin.id)
    all_passengers = User.query.filter_by(role="passenger").order_by(User.created_at.desc()).all()
    all_trips = Trip.query.order_by(Trip.created_at.desc()).limit(80).all()
    profile = ensure_payment_profile(admin.id)
    total_general = sum(balance_total(p.id) for p in all_passengers)
    recent_advances = Advance.query.order_by(Advance.created_at.desc()).limit(60).all()
    return render_template(
        "admin_dashboard.html",
        drivers=drivers,
        own_passengers=own_passengers,
        all_passengers=all_passengers,
        all_trips=all_trips,
        profile=profile,
        total_general=total_general,
        recent_advances=recent_advances,
        build_whatsapp_url=build_whatsapp_url,
        trip_pending_total=trip_pending_total,
        advances_total=advances_total,
        balance_total=balance_total,
        passenger_breakdown=passenger_breakdown,
        get_driver_passenger_count=get_driver_passenger_count,
    )


@app.route("/driver")
@login_required(["driver"])
def driver_dashboard():
    driver = current_user()
    passengers = get_owned_passengers(driver.id)
    trips = Trip.query.filter_by(owner_id=driver.id).order_by(Trip.created_at.desc()).limit(80).all()
    profile = ensure_payment_profile(driver.id)
    total_driver = sum(balance_total(p.id) for p in passengers)
    recent_advances = Advance.query.filter_by(owner_id=driver.id).order_by(Advance.created_at.desc()).limit(60).all()
    return render_template(
        "driver_dashboard.html",
        passengers=passengers,
        trips=trips,
        profile=profile,
        total_driver=total_driver,
        recent_advances=recent_advances,
        build_whatsapp_url=build_whatsapp_url,
        trip_pending_total=trip_pending_total,
        advances_total=advances_total,
        balance_total=balance_total,
        passenger_breakdown=passenger_breakdown,
    )


@app.route("/passenger")
@login_required(["passenger"])
def passenger_dashboard():
    passenger = current_user()
    owner = passenger_owner(passenger)
    profile = ensure_payment_profile(owner.id)
    trips = Trip.query.filter_by(passenger_id=passenger.id).order_by(Trip.created_at.desc()).all()
    advances = Advance.query.filter_by(passenger_id=passenger.id).order_by(Advance.created_at.desc()).all()
    totals = passenger_breakdown(passenger.id)
    return render_template(
        "passenger_dashboard.html",
        passenger=passenger,
        owner=owner,
        profile=profile,
        trips=trips,
        advances=advances,
        totals=totals,
        public_url=build_public_url(passenger),
    )


@app.route("/admin/create-driver", methods=["POST"])
@login_required(["admin"])
def admin_create_driver():
    try:
        user, final_user, final_pass, gen_user, gen_pass = create_user(
            username=request.form.get("username"),
            password=request.form.get("password"),
            role="driver",
            full_name=request.form.get("full_name"),
            phone=request.form.get("phone"),
            email=request.form.get("email"),
            owner_id=current_user().id,
        )
        flash(
            f"Conductor creado correctamente. Usuario: {final_user} · Contraseña: {final_pass}",
            "success"
        )
    except ValueError as e:
        flash(str(e), "danger")
    return redirect(url_for("admin_dashboard"))


@app.route("/create-passenger", methods=["POST"])
@login_required(["admin", "driver"])
def create_passenger_route():
    actor = current_user()
    try:
        user, final_user, final_pass, gen_user, gen_pass = create_user(
            username=request.form.get("username"),
            password=request.form.get("password"),
            role="passenger",
            full_name=request.form.get("full_name"),
            phone=request.form.get("phone"),
            email=request.form.get("email"),
            owner_id=actor.id,
            permission=request.form.get("permission", "reader"),
        )
        flash(
            f"Pasajero creado correctamente. Usuario: {final_user} · Contraseña: {final_pass}",
            "success"
        )
    except ValueError as e:
        flash(str(e), "danger")
    return redirect(url_for("admin_dashboard" if actor.role == "admin" else "driver_dashboard"))


@app.route("/user/<int:user_id>/toggle", methods=["POST"])
@login_required(["admin", "driver"])
def toggle_user(user_id):
    actor = current_user()
    user = db.session.get(User, user_id)
    if not user:
        abort(404)
    if actor.role == "driver" and user.owner_id != actor.id:
        abort(403)
    if actor.role == "driver" and user.role != "passenger":
        abort(403)
    if user.role == "admin":
        flash("No se puede bloquear al usuario maestro.", "warning")
    else:
        user.active = not user.active
        db.session.commit()
        flash("Estado actualizado correctamente.", "success")
    return redirect(request.referrer or url_for("index"))


@app.route("/user/<int:user_id>/delete", methods=["POST"])
@login_required(["admin", "driver"])
def delete_user(user_id):
    actor = current_user()
    user = db.session.get(User, user_id)
    if not user:
        abort(404)
    if user.role == "admin":
        flash("No se puede eliminar al usuario maestro.", "warning")
        return redirect(request.referrer or url_for("admin_dashboard"))
    if actor.role == "driver" and (user.role != "passenger" or user.owner_id != actor.id):
        abort(403)

    user.active = False
    user.username = unique_username(f"archivado_{user.username}")
    db.session.commit()
    flash("Usuario eliminado del panel y archivado correctamente.", "success")
    return redirect(request.referrer or url_for("index"))


@app.route("/trip/create", methods=["POST"])
@login_required(["admin", "driver"])
def create_trip():
    actor = current_user()
    passenger_id = int(request.form.get("passenger_id", 0))
    passenger = db.session.get(User, passenger_id)
    if not can_manage_passenger(actor, passenger):
        abort(403)
    created_at = datetime.utcnow()
    if actor.role == "admin" and request.form.get("created_at"):
        try:
            created_at = datetime.fromisoformat(request.form.get("created_at"))
        except ValueError:
            created_at = datetime.utcnow()
    try:
        price = float(str(request.form.get("price", "0")).replace(",", "."))
    except ValueError:
        price = 0

    trip = Trip(
        passenger_id=passenger.id,
        owner_id=passenger.owner_id,
        origin=request.form.get("origin", "").strip(),
        destination=request.form.get("destination", "").strip(),
        price=price,
        created_at=created_at,
    )
    db.session.add(trip)
    db.session.commit()
    flash("Carrera registrada correctamente.", "success")
    return redirect(request.referrer or url_for("index"))


@app.route("/advance/create", methods=["POST"])
@login_required(["admin", "driver"])
def create_advance():
    actor = current_user()
    passenger_id = int(request.form.get("passenger_id", 0))
    passenger = db.session.get(User, passenger_id)
    if not can_manage_passenger(actor, passenger):
        abort(403)
    try:
        amount = float(str(request.form.get("amount", "0")).replace(",", "."))
    except ValueError:
        amount = 0
    if amount <= 0:
        flash("El adelanto debe ser mayor a cero.", "danger")
        return redirect(request.referrer or url_for("index"))

    advance = Advance(
        passenger_id=passenger.id,
        owner_id=passenger.owner_id,
        amount=amount,
        note=(request.form.get("note") or "").strip(),
        created_by=actor.id,
    )
    db.session.add(advance)
    db.session.commit()
    flash(f"Adelanto registrado correctamente: S/ {amount:.2f}", "success")
    return redirect(request.referrer or url_for("index"))


@app.route("/advance/<int:advance_id>/delete", methods=["POST"])
@login_required(["admin", "driver"])
def delete_advance(advance_id):
    actor = current_user()
    advance = db.session.get(Advance, advance_id)
    if not advance:
        abort(404)
    passenger = db.session.get(User, advance.passenger_id)
    if not can_manage_passenger(actor, passenger):
        abort(403)
    db.session.delete(advance)
    db.session.commit()
    flash("Adelanto eliminado correctamente.", "success")
    return redirect(request.referrer or url_for("index"))


@app.route("/trip/<int:trip_id>/update", methods=["POST"])
@login_required(["admin", "driver", "passenger"])
def update_trip(trip_id):
    actor = current_user()
    trip = db.session.get(Trip, trip_id)
    if not trip:
        abort(404)
    passenger = db.session.get(User, trip.passenger_id)

    if actor.role in ["admin", "driver"]:
        if not can_manage_passenger(actor, passenger):
            abort(403)
        allow_status = True
    else:
        if actor.id != trip.passenger_id or actor.permission != "editor":
            abort(403)
        allow_status = False

    trip.origin = request.form.get("origin", trip.origin).strip()
    trip.destination = request.form.get("destination", trip.destination).strip()
    try:
        trip.price = float(str(request.form.get("price", trip.price)).replace(",", "."))
    except ValueError:
        pass
    if actor.role == "admin" and request.form.get("created_at"):
        try:
            trip.created_at = datetime.fromisoformat(request.form.get("created_at"))
        except ValueError:
            pass
    if allow_status:
        trip.status = request.form.get("status", trip.status)
    db.session.commit()
    flash("Carrera actualizada correctamente.", "success")
    return redirect(request.referrer or url_for("index"))


@app.route("/trip/<int:trip_id>/delete", methods=["POST"])
@login_required(["admin", "driver"])
def delete_trip(trip_id):
    actor = current_user()
    trip = db.session.get(Trip, trip_id)
    if not trip:
        abort(404)
    passenger = db.session.get(User, trip.passenger_id)
    if not can_manage_passenger(actor, passenger):
        abort(403)
    db.session.delete(trip)
    db.session.commit()
    flash("Carrera eliminada correctamente.", "success")
    return redirect(request.referrer or url_for("index"))


@app.route("/payment/<int:owner_id>/save", methods=["POST"])
@login_required(["admin", "driver"])
def save_payment(owner_id):
    actor = current_user()
    owner = db.session.get(User, owner_id)
    if not owner or owner.role not in ["admin", "driver"]:
        abort(404)
    if actor.role == "driver" and owner_id != actor.id:
        abort(403)
    if actor.role == "admin" and owner.role == "driver":
        pass
    elif actor.role == "admin" and owner_id != actor.id:
        abort(403)

    profile = ensure_payment_profile(owner_id)
    profile.titular = request.form.get("titular", "").strip()
    profile.payment_number = request.form.get("payment_number", "").strip()
    profile.payment_message = request.form.get("payment_message", "").strip()
    profile.card_title = request.form.get("card_title", "Pago El Rasho").strip() or "Pago El Rasho"
    profile.color_primary = request.form.get("color_primary", "#e10600").strip() or "#e10600"
    profile.color_secondary = request.form.get("color_secondary", "#ffc400").strip() or "#ffc400"

    if "qr_file" in request.files:
        new_filename = save_qr_file(request.files["qr_file"])
        if new_filename:
            if profile.qr_filename:
                old_path = os.path.join(UPLOAD_FOLDER, profile.qr_filename)
                if os.path.exists(old_path):
                    try:
                        os.remove(old_path)
                    except OSError:
                        pass
            profile.qr_filename = new_filename
    db.session.commit()
    flash("Datos de pago actualizados correctamente.", "success")
    return redirect(request.referrer or url_for("index"))


@app.route("/payment/<int:owner_id>/delete-qr", methods=["POST"])
@login_required(["admin", "driver"])
def delete_qr(owner_id):
    actor = current_user()
    owner = db.session.get(User, owner_id)
    if not owner:
        abort(404)
    if actor.role == "driver" and owner_id != actor.id:
        abort(403)
    if actor.role == "admin" and owner.role not in ["admin", "driver"]:
        abort(403)
    profile = ensure_payment_profile(owner_id)
    if profile.qr_filename:
        path = os.path.join(UPLOAD_FOLDER, profile.qr_filename)
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass
    profile.qr_filename = None
    db.session.commit()
    flash("QR eliminado correctamente.", "success")
    return redirect(request.referrer or url_for("index"))


@app.route("/payment/<int:owner_id>/download-qr")
@login_required(["admin", "driver", "passenger"])
def download_qr(owner_id):
    actor = current_user()
    profile = ensure_payment_profile(owner_id)
    if actor.role == "driver" and owner_id != actor.id:
        abort(403)
    if actor.role == "passenger":
        owner = passenger_owner(actor)
        if owner.id != owner_id:
            abort(403)
    if not profile.qr_filename:
        flash("Aún no hay QR cargado.", "warning")
        return redirect(request.referrer or url_for("index"))
    return send_from_directory(UPLOAD_FOLDER, profile.qr_filename, as_attachment=True)


@app.route("/public/<token>")
def public_passenger(token):
    passenger = User.query.filter_by(public_token=token, role="passenger").first_or_404()
    owner = passenger_owner(passenger)
    profile = ensure_payment_profile(owner.id)
    trips = Trip.query.filter_by(passenger_id=passenger.id).order_by(Trip.created_at.desc()).all()
    advances = Advance.query.filter_by(passenger_id=passenger.id).order_by(Advance.created_at.desc()).all()
    totals = passenger_breakdown(passenger.id)
    return render_template(
        "public_passenger.html",
        passenger=passenger,
        owner=owner,
        profile=profile,
        trips=trips,
        advances=advances,
        totals=totals,
    )


@app.route("/ticket/<int:passenger_id>")
def ticket_pdf(passenger_id):
    passenger = db.session.get(User, passenger_id)
    if not passenger or passenger.role != "passenger":
        abort(404)

    actor = current_user()
    token = request.args.get("token")
    allowed = False
    if actor:
        if actor.role == "admin":
            allowed = True
        elif actor.role == "driver" and passenger.owner_id == actor.id:
            allowed = True
        elif actor.role == "passenger" and actor.id == passenger.id:
            allowed = True
    if token and token == passenger.public_token:
        allowed = True
    if not allowed:
        abort(403)

    owner = passenger_owner(passenger)
    profile = ensure_payment_profile(owner.id)
    trips = Trip.query.filter_by(passenger_id=passenger.id).order_by(Trip.created_at.desc()).all()
    advances = Advance.query.filter_by(passenger_id=passenger.id).order_by(Advance.created_at.asc()).all()
    totals = passenger_breakdown(passenger.id)

    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    brand_red = colors.HexColor(profile.color_primary or "#8d0b00")
    brand_yellow = colors.HexColor(profile.color_secondary or "#ffc400")
    dark = colors.HexColor("#141414")
    light = colors.HexColor("#f8f4ee")
    gray = colors.HexColor("#5f5f5f")

    # Background header
    pdf.setFillColor(brand_red)
    pdf.roundRect(12 * mm, height - 40 * mm, width - 24 * mm, 28 * mm, 7 * mm, fill=1, stroke=0)
    pdf.setFillColor(light)
    pdf.setFont("Helvetica-Bold", 21)
    pdf.drawString(18 * mm, height - 24 * mm, "EL RASHO")
    pdf.setFont("Helvetica", 9)
    pdf.drawString(18 * mm, height - 30 * mm, "Detalle profesional de carreras pendientes")
    pdf.setFont("Helvetica-Bold", 11)
    pdf.setFillColor(brand_yellow)
    pdf.drawRightString(width - 18 * mm, height - 24 * mm, f"Cliente: {passenger.full_name}")

    # Info box
    y = height - 54 * mm
    pdf.setFillColor(light)
    pdf.roundRect(12 * mm, y - 24 * mm, width - 24 * mm, 24 * mm, 5 * mm, fill=1, stroke=0)
    pdf.setFillColor(dark)
    pdf.setFont("Helvetica-Bold", 10)
    pdf.drawString(18 * mm, y - 7 * mm, "Cliente")
    pdf.drawString(78 * mm, y - 7 * mm, "Celular")
    pdf.drawString(132 * mm, y - 7 * mm, "Emitido")
    pdf.setFont("Helvetica", 10)
    pdf.drawString(18 * mm, y - 14 * mm, passenger.full_name)
    pdf.drawString(78 * mm, y - 14 * mm, passenger.phone or "-")
    pdf.drawString(132 * mm, y - 14 * mm, datetime.now().strftime("%d/%m/%Y %H:%M"))

    # Table
    y = height - 86 * mm
    pdf.setFillColor(brand_yellow)
    pdf.roundRect(12 * mm, y, width - 24 * mm, 9 * mm, 3 * mm, fill=1, stroke=0)
    pdf.setFillColor(dark)
    pdf.setFont("Helvetica-Bold", 9)
    pdf.drawString(16 * mm, y + 3 * mm, "Fecha")
    pdf.drawString(50 * mm, y + 3 * mm, "Origen")
    pdf.drawString(91 * mm, y + 3 * mm, "Destino")
    pdf.drawString(142 * mm, y + 3 * mm, "Estado")
    pdf.drawRightString(192 * mm, y + 3 * mm, "Precio")

    y -= 8 * mm
    pdf.setFont("Helvetica", 9)
    row_fill_toggle = False
    for trip in trips:
        if y < 70 * mm:
            pdf.showPage()
            y = height - 24 * mm
        if row_fill_toggle:
            pdf.setFillColor(colors.HexColor("#f5f0ea"))
            pdf.rect(12 * mm, y - 2 * mm, width - 24 * mm, 7 * mm, fill=1, stroke=0)
        row_fill_toggle = not row_fill_toggle
        pdf.setFillColor(dark)
        pdf.drawString(16 * mm, y, trip.created_at.strftime("%d/%m %H:%M"))
        pdf.drawString(50 * mm, y, (trip.origin or "-")[:18])
        pdf.drawString(91 * mm, y, (trip.destination or "-")[:24])
        pdf.drawString(142 * mm, y, trip.status.upper())
        pdf.drawRightString(192 * mm, y, f"S/ {float(trip.price or 0):.2f}")
        y -= 7 * mm

    # Totals box
    y -= 5 * mm
    pdf.setFillColor(dark)
    pdf.roundRect(12 * mm, y - 28 * mm, width - 24 * mm, 28 * mm, 5 * mm, fill=1, stroke=0)
    pdf.setFillColor(light)
    pdf.setFont("Helvetica-Bold", 10)
    pdf.drawString(18 * mm, y - 7 * mm, "Subtotal carreras pendientes")
    pdf.drawRightString(192 * mm, y - 7 * mm, f"S/ {totals['pending']:.2f}")
    pdf.drawString(18 * mm, y - 14 * mm, "Adelantos registrados")
    pdf.drawRightString(192 * mm, y - 14 * mm, f"- S/ {totals['advances']:.2f}")
    pdf.setFillColor(brand_yellow)
    pdf.setFont("Helvetica-Bold", 13)
    pdf.drawString(18 * mm, y - 22 * mm, "TOTAL PENDIENTE FINAL")
    pdf.drawRightString(192 * mm, y - 22 * mm, f"S/ {totals['total']:.2f}")

    y -= 40 * mm
    if totals["has_advance"]:
        pdf.setFillColor(gray)
        pdf.setFont("Helvetica", 9)
        pdf.drawString(12 * mm, y, f"Nota: este cliente tiene adelantos registrados por S/ {totals['advances']:.2f}.")
        y -= 8 * mm

    if advances:
        pdf.setFillColor(brand_red)
        pdf.setFont("Helvetica-Bold", 10)
        pdf.drawString(12 * mm, y, "Historial de adelantos")
        y -= 6 * mm
        pdf.setFont("Helvetica", 8.7)
        for adv in advances[:8]:
            text = f"• {adv.created_at.strftime('%d/%m/%Y %H:%M')} · S/ {float(adv.amount or 0):.2f}"
            if adv.note:
                text += f" · {adv.note[:55]}"
            pdf.setFillColor(dark)
            pdf.drawString(15 * mm, y, text)
            y -= 5 * mm
            if y < 40 * mm:
                break
        y -= 4 * mm

    # Payment box
    pay_box_y = 18 * mm
    pay_box_h = 36 * mm
    pdf.setFillColor(light)
    pdf.roundRect(12 * mm, pay_box_y, width - 24 * mm, pay_box_h, 5 * mm, fill=1, stroke=0)
    pdf.setFillColor(dark)
    pdf.setFont("Helvetica-Bold", 10)
    pdf.drawString(18 * mm, pay_box_y + 28 * mm, profile.card_title or "Pago El Rasho")
    pdf.setFont("Helvetica", 9)
    pdf.drawString(18 * mm, pay_box_y + 22 * mm, profile.payment_message or "Paga aquí tus carreras pendientes")
    pdf.drawString(18 * mm, pay_box_y + 14 * mm, f"Titular: {profile.titular or '-'}")
    pdf.drawString(18 * mm, pay_box_y + 8 * mm, f"Número: {profile.payment_number or '-'}")

    if profile.qr_filename:
        qr_path = os.path.join(UPLOAD_FOLDER, profile.qr_filename)
        if os.path.exists(qr_path):
            try:
                pdf.drawImage(
                    ImageReader(qr_path),
                    width - 48 * mm,
                    pay_box_y + 4 * mm,
                    width=24 * mm,
                    height=24 * mm,
                    preserveAspectRatio=True,
                    mask='auto'
                )
            except Exception:
                pass

    pdf.setFillColor(gray)
    pdf.setFont("Helvetica", 8)
    pdf.drawCentredString(width / 2, 8 * mm, "El Rasho · Ticket detallado de carreras y créditos")
    pdf.save()
    buffer.seek(0)
    safe_name = slugify_text(passenger.full_name).replace("_", "-")
    filename = f"ticket-el-rasho-{safe_name}.pdf"
    return send_file(buffer, as_attachment=True, download_name=filename, mimetype="application/pdf")


@app.errorhandler(403)
def forbidden(_):
    return render_template("error.html", title="Acceso no permitido", message="No tienes permiso para abrir esta sección."), 403


@app.errorhandler(404)
def not_found(_):
    return render_template("error.html", title="No encontrado", message="No se encontró la información solicitada."), 404


def create_initial_admin():
    db.create_all()
    admin = User.query.filter_by(username="73221820").first()
    if not admin:
        admin, _, _, _, _ = create_user(
            username="73221820",
            password="jdiazg20",
            role="admin",
            full_name="Jorge Diaz",
            phone="992657332",
            email="",
        )
    admin.role = "admin"
    admin.full_name = "Jorge Diaz"
    admin.active = True
    admin.public_token = None
    if not admin.check_password("jdiazg20"):
        admin.set_password("jdiazg20")
    db.session.commit()
    ensure_payment_profile(admin.id)

    # Reparar registros antiguos
    passengers = User.query.filter_by(role="passenger").all()
    changed = False
    for passenger in passengers:
        if not passenger.public_token:
            passenger.public_token = uuid.uuid4().hex
            changed = True
    if changed:
        db.session.commit()


with app.app_context():
    create_initial_admin()


if __name__ == "__main__":
    app.run(debug=True)
