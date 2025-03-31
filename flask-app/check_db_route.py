from flask import jsonify

def add_db_check_route(app, db_pool):
    """Add a route to check database tables"""
    
    @app.route('/api/check-db', methods=['GET'])
    def check_db():
        try:
            # Get a connection from the pool
            conn = db_pool.getconn()
            try:
                cur = conn.cursor()
                
                # Get list of tables
                cur.execute("""
                    SELECT table_name 
                    FROM information_schema.tables 
                    WHERE table_schema = 'public'
                    ORDER BY table_name;
                """)
                tables = [table[0] for table in cur.fetchall()]
                
                result = {"tables": {}}
                
                # Get details for each table
                for table in tables:
                    # Get column information
                    cur.execute(f"""
                        SELECT column_name, data_type 
                        FROM information_schema.columns 
                        WHERE table_name = '{table}'
                        ORDER BY ordinal_position;
                    """)
                    columns = [{"name": col[0], "type": col[1]} for col in cur.fetchall()]
                    
                    # Count rows
                    cur.execute(f"SELECT COUNT(*) FROM {table}")
                    count = cur.fetchone()[0]
                    
                    # Get sample data (first 5 rows)
                    cur.execute(f"SELECT * FROM {table} LIMIT 5")
                    sample_data = []
                    for row in cur.fetchall():
                        # Convert row to a list of strings for JSON serialization
                        sample_row = []
                        for item in row:
                            if item is None:
                                sample_row.append(None)
                            else:
                                sample_row.append(str(item))
                        sample_data.append(sample_row)
                    
                    # Store table info
                    result["tables"][table] = {
                        "columns": columns,
                        "row_count": count,
                        "sample_data": sample_data
                    }
                
                return jsonify(result), 200
            finally:
                db_pool.putconn(conn)
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    
    return app
