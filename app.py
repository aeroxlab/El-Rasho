import os
import uuid
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
    # Render/Heroku sometimes uses postgres://; SQLAlchemy expects postgresql://
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
    permission = db.Column(db.String(20), default="reader")  # reader/editor for passenger
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
    return {"current_user": current_user(), "now": datetime.now()}


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
        return db.session.get(User, passenger.owner_id)
    return User.query.filter_by(role="admin").first()


def pending_total(passenger_id):
    trips = Trip.query.filter_by(passenger_id=passenger_id, status="pending").all()
    return sum(float(t.price or 0) for t in trips)


def build_public_url(passenger):
    return url_for("public_passenger", token=passenger.public_token, _external=True)


def build_whatsapp_url(passenger):
    phone = normalize_phone(passenger.phone)
    total = pending_total(passenger.id)
    text = (
        f"Hola {passenger.full_name}, te comparto el detalle de tus carreras pendientes en El Rasho. "
        f"Total pendiente: S/ {total:.2f}. Revisa tu detalle aquí: {build_public_url(passenger)}"
    )
    return f"https://wa.me/{phone}?text={quote(text)}" if phone else "#"


def get_owned_passengers(owner_id):
    return User.query.filter_by(role="passenger", owner_id=owner_id).order_by(User.created_at.desc()).all()


def create_user(username, password, role, full_name, phone=None, email=None, owner_id=None, permission="reader"):
    username = (username or "").strip()
    if not username:
        raise ValueError("El usuario es obligatorio.")
    if User.query.filter_by(username=username).first():
        raise ValueError("Ese usuario ya existe. Usa otro usuario.")
    user = User(
        username=username,
        role=role,
        full_name=(full_name or "").strip() or username,
        phone=(phone or "").strip(),
        email=(email or "").strip(),
        owner_id=owner_id,
        permission=permission if permission in ["reader", "editor"] else "reader",
        public_token=uuid.uuid4().hex if role == "passenger" else None,
    )
    user.set_password(password or "123456")
    db.session.add(user)
    db.session.commit()
    if role in ["admin", "driver"]:
        ensure_payment_profile(user.id)
    return user


def create_initial_admin():
    db.create_all()
    admin = User.query.filter_by(username="73221820").first()
    if not admin:
        admin = create_user(
            username="73221820",
            password="jdiazg20",
            role="admin",
            full_name="Admin Maestro El Rasho",
            phone="",
            email="",
        )
        ensure_payment_profile(admin.id)
    else:
        admin.role = "admin"
        admin.active = True
        # Mantener la clave maestra siempre funcional.
        if not admin.check_password("jdiazg20"):
            admin.set_password("jdiazg20")
        db.session.commit()


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
    flash(f"Bienvenido, {user.full_name}.", "success")
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
    total_general = sum(float(t.price or 0) for t in Trip.query.filter_by(status="pending").all())
    return render_template(
        "admin_dashboard.html",
        drivers=drivers,
        own_passengers=own_passengers,
        all_passengers=all_passengers,
        all_trips=all_trips,
        profile=profile,
        total_general=total_general,
        build_whatsapp_url=build_whatsapp_url,
        pending_total=pending_total,
    )


@app.route("/driver")
@login_required(["driver"])
def driver_dashboard():
    driver = current_user()
    passengers = get_owned_passengers(driver.id)
    trips = Trip.query.filter_by(owner_id=driver.id).order_by(Trip.created_at.desc()).limit(80).all()
    profile = ensure_payment_profile(driver.id)
    total_driver = sum(float(t.price or 0) for t in Trip.query.filter_by(owner_id=driver.id, status="pending").all())
    return render_template(
        "driver_dashboard.html",
        passengers=passengers,
        trips=trips,
        profile=profile,
        total_driver=total_driver,
        build_whatsapp_url=build_whatsapp_url,
        pending_total=pending_total,
    )


@app.route("/passenger")
@login_required(["passenger"])
def passenger_dashboard():
    passenger = current_user()
    owner = passenger_owner(passenger)
    profile = ensure_payment_profile(owner.id)
    trips = Trip.query.filter_by(passenger_id=passenger.id).order_by(Trip.created_at.desc()).all()
    return render_template(
        "passenger_dashboard.html",
        passenger=passenger,
        owner=owner,
        profile=profile,
        trips=trips,
        total=pending_total(passenger.id),
        public_url=build_public_url(passenger),
    )


@app.route("/admin/create-driver", methods=["POST"])
@login_required(["admin"])
def admin_create_driver():
    try:
        create_user(
            username=request.form.get("username"),
            password=request.form.get("password"),
            role="driver",
            full_name=request.form.get("full_name"),
            phone=request.form.get("phone"),
            email=request.form.get("email"),
            owner_id=current_user().id,
        )
        flash("Conductor creado correctamente.", "success")
    except ValueError as e:
        flash(str(e), "danger")
    return redirect(url_for("admin_dashboard"))


