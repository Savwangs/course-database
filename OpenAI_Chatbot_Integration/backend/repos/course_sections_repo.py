from backend.db import get_conn, dict_cursor

def fetch_sections_by_keywords(keywords, limit=500):
    kws = [str(k).strip().upper() for k in (keywords if isinstance(keywords, list) else [keywords])]
    kws = [k for k in kws if k]

    course_codes = [k for k in kws if "-" in k]
    subjects = [k for k in kws if "-" not in k]

    clauses = []
    params = []

    if course_codes:
        clauses.append("course_code = ANY(%s)")
        params.append(course_codes)

    if subjects:
        patterns = [f"{s}-%" for s in subjects]
        clauses.append("course_code ILIKE ANY(%s)")
        params.append(patterns)

    where_sql = " OR ".join(clauses) if clauses else "TRUE"

    conn = get_conn()
    try:
        with conn:
            with dict_cursor(conn) as cur:
                cur.execute(
                    f"""
                    SELECT course_code, section_number, instructor, schedule, modality,
                           seat_availability, units, last_update
                    FROM course_sections
                    WHERE {where_sql}
                    ORDER BY course_code, section_number
                    LIMIT %s;
                    """,
                    (*params, limit),
                )
                return cur.fetchall()
    finally:
        conn.close()


def fetch_allow_lists():
    conn = get_conn()
    try:
        with conn:
            with dict_cursor(conn) as cur:
                cur.execute("SELECT DISTINCT course_code FROM course_sections ORDER BY course_code;")
                codes = [r["course_code"].upper() for r in cur.fetchall()]
    finally:
        conn.close()

    subjects = sorted({c.split("-")[0] for c in codes if "-" in c})
    return codes, subjects
