import os
import psycopg2
from psycopg2.extras import RealDictCursor

def get_conn():
    db_url = os.getenv("DB_URL")
    if not db_url:
        raise RuntimeError("DB_URL is not set")
    return psycopg2.connect(db_url)

def dict_cursor(conn):
    return conn.cursor(cursor_factory=RealDictCursor)