from functools import wraps
from flask import request, abort
import hmac
import hashlib
import time
from myapp.config import Config
import logging

logger = logging.getLogger(__name__)

def verify_slack_signature(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        timestamp = request.headers.get('X-Slack-Request-Timestamp', '')
        signature = request.headers.get('X-Slack-Signature', '')
        
        # Check timestamp to prevent replay attacks
        if abs(time.time() - int(timestamp)) > 60 * 5:
            logger.warning("Slack request timestamp too old")
            abort(403)
            
        # Verify signature
        sig_basestring = f"v0:{timestamp}:{request.get_data().decode()}"
        my_signature = 'v0=' + hmac.new(
            Config.SLACK_SIGNING_SECRET.encode(),
            sig_basestring.encode(),
            hashlib.sha256
        ).hexdigest()
        
        if not hmac.compare_digest(my_signature, signature):
            logger.warning("Invalid Slack signature")
            abort(403)
            
        return f(*args, **kwargs)
    return decorated_function