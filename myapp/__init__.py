from flask import Flask, jsonify, request, redirect
from myapp.config import Config
from myapp.routes import setup_routes
from myapp.utils.slack_client import verify_slack_connection
from myapp.services.scheduler_service import start_scheduler
from myapp.utils.middleware import SecurityHeadersMiddleware, RequestLoggingMiddleware
import logging

logger = logging.getLogger(__name__)

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # Apply middlewares
    app.wsgi_app = SecurityHeadersMiddleware(app.wsgi_app)
    app.wsgi_app = RequestLoggingMiddleware(app.wsgi_app)

    # Force HTTPS in production
    if app.config['RAILWAY_ENVIRONMENT_NAME'] == 'production':
        @app.before_request
        def force_https():
            if not request.is_secure:
                url = request.url.replace('http://', 'https://', 1)
                return redirect(url, code=301)

    # Setup logging
    logging.basicConfig(level=logging.INFO)
    
    # Register error handlers
    @app.errorhandler(404)
    def not_found_error(error):
        return jsonify({"error": "Not found", "status": 404}), 404

    @app.errorhandler(500)
    def internal_error(error):
        logger.error(f"Internal error: {error}")
        return jsonify({"error": "Internal server error", "status": 500}), 500

    @app.errorhandler(Exception)
    def handle_exception(error):
        logger.error(f"Unhandled exception: {error}")
        return jsonify({"error": "Internal server error", "status": 500}), 500
    
    # Verify Slack connection but don't fail if it's not available
    try:
        if not verify_slack_connection():
            logger.warning("⚠️ Failed to connect to Slack - some features may be limited")
    except Exception as e:
        logger.warning(f"⚠️ Slack verification error: {e} - continuing anyway")

    # Setup routes
    setup_routes(app)
    
    # Start scheduler
    try:
        start_scheduler(app)
    except Exception as e:
        logger.warning(f"⚠️ Failed to start scheduler: {e} - continuing anyway")
    
    logger.info("✅ Application initialized successfully")
    return app
