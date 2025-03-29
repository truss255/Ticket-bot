import psutil
import logging
import requests
from myapp.utils.slack_client import verify_slack_connection
from myapp.services.scheduler_service import scheduler
from myapp.config import Config

logger = logging.getLogger(__name__)

def check_domain_health():
    """Check if the domain is accessible"""
    try:
        response = requests.get(
            f"https://{Config.APP_DOMAIN}/health",
            timeout=5,
            headers={'User-Agent': f'HealthCheck/{Config.RAILWAY_SERVICE_NAME}'}
        )
        return response.status_code == 200
    except Exception as e:
        logger.error(f"Domain health check failed: {e}")
        return False

def check_system_health():
    """Check system resources and application components."""
    try:
        memory = psutil.virtual_memory()
        cpu = psutil.cpu_percent(interval=1)
        disk = psutil.disk_usage('/')
        
        return {
            "status": "healthy",
            "system": {
                "memory_used_percent": memory.percent,
                "cpu_used_percent": cpu,
                "disk_used_percent": disk.percent,
            },
            "components": {
                "slack": verify_slack_connection(),
                "scheduler": scheduler.running,
                "domain": check_domain_health()
            },
            "domain": {
                "name": Config.APP_DOMAIN,
                "url": Config.APP_URL,
                "environment": Config.RAILWAY_ENVIRONMENT_NAME
            },
            "metrics": {
                "memory_warning": memory.percent > 80,
                "cpu_warning": cpu > 80,
                "disk_warning": disk.percent > 80
            }
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {"status": "degraded", "error": str(e)}
