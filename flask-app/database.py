import os
import psycopg2
from psycopg2 import pool

# Initialize a connection pool
db_pool = pool.SimpleConnectionPool(
    minconn=1,
    maxconn=10,
    dsn=os.getenv("DATABASE_URL")
)

def init_db():
    """Initialize the database schema if necessary."""
    conn = db_pool.getconn()
    try:
        with conn.cursor() as cur:
            # Example schema creation
            cur.execute("""
                CREATE TABLE IF NOT EXISTS tickets (
                    id SERIAL PRIMARY KEY,
                    title TEXT NOT NULL,
                    description TEXT,
                    status TEXT DEFAULT 'Open',
                    priority TEXT DEFAULT 'Normal',
                    assigned_to TEXT DEFAULT 'Unassigned',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()
    finally:
        db_pool.putconn(conn)
