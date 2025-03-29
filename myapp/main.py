from myapp import create_app
from myapp.utils.middleware import RequestLoggingMiddleware
import os
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = create_app()
app.wsgi_app = RequestLoggingMiddleware(app.wsgi_app)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    logger.info(f"Starting application on port {port}")
    app.run(host="0.0.0.0", port=port)