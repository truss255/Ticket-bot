from functools import wraps
from flask import request, jsonify
import time
from collections import defaultdict
import logging

logger = logging.getLogger(__name__)

class RateLimiter:
    def __init__(self, calls=100, period=60):
        self.calls = calls  # Number of calls allowed
        self.period = period  # Time period in seconds
        self.records = defaultdict(list)
    
    def __call__(self, f):
        @wraps(f)
        def decorated(*args, **kwargs):
            client_ip = request.remote_addr
            now = time.time()
            
            # Clean old records
            self.records[client_ip] = [t for t in self.records[client_ip] if now - t < self.period]
            
            # Check rate limit
            if len(self.records[client_ip]) >= self.calls:
                logger.warning(f"Rate limit exceeded for IP: {client_ip}")
                return jsonify({
                    "error": "Rate limit exceeded",
                    "retry_after": self.period - (now - self.records[client_ip][0])
                }), 429
            
            self.records[client_ip].append(now)
            return f(*args, **kwargs)
        return decorated