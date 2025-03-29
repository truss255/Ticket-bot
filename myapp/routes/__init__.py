from flask import Blueprint, jsonify
from myapp.utils.health import check_system_health
from myapp.config import Config

def setup_routes(app):
    """Register all Flask blueprints with the application."""
    
    @app.route("/health")
    def health_check():
        health_data = check_system_health()
        
        # Add Railway-specific information
        health_data.update({
            "deployment": Config.get_deployment_info(),
            "config": {
                "workers": Config.WORKERS,
                "threads": Config.THREADS,
                "timeout": Config.TIMEOUT
            }
        })
        
        status_code = 200 if health_data["status"] == "healthy" else 503
        return jsonify(health_data), status_code
        
    app.register_blueprint(ticket_blueprint, url_prefix="/api/tickets")
    app.register_blueprint(system_blueprint, url_prefix="/api/system")
