from backend.db import get_conn, dict_cursor

conn = get_conn()
with conn:
    with dict_cursor(conn) as cur:
        cur.execute("SELECT course_code, section_number FROM course_sections LIMIT 5;")
        print(cur.fetchall())
conn.close()
