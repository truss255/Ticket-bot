import os
import time
import atexit
from flask import Flask, request, jsonify
from dotenv import load_dotenv

# Attempt to import the config module, fallback to environment variables if missing
try:
    from config import SLACK_BOT_TOKEN, DATABASE_URL, TIMEZONE, SYSTEM_ISSUES_CHANNEL
except ModuleNotFoundError:
    SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
    DATABASE_URL = os.getenv("DATABASE_URL")
    TIMEZONE = os.getenv("TIMEZONE", "UTC")
    SYSTEM_ISSUES_CHANNEL = os.getenv("SYSTEM_ISSUES_CHANNEL")
    if not SLACK_BOT_TOKEN or not DATABASE_URL:
        raise ImportError("The 'config' module is missing, and required environment variables are not set.")

from database import db_pool, init_db
from slack_client import client
from new_modal import build_new_ticket_modal, build_ticket_confirmation_modal
from utils import send_dm, is_authorized_user, export_tickets
from scheduler import scheduler

load_dotenv()
app = Flask(__name__)
app.start_time = time.time()

# Configure upload folder
UPLOAD_FOLDER = 'uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Initialize database
init_db()

# Routes
@app.route('/', methods=['GET'])
def index():
    return jsonify({
        "status": "ok",
        "message": "Ticket Bot is running",
        "endpoints": [
            "/api/tickets/slack/interactivity",
            "/api/tickets/system-tickets",
            "/api/tickets/ticket-summary",
            "/api/tickets/new-ticket"
        ]
    })

@app.route('/upload', methods=['POST'])
def upload_file():
    from werkzeug.utils import secure_filename
    if 'picture' not in request.files:
        return jsonify({"error": "No file part"}), 400
    file = request.files['picture']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400
    if file:
        filename = secure_filename(file.filename)
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)
        file_url = f"{request.url_root}static/uploads/{filename}"
        return jsonify({"file_url": file_url}), 200

@app.route('/slack/events', methods=['POST'])
def slack_events():
    payload = request.json
    if payload.get("type") == "url_verification":
        return jsonify({"challenge": payload.get("challenge")})
    return jsonify({"ok": True})

@app.route('/api/tickets/new-ticket', methods=['POST'])
def new_ticket():
    return new_ticket_command(request, client, db_pool)

@app.route('/health', methods=['GET'])
def health_check():
    db_status = "ok"
    try:
        conn = db_pool.getconn()
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.fetchone()
    except Exception as e:
        db_status = f"error: {str(e)}"
    finally:
        if 'conn' in locals():
            db_pool.putconn(conn)
    slack_status = "ok"
    try:
        client.auth_test()
    except Exception as e:
        slack_status = f"error: {str(e)}"
    return jsonify({
        "status": "ok",
        "timestamp": datetime.now().isoformat(),
        "uptime": time.time() - app.start_time,
        "database": db_status,
        "slack": slack_status
    })

@app.route('/api/tickets/slack/events', methods=['POST'])
def handle_events():
    data = request.json
    if data.get("type") == "url_verification":
        return jsonify({"challenge": data.get("challenge")})
    return jsonify({"status": "ok"})

@app.route('/api/tickets/slack/interactivity', methods=['POST'])
def interactivity():
    return handle_interactivity(request, client, db_pool)

@app.route('/api/tickets/system-tickets', methods=['POST'])
def system_tickets():
    user_id = request.form.get('user_id')
    if not user_id or not is_authorized_user(user_id):
        return jsonify({"text": "❌ You are not authorized to view system tickets."}), 200
    trigger_id = request.form.get('trigger_id')
    modal = {
        "type": "modal",
        "title": {"type": "plain_text", "text": "System Tickets", "emoji": True},
        "close": {"type": "plain_text", "text": "Close", "emoji": True},
        "blocks": [
            {"type": "header", "text": {"type": "plain_text", "text": "System Tickets", "emoji": True}},
            {"type": "section", "text": {"type": "mrkdwn", "text": "Dynamic filtering coming soon."}},
            {"type": "actions", "elements": [
                {"type": "button", "text": {"type": "plain_text", "text": "Export Tickets", "emoji": True},
                 "action_id": "export_tickets", "value": "export"}
            ]}
        ]
    }
    if trigger_id:
        client.views_open(trigger_id=trigger_id, view=modal)
        return "", 200
    return jsonify({"response_type": "ephemeral", "blocks": modal["blocks"]}), 200

@app.route('/api/tickets/ticket-summary', methods=['POST'])
def ticket_summary():
    user_id = request.form.get('user_id')
    if not user_id or not is_authorized_user(user_id):
        return jsonify({"text": "❌ You are not authorized to view ticket summary."}), 200
    conn = db_pool.getconn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM tickets"); total = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM tickets WHERE status = 'Open'"); open_t = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM tickets WHERE status = 'In Progress'"); in_progress = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM tickets WHERE status = 'Resolved'"); resolved = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM tickets WHERE status = 'Closed'"); closed = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM tickets WHERE priority = 'High'"); high = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM tickets WHERE assigned_to = 'Unassigned'"); unassigned = cur.fetchone()[0]
    finally:
        db_pool.putconn(conn)
    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": "Ticket Summary"}},
        {"type": "section", "text": {"type": "mrkdwn",
                                      "text": f"*Total Tickets:* {total}\n*Open:* {open_t}\n*In Progress:* {in_progress}\n*Resolved:* {resolved}\n*Closed:* {closed}\n*High Priority:* {high}\n*Unassigned:* {unassigned}"}}
    ]
    return jsonify({"response_type": "ephemeral", "blocks": blocks}), 200

if __name__ == "__main__":
    scheduler.start()
    atexit.register(lambda: scheduler.shutdown())
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))