import hashlib
import os
from datetime import datetime

import qrcode
from flask import Flask, render_template, request, redirect, url_for, jsonify

from database import get_db, init_db

app = Flask(__name__)
app.secret_key = os.urandom(24)

VIDEO_IDS = {"en": "BF9TB7TIQcI", "es": "ZaHtAiLCark"}

QR_DIR = os.path.join(app.static_folder, "qrcodes")
os.makedirs(QR_DIR, exist_ok=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _generate_qr_hash(participant_id, email):
    """Create a deterministic verification hash for a participant."""
    raw = f"safeset-{participant_id}-{email}-verified"
    return hashlib.sha256(raw.encode()).hexdigest()


def _generate_qr_image(participant_id, email):
    """Generate a QR code PNG and return its URL path."""
    qr_hash = _generate_qr_hash(participant_id, email)
    filename = f"qr_{participant_id}.png"
    filepath = os.path.join(QR_DIR, filename)

    img = qrcode.make(qr_hash)
    img.save(filepath)

    return f"/static/qrcodes/{filename}"


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("register.html")


@app.route("/register", methods=["POST"])
def register():
    full_name = request.form.get("full_name", "").strip()
    email = request.form.get("email", "").strip()
    role = request.form.get("role", "").strip()

    if not full_name or not email or not role:
        return render_template("register.html", error="Please fill in all required fields.")

    language = request.form.get("lang", "en").strip().lower()
    if language not in ("en", "es"):
        language = "en"

    other_role = request.form.get("other_role", "").strip() or None
    minor_name = request.form.get("minor_name", "").strip() or None
    minor_age = request.form.get("minor_age", "").strip() or None
    guardian_name = request.form.get("guardian_name", "").strip() or None

    if minor_age is not None:
        try:
            minor_age = int(minor_age)
        except ValueError:
            minor_age = None

    db = get_db()
    try:
        cursor = db.execute(
            """INSERT INTO participants
               (full_name, email, role, other_role, minor_name, minor_age, guardian_name, language)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (full_name, email, role, other_role, minor_name, minor_age, guardian_name, language),
        )
        db.commit()
        participant_id = cursor.lastrowid
    finally:
        db.close()

    return redirect(url_for("video", participant_id=participant_id))


@app.route("/video/<int:participant_id>")
def video(participant_id):
    db = get_db()
    try:
        row = db.execute("SELECT language FROM participants WHERE id = ?", (participant_id,)).fetchone()
    finally:
        db.close()
    lang = (row["language"] if row and row["language"] else "en")
    video_id = VIDEO_IDS.get(lang, VIDEO_IDS["en"])
    return render_template("video.html", participant_id=participant_id, video_id=video_id, lang=lang)


@app.route("/heartbeat/<int:participant_id>", methods=["POST"])
def heartbeat(participant_id):
    data = request.get_json(silent=True) or {}
    progress = data.get("progress", 0)

    try:
        progress = float(progress)
    except (TypeError, ValueError):
        progress = 0

    progress = max(0.0, min(progress, 100.0))

    db = get_db()
    try:
        db.execute(
            "UPDATE participants SET progress = MAX(progress, ?) WHERE id = ?",
            (progress, participant_id),
        )
        db.commit()
    finally:
        db.close()

    return jsonify({"ok": True, "progress": progress})


@app.route("/complete/<int:participant_id>", methods=["POST"])
def complete(participant_id):
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

    db = get_db()
    try:
        row = db.execute(
            "SELECT id, email FROM participants WHERE id = ?", (participant_id,)
        ).fetchone()

        if row is None:
            return render_template("register.html", error="Participant not found."), 404

        qr_url = _generate_qr_image(row["id"], row["email"])

        db.execute(
            """UPDATE participants
               SET completed = 1, completed_at = ?, progress = 100, qr_code = ?
               WHERE id = ?""",
            (now, qr_url, participant_id),
        )
        db.commit()
    finally:
        db.close()

    return redirect(url_for("qrcode_page", participant_id=participant_id))


@app.route("/qrcode/<int:participant_id>")
def qrcode_page(participant_id):
    db = get_db()
    try:
        row = db.execute(
            "SELECT * FROM participants WHERE id = ?", (participant_id,)
        ).fetchone()
    finally:
        db.close()

    if row is None:
        return render_template("register.html", error="Participant not found."), 404

    return render_template("qrcode.html", participant=row)


@app.route("/verify")
def verify():
    return render_template("verify.html")


@app.route("/scan", methods=["POST"])
def scan():
    data = request.get_json(silent=True) or {}
    qr_value = data.get("qr_code", "").strip()

    if not qr_value:
        return jsonify({
            "verified": False,
            "status": "Invalid",
            "message": "No QR code value provided.",
        }), 400

    db = get_db()
    try:
        rows = db.execute("SELECT * FROM participants WHERE completed = 1").fetchall()
    finally:
        db.close()

    for row in rows:
        expected_hash = _generate_qr_hash(row["id"], row["email"])
        if qr_value == expected_hash:
            return jsonify({
                "verified": True,
                "full_name": row["full_name"],
                "role": row["role"],
                "completed_date": row["completed_at"] or row["created_at"],
            })

    return jsonify({
        "verified": False,
        "status": "Not Found",
        "message": "No matching participant for this QR code.",
    }), 404


@app.route("/lookup")
def lookup():
    q = request.args.get("q", "").strip()

    if not q:
        return jsonify({"results": []})

    pattern = f"%{q}%"

    db = get_db()
    try:
        rows = db.execute(
            """SELECT id, full_name, email, role, completed, qr_code
               FROM participants
               WHERE full_name LIKE ? OR email LIKE ?
               ORDER BY full_name
               LIMIT 20""",
            (pattern, pattern),
        ).fetchall()
    finally:
        db.close()

    results = []
    for row in rows:
        qr_value = ""
        if row["completed"]:
            qr_value = _generate_qr_hash(row["id"], row["email"])
        results.append({
            "full_name": row["full_name"],
            "email": row["email"],
            "role": row["role"],
            "completed": bool(row["completed"]),
            "qr_value": qr_value,
        })

    return jsonify({"results": results})


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=3001, debug=True)
