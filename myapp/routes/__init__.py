from flask import Blueprint, jsonify
from myapp.routes.system import system_blueprint
from myapp.routes.ticket import ticket_blueprint

def setup_routes(app):
    """Register all Flask blueprints with the application."""
    
    @app.route("/health")
    def health_check():
        return jsonify({"status": "healthy"}), 200
        
    app.register_blueprint(ticket_blueprint, url_prefix="/api/tickets")
    app.register_blueprint(system_blueprint, url_prefix="/api/system")
