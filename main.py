from myapp import create_app
from myapp.utils.middleware import RequestLoggingMiddleware
from myapp.utils.logging_config import setup_railway_logging
import os
import logging

# Setup Railway-specific logging
setup_railway_logging()
logger = logging.getLogger(__name__)

app = create_app()
app.wsgi_app = RequestLoggingMiddleware(app.wsgi_app)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    logger.info(f"Starting application on port {port}", extra={
        "railway_startup": True,
        "port": port,
        "environment": app.config["RAILWAY_ENVIRONMENT_NAME"]
    })
    app.run(host="0.0.0.0", port=port)

