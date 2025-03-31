from flask import jsonify

def add_db_check_route(app, db_pool):
    @app.route('/api/check-db', methods=['GET'])
    def check_db():
        try:
            conn = db_pool.getconn()
            cur = conn.cursor()
            cur.execute("SELECT 1")
            result = cur.fetchone()
            cur.close()
            db_pool.putconn(conn)
            return jsonify({"status": "ok", "message": "Database connection successful", "result": result[0]})
        except Exception as e:
            return jsonify({"status": "error", "message": f"Database connection failed: {str(e)}"}), 500

    return app