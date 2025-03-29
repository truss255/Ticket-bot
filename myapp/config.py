import os
import json
import logging

logger = logging.getLogger(__name__)

class Config:
    # Railway-specific configurations
    RAILWAY_ENVIRONMENT_NAME = os.getenv('RAILWAY_ENVIRONMENT_NAME', 'production')
    RAILWAY_GIT_COMMIT = os.getenv('RAILWAY_GIT_COMMIT', 'unknown')
    RAILWAY_GIT_BRANCH = os.getenv('RAILWAY_GIT_BRANCH', 'main')
    RAILWAY_SERVICE_NAME = os.getenv('RAILWAY_SERVICE_NAME', 'web')
    
    # Domain configuration
    APP_DOMAIN = os.getenv('APP_DOMAIN', 'ticket-bot-production.up.railway.app')
    APP_URL = f"https://{APP_DOMAIN}"
    
    # Security settings for domain
    SESSION_COOKIE_DOMAIN = APP_DOMAIN
    SESSION_COOKIE_SECURE = True
    PREFERRED_URL_SCHEME = 'https'
    
    # Application settings
    DEBUG = RAILWAY_ENVIRONMENT_NAME != 'production'
    TESTING = RAILWAY_ENVIRONMENT_NAME == 'test'
    
    # Gunicorn settings for Railway
    WORKERS = int(os.getenv('GUNICORN_WORKERS', '4'))
    THREADS = int(os.getenv('GUNICORN_THREADS', '2'))
    TIMEOUT = int(os.getenv('GUNICORN_TIMEOUT', '30'))
    
    # Make Slack configs optional with warnings
    SLACK_BOT_TOKEN = os.getenv('SLACK_BOT_TOKEN')
    SLACK_CHANNEL = os.getenv("SLACK_CHANNEL")
    TICKET_STORAGE_CHANNEL = os.getenv("TICKET_STORAGE_CHANNEL")
    
    # Optional environment variables with defaults
    SYSTEM_USERS = os.getenv("SYSTEM_USERS", "").split(",")
    TIMEZONE = os.getenv('TIMEZONE', 'UTC')
    
    # Slack configurations
    SLACK_SIGNING_SECRET = os.getenv('SLACK_SIGNING_SECRET')
    SLACK_BOT_SCOPES = [
        "channels:read",
        "channels:history",
        "chat:write",
        "commands",
        "files:read",
        "pins:write",
        "users:read",
        "im:write",
        "im:history",
        "groups:write"
    ]
    
    @classmethod
    def get_deployment_info(cls):
        """Get Railway deployment information"""
        return {
            "environment": cls.RAILWAY_ENVIRONMENT_NAME,
            "git_commit": cls.RAILWAY_GIT_COMMIT,
            "git_branch": cls.RAILWAY_GIT_BRANCH,
            "service": cls.RAILWAY_SERVICE_NAME,
            "domain": cls.APP_DOMAIN,
            "url": cls.APP_URL
        }

