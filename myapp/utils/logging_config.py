import logging
import json
from myapp.config import Config

class RailwayJsonFormatter(logging.Formatter):
    def format(self, record):
        log_data = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
            "railway": {
                "environment": Config.RAILWAY_ENVIRONMENT_NAME,
                "service": Config.RAILWAY_SERVICE_NAME,
                "commit": Config.RAILWAY_GIT_COMMIT[:7] if Config.RAILWAY_GIT_COMMIT != 'unknown' else 'unknown'
            }
        }
        
        if hasattr(record, 'request_id'):
            log_data['request_id'] = record.request_id
            
        if record.exc_info:
            log_data['exception'] = self.formatException(record.exc_info)
            
        return json.dumps(log_data)

def setup_railway_logging():
    handler = logging.StreamHandler()
    handler.setFormatter(RailwayJsonFormatter())
    
    root_logger = logging.getLogger()
    root_logger.handlers = []
    root_logger.addHandler(handler)
    
    # Set appropriate log level based on environment
    if Config.RAILWAY_ENVIRONMENT_NAME == 'production':
        root_logger.setLevel(logging.INFO)
    else:
        root_logger.setLevel(logging.DEBUG)