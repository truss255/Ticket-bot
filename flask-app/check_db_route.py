"""
Utility module for checking database tables
"""

def add_db_check_route(app, db_pool):
    """
    Adds a route to the Flask app for checking database tables
    """
    @app.route('/api/check-db', methods=['GET'])
    def check_db():
        """
        Check database tables and return their status
        """
        from flask import jsonify
        
        try:
            conn = db_pool.getconn()
            cur = conn.cursor()
            
            # Get list of tables
            cur.execute("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = 'public'
            """)
            tables = [row[0] for row in cur.fetchall()]
            
            # Get row counts for each table
            table_counts = {}
            for table in tables:
                cur.execute(f"SELECT COUNT(*) FROM {table}")
                count = cur.fetchone()[0]
                table_counts[table] = count
            
            return jsonify({
                "status": "ok",
                "tables": tables,
                "counts": table_counts
            })
        except Exception as e:
            return jsonify({
                "status": "error",
                "message": str(e)
            }), 500
        finally:
            if 'conn' in locals():
                db_pool.putconn(conn)
    
    return app