@app.route("/create-passenger", methods=["POST"])
@login_required(["admin", "driver"])
def create_passenger_route():
    actor = current_user()
    try:
        create_user(
            username=request.form.get("username"),
            password=request.form.get("password"),
            role="passenger",
            full_name=request.form.get("full_name"),
            phone=request.form.get("phone"),
            email=request.form.get("email"),
            owner_id=actor.id,
            permission=request.form.get("permission", "reader"),
        )
        flash("Pasajero creado correctamente.", "success")
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
        flash("No se puede bloquear al admin maestro.", "warning")
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
        flash("No se puede eliminar al admin maestro.", "warning")
        return redirect(request.referrer or url_for("admin_dashboard"))
    if actor.role == "driver" and (user.role != "passenger" or user.owner_id != actor.id):
        abort(403)
    # Borrado lógico: se oculta/bloquea sin perder historial.
    user.active = False
    user.username = f"archivado_{user.id}_{user.username}"
    db.session.commit()
    flash("Usuario archivado y acceso desactivado.", "success")
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
@login_required(["admin"])
def delete_trip(trip_id):
    trip = db.session.get(Trip, trip_id)
    if not trip:
        abort(404)
    db.session.delete(trip)
    db.session.commit()
    flash("Carrera eliminada correctamente.", "success")
    return redirect(request.referrer or url_for("admin_dashboard"))


@app.route("/payment/<int:owner_id>/save", methods=["POST"])
@login_required(["admin", "driver"])
def save_payment(owner_id):
    actor = current_user()
    owner = db.session.get(User, owner_id)
    if not owner or owner.role not in ["admin", "driver"]:
        abort(404)
    # Admin puede editar su QR y el de conductores. Conductor solo su propio QR.
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
    profile.card_title = request.form.get("card_title", "Pago El Rasho").strip()
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
    return render_template(
        "public_passenger.html",
        passenger=passenger,
        owner=owner,
        profile=profile,
        trips=trips,
        total=pending_total(passenger.id),
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

    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    y = height - 25 * mm
    pdf.setFont("Helvetica-Bold", 20)
    pdf.drawString(20 * mm, y, "EL RASHO")
    pdf.setFont("Helvetica", 10)
    pdf.drawString(20 * mm, y - 6 * mm, "Ticket de carreras pendientes")

    y -= 20 * mm
    pdf.setFont("Helvetica-Bold", 11)
    pdf.drawString(20 * mm, y, f"Cliente: {passenger.full_name}")
    y -= 6 * mm
    pdf.setFont("Helvetica", 10)
    pdf.drawString(20 * mm, y, f"Celular: {passenger.phone or '-'}")
    y -= 6 * mm
    pdf.drawString(20 * mm, y, f"Responsable de cobro: {owner.full_name}")
    y -= 6 * mm
    pdf.drawString(20 * mm, y, f"Emitido: {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    y -= 10 * mm

    pdf.setFont("Helvetica-Bold", 10)
    pdf.drawString(20 * mm, y, "Fecha")
    pdf.drawString(50 * mm, y, "Origen")
    pdf.drawString(95 * mm, y, "Destino")
    pdf.drawString(150 * mm, y, "Estado")
    pdf.drawRightString(190 * mm, y, "Precio")
    y -= 5 * mm
    pdf.line(20 * mm, y, 190 * mm, y)
    y -= 6 * mm

    pdf.setFont("Helvetica", 9)
    total = 0
    for trip in trips:
        if y < 35 * mm:
            pdf.showPage()
            y = height - 25 * mm
            pdf.setFont("Helvetica", 9)
        fecha = trip.created_at.strftime("%d/%m %H:%M")
        price = float(trip.price or 0)
        if trip.status == "pending":
            total += price
        pdf.drawString(20 * mm, y, fecha)
        pdf.drawString(50 * mm, y, (trip.origin or "-")[:24])
        pdf.drawString(95 * mm, y, (trip.destination or "-")[:30])
        pdf.drawString(150 * mm, y, trip.status.upper())
        pdf.drawRightString(190 * mm, y, f"S/ {price:.2f}")
        y -= 6 * mm

    y -= 5 * mm
    pdf.line(20 * mm, y, 190 * mm, y)
    y -= 10 * mm
    pdf.setFont("Helvetica-Bold", 14)
    pdf.drawRightString(190 * mm, y, f"TOTAL PENDIENTE: S/ {total:.2f}")
    y -= 12 * mm

    pdf.setFont("Helvetica-Bold", 11)
    pdf.drawString(20 * mm, y, "Datos de pago")
    y -= 6 * mm
    pdf.setFont("Helvetica", 10)
    pdf.drawString(20 * mm, y, f"Titular: {profile.titular or '-'}")
    y -= 6 * mm
    pdf.drawString(20 * mm, y, f"Número: {profile.payment_number or '-'}")
    y -= 6 * mm
    pdf.drawString(20 * mm, y, f"Mensaje: {profile.payment_message or '-'}")

    if profile.qr_filename:
        qr_path = os.path.join(UPLOAD_FOLDER, profile.qr_filename)
        if os.path.exists(qr_path):
            try:
                pdf.drawImage(ImageReader(qr_path), 150 * mm, 40 * mm, width=35 * mm, height=35 * mm, preserveAspectRatio=True, mask='auto')
            except Exception:
                pass

    pdf.setFont("Helvetica", 8)
    pdf.drawCentredString(width / 2, 12 * mm, "El Rasho - Control de carreras y créditos")
    pdf.save()
    buffer.seek(0)
    filename = f"ticket_el_rasho_{passenger.full_name.replace(' ', '_')}.pdf"
    return send_file(buffer, as_attachment=True, download_name=filename, mimetype="application/pdf")


@app.errorhandler(403)
def forbidden(_):
    return render_template("error.html", title="Acceso no permitido", message="No tienes permiso para abrir esta sección."), 403


@app.errorhandler(404)
def not_found(_):
    return render_template("error.html", title="No encontrado", message="No se encontró la información solicitada."), 404


with app.app_context():
    create_initial_admin()


if __name__ == "__main__":
    app.run(debug=True)
