from flask import Flask, render_template, request, redirect, url_for, flash
from datetime import datetime
from zoneinfo import ZoneInfo
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import event
import os
web = Flask(__name__)
web.secret_key = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')

# Local timezone for timestamps (change to your city if needed)
LOCAL_TZ = ZoneInfo("Africa/Cairo")

def now_local() -> datetime:
    return datetime.now(LOCAL_TZ)

def now_local_naive() -> datetime:
    # Store as naive local time for SQLite compatibility
    return now_local().replace(tzinfo=None)

# Database configuration
if os.environ.get('DATABASE_URL'):
    # Production database (Heroku Postgres)
    web.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get('DATABASE_URL').replace('postgres://', 'postgresql://')
else:
    # Development database (SQLite)
    os.makedirs(web.instance_path, exist_ok=True)
    db_file_path = os.path.join(web.instance_path, "contact.db")
    web.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_file_path}?timeout=30"
web.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
web.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_pre_ping": True,
    "connect_args": {"timeout": 30, "check_same_thread": False}
}
db = SQLAlchemy(web)

class ContactMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=now_local_naive, nullable=False)

# Initialize database tables once at startup (Flask 3 compatible)
def _ensure_db_and_backup():
    try:
        db.create_all()
    except Exception:
        pass

try:
    with web.app_context():
        _ensure_db_and_backup()
        # Set SQLite pragmas for better concurrency
        engine = db.get_engine()
        @event.listens_for(engine, "connect")
        def set_sqlite_pragma(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute("PRAGMA journal_mode=WAL;")
                cursor.execute("PRAGMA synchronous=NORMAL;")
                cursor.execute("PRAGMA busy_timeout=30000;")
            finally:
                cursor.close()
except Exception:
    pass

@web.context_processor
def inject_globals():
    return {
        "current_year": now_local().year,
    }
@web.route('/')
def home():
    return render_template("home.html")
@web.route('/about/')
def about():
    return render_template("about.html")
@web.route('/projects/')
def projects():
    return render_template("projects.html")

## Admin routes removed per request: messages are accessed directly via the database file.

@web.route('/health')
def health():
    return {'status': 'healthy', 'message': 'Portfolio app is running'}, 200

@web.route('/contact', methods=["GET", "POST"])
@web.route('/contact/', methods=["GET", "POST"])
def contact():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip()
        message = request.form.get("message", "").strip()

        if not name or not email or not message:
            flash("Please fill out all fields.", "error")
            return redirect(url_for("contact"))

        try:
            db.session.add(ContactMessage(name=name, email=email, message=message))
            db.session.commit()
        except Exception as e:
            # First failure: attempt auto-repair (recreate tables) then retry once
            db.session.rollback()
            print("[contact-save-error] first", repr(e))
            try:
                db.drop_all()
                db.create_all()
                db.session.add(ContactMessage(name=name, email=email, message=message))
                db.session.commit()
            except Exception as e2:
                db.session.rollback()
                print("[contact-save-error] retry", repr(e2))
                flash("Could not save your message. Please try again.", "error")
                return redirect(url_for("contact"))

        flash("Thanks! Your message has been sent.", "success")
        return redirect(url_for("contact"))

    return render_template("contact.html")

@web.teardown_appcontext
def shutdown_session(exception=None):
    try:
        db.session.remove()
    except Exception:
        pass
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))
    debug = os.environ.get('FLASK_ENV') != 'production'
    web.run(debug=debug, port=port, use_reloader=False, threaded=False)