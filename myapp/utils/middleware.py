import time
import logging
from flask import request, g, current_app

logger = logging.getLogger(__name__)

class RequestLoggingMiddleware:
    def __init__(self, app):
        self.app = app

    def __call__(self, environ, start_response):
        path = environ.get('PATH_INFO', '')
        method = environ.get('REQUEST_METHOD', '')
        
        # Skip logging for health checks to reduce noise
        if path == '/health':
            return self.app(environ, start_response)

        start_time = time.time()
        
        def custom_start_response(status, headers, exc_info=None):
            request_time = time.time() - start_time
            status_code = int(status.split()[0])
            logger.info(
                f"{method} {path} {status_code} - {request_time:.2f}s"
            )
            return start_response(status, headers, exc_info)

        return self.app(environ, custom_start_response)

class SecurityHeadersMiddleware:
    def __init__(self, app):
        self.app = app

    def __call__(self, environ, start_response):
        def security_headers_response(status, headers, exc_info=None):
            headers.extend([
                ('Strict-Transport-Security', 'max-age=31536000; includeSubDomains'),
                ('X-Frame-Options', 'SAMEORIGIN'),
                ('X-Content-Type-Options', 'nosniff'),
                ('X-XSS-Protection', '1; mode=block'),
                ('Referrer-Policy', 'strict-origin-when-cross-origin'),
                ('Content-Security-Policy', self.get_csp_policy())
            ])
            return start_response(status, headers, exc_info)
        
        return self.app(environ, security_headers_response)
    
    def get_csp_policy(self):
        domain = current_app.config['APP_DOMAIN']
        return (
            f"default-src 'self' https://{domain}; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: https:; "
            f"connect-src 'self' https://{domain}; "
            "frame-ancestors 'none';"
        )
