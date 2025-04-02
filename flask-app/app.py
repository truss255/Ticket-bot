import os
import time
import atexit
from flask import Flask, jsonify
from dotenv import load_dotenv
from database import init_db
from scheduler import scheduler
from new_ticket import new_ticket_bp  # Import the new_ticket Blueprint

load_dotenv()
app = Flask(__name__)
app.start_time = time.time()

# Configure upload folder
UPLOAD_FOLDER = 'uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Initialize database
init_db()

# Register Blueprints
app.register_blueprint(new_ticket_bp)  # Register the new_ticket Blueprint

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

if __name__ == "__main__":
    scheduler.start()
    atexit.register(lambda: scheduler.shutdown())
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))