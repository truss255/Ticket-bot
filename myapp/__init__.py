from flask import Flask
from myapp.config import Config
from myapp.routes import setup_routes
from myapp.utils.slack_client import verify_slack_connection
from myapp.services.scheduler_service import start_scheduler
import logging

logger = logging.getLogger(__name__)

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # Setup logging
    logging.basicConfig(level=logging.INFO)
    
    # Verify Slack connection
    if not verify_slack_connection():
        logger.error("Failed to connect to Slack")
        raise RuntimeError("Slack connection failed")

    # Setup routes
    setup_routes(app)
    
    # Start scheduler
    start_scheduler(app)
    
    logger.info("Application initialized successfully")
    return app
