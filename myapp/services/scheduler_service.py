from apscheduler.schedulers.background import BackgroundScheduler
from myapp.config import Config
import atexit
import logging

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler()

def start_scheduler(app=None):
    """Initialize and start the background scheduler."""
    scheduler.start()
    atexit.register(lambda: scheduler.shutdown(wait=False))
    logger.info("Scheduler started successfully")

def schedule_weekly_summary():
    """Schedule the weekly summary job."""
    # Add your weekly summary scheduling logic here
    pass

def schedule_daily_cleanup():
    """Schedule daily cleanup tasks."""
    # Add your daily cleanup scheduling logic here
    pass

