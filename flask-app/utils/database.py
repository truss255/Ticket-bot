import psycopg2
from psycopg2 import pool
from config import DATABASE_URL

db_pool = pool.SimpleConnectionPool(1, 10, DATABASE_URL)

def init_db():
    conn = db_pool.getconn()
    try:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tickets (
                ticket_id SERIAL PRIMARY KEY,
                created_by VARCHAR(255),
                campaign VARCHAR(255),
                issue_type VARCHAR(255),
                priority VARCHAR(50),
                status VARCHAR(50),
                assigned_to VARCHAR(255),
                details TEXT,
                salesforce_link VARCHAR(255),
                file_url VARCHAR(255),
                created_at TIMESTAMP,
                updated_at TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS comments (
                comment_id SERIAL PRIMARY KEY,
                ticket_id INTEGER REFERENCES tickets(ticket_id),
                user_id VARCHAR(255),
                comment_text TEXT,
                created_at TIMESTAMP
            );
        """)
        conn.commit()
    except Exception as e:
        raise
    finally:
        db_pool.putconn(conn)