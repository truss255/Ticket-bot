from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.events import EVENT_JOB_ERROR
from myapp.config import Config
import atexit
import logging

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler()

def job_error_listener(event):
    """Handle job execution errors"""
    logger.error(f"Job failed: {event.job_id} - {event.exception}")

def start_scheduler(app=None):
    """Initialize and start the background scheduler."""
    try:
        # Add error listener
        scheduler.add_listener(job_error_listener, EVENT_JOB_ERROR)
        
        # Add some basic jobs
        scheduler.add_job(
            func=daily_cleanup,
            trigger='cron',
            hour=0,
            minute=0,
            id='daily_cleanup'
        )
        
        scheduler.add_job(
            func=weekly_summary,
            trigger='cron',
            day_of_week='mon',
            hour=9,
            minute=0,
            id='weekly_summary'
        )
        
        scheduler.start()
        atexit.register(lambda: scheduler.shutdown(wait=False))
        logger.info("✅ Scheduler started successfully")
        
    except Exception as e:
        logger.error(f"❌ Failed to start scheduler: {e}")
        raise

def weekly_summary():
    """Generate weekly summary"""
    logger.info("Generating weekly summary...")
    # Add your weekly summary logic here

def daily_cleanup():
    """Perform daily cleanup tasks"""
    logger.info("Performing daily cleanup...")
    # Add your cleanup logic here


