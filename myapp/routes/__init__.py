from flask import Blueprint, jsonify

def setup_routes(app):
    """Register all Flask blueprints with the application."""
    
    @app.route("/health")
    def health_check():
        return jsonify({
            "status": "healthy",
            "message": "Service is running"
        }), 200
        
    app.register_blueprint(ticket_blueprint, url_prefix="/api/tickets")
    app.register_blueprint(system_blueprint, url_prefix="/api/system")
