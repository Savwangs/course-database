import os
import re
from pathlib import Path
from datetime import datetime, timezone

import psycopg2
from psycopg2.extras import Json
from dotenv import load_dotenv

# Load .env from the path you gave
load_dotenv("../OpenAI_Chatbot_Integration/.env")

INPUT_DIR = Path("dvc_txt_FA2026")
TABLE_NAME = "course_sections_fall_2026"
DATABASE_URL = os.getenv("DATABASE_URL")

TEST_FILE = False
# Convert SQLAlchemy URL to psycopg2 URL
if DATABASE_URL.startswith("postgresql+psycopg2://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql+psycopg2://", "postgresql://", 1)

UNITS_PATTERN = re.compile(r"^\d+\.\d{2}(?:/\d+\.\d{2})?$")
DATE_RANGE_PATTERN = re.compile(r"^\d{1,2}/\d{1,2}/\d{4}\s*-\s*\d{1,2}/\d{1,2}/\d{4}$")
STATUS_PATTERN = re.compile(r"^(Open|Clsd|Closed|Waitlist|Waitlisted|Cancelled|Full)\b", re.I)
DAY_PATTERN = re.compile(r"^(M|T|W|Th|F|Sa|Su)(\s+(M|T|W|Th|F|Sa|Su))*$")
TIME_PATTERN = re.compile(r"^\d{1,2}:\d{2}(AM|PM)\s*-\s*\d{1,2}:\d{2}(AM|PM)$", re.I)


def _extract_last_update(text: str) -> str:
    m = re.search(r"\((\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})\)", text)
    return m.group(1) if m else ""


def _parse_iso_ts(ts: str):
    if not ts:
        return None
    dt = datetime.fromisoformat(ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _split_line(line: str) -> list[str]:
    return [c.strip() for c in line.split(";")]


def _parse_course_code_title(course_cell: str) -> tuple[str, str]:
    m = re.match(r"^\s*([A-Z0-9-]+)\s*-\s*(.*?)\s*$", course_cell)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return "", course_cell.strip()


def _is_units(token: str) -> bool:
    return bool(UNITS_PATTERN.fullmatch(token.strip()))


def _is_status(token: str) -> bool:
    return bool(STATUS_PATTERN.match(token.strip()))


def _looks_like_instructor(token: str) -> bool:
    token = token.strip()
    if not token:
        return False
    if token.startswith(("Prerequisite:", "Note:", "Advisory:")):
        return False
    return bool(re.fullmatch(r"[A-Za-z'. -]+,\s*[A-Za-z'. -]+", token))


def _build_seat_availability(status: str, seats: str) -> str | None:
    status = (status or "").strip()
    seats = (seats or "").strip()

    if status and seats:
        return f"{status} ({seats} seats)"
    if status:
        return status
    if seats:
        return f"{seats} seats"
    return None

def _split_comment_buckets(comment_tokens: list[str]) -> tuple[str | None, str | None, str | None]:
    prereq_parts = []
    advisory_parts = []
    note_parts = []
    current = None

    for token in comment_tokens:
        t = token.strip()
        if not t:
            continue

        low = t.lower()
        if low.startswith("prerequisite:"):
            current = "prereq"
            prereq_parts.append(t)
        elif low.startswith("advisory:"):
            current = "advisory"
            advisory_parts.append(t)
        elif low.startswith("note:"):
            current = "note"
            note_parts.append(t)
        else:
            if current == "prereq":
                prereq_parts.append(t)
            elif current == "advisory":
                advisory_parts.append(t)
            else:
                note_parts.append(t)

    prereq = " ".join(prereq_parts).strip() or None
    advisory = " ".join(advisory_parts).strip() or None
    comments = " ".join(note_parts).strip() or None

    return prereq, advisory, comments


def _parse_schedule(schedule_tokens: list[str]) -> tuple[list[dict], str | None]:
    tokens = [t.strip() for t in schedule_tokens if t.strip()]
    meetings = []
    modality = None
    i = 0

    while i < len(tokens):
        token = tokens[i]

        if token == "OFF":
            if i + 1 < len(tokens) and tokens[i + 1] == "ONLINE":
                meetings.append({
                    "days": "OFF",
                    "time": "Asynchronous",
                    "building": "",
                    "room": "",
                    "format": "online"
                })
                modality = "online"
                i += 2
                continue

            if i + 1 < len(tokens) and tokens[i + 1] == "PART-ONL":
                meetings.append({
                    "days": "OFF",
                    "time": "",
                    "building": "",
                    "room": "",
                    "format": "hybrid"
                })
                modality = "hybrid"
                i += 2
                continue

        if DAY_PATTERN.fullmatch(token) and i + 3 < len(tokens) and TIME_PATTERN.fullmatch(tokens[i + 1]):
            meetings.append({
                "days": token,
                "time": tokens[i + 1],
                "building": tokens[i + 2],
                "room": tokens[i + 3],
                "format": "in-person"
            })
            i += 4
            continue

        if token == "ONLINE":
            meetings.append({
                "days": "ONLINE",
                "time": "Asynchronous",
                "building": "",
                "room": "",
                "format": "online"
            })
            modality = "online"
            i += 1
            continue

        if token == "PART-ONL":
            meetings.append({
                "days": "PART-ONL",
                "time": "",
                "building": "",
                "room": "",
                "format": "hybrid"
            })
            modality = "hybrid"
            i += 1
            continue

        i += 1

    if modality is None:
        formats = {m.get("format") for m in meetings}
        if "hybrid" in formats:
            modality = "hybrid"
        elif formats == {"online"}:
            modality = "online"
        elif "in-person" in formats:
            modality = "in-person"

    return meetings, modality


def parse_course_txt_to_object(txt_path: Path) -> dict | None:
    text = txt_path.read_text(encoding="utf-8").strip()
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return None

    last_update = _extract_last_update(lines[0])

    header_idx = None
    for i, line in enumerate(lines):
        low = line.lower()
        if all(k in low for k in ["term", "location", "section", "course", "status"]):
            header_idx = i
            break

    if header_idx is None:
        return None

    course_code = ""
    course_title = ""
    sections = []

    for line in lines[header_idx + 1:]:
        cells = _split_line(line)
        if len(cells) < 11:
            continue

        term = cells[0]
        location = cells[1]
        section_number = cells[2]
        course_cell = cells[3]
        date_range = cells[4]

        if not DATE_RANGE_PATTERN.fullmatch(date_range):
            continue

        # Handle both:
        # ...;prereq;advisory;comments;status;seats
        # ...;prereq;advisory;comments;status
        if _is_status(cells[-1]):
            seats = ""
            status = cells[-1]
            comments = cells[-2] if len(cells) >= 2 else ""
            advisory = cells[-3] if len(cells) >= 3 else ""
            prereq = cells[-4] if len(cells) >= 4 else ""
            instructor = cells[-5] if len(cells) >= 5 else ""
            units = cells[-6] if len(cells) >= 6 else ""
            schedule_tokens = cells[5:-6]
        else:
            seats = cells[-1]
            status = cells[-2]
            comments = cells[-3]
            advisory = cells[-4]
            prereq = cells[-5]
            instructor = cells[-6]
            units = cells[-7]
            schedule_tokens = cells[5:-7]

        if not _is_units(units):
            continue
        if not _looks_like_instructor(instructor):
            continue
        if not _is_status(status):
            continue

        code, title = _parse_course_code_title(course_cell)
        if code:
            course_code = course_code or code
        if title:
            course_title = course_title or title

        meetings, modality = _parse_schedule(schedule_tokens)

        prereq = prereq or None
        advisory = advisory or None
        comments = comments or None

        sections.append({
            "term": term,
            "location": location,
            "section_number": section_number,
            "date_range": date_range,
            "units": units,
            "instructor": instructor,
            "schedule": meetings,
            "modality": modality,
            "prereq": prereq,
            "advisory": advisory,
            "comments": comments,
            "seat_availability": _build_seat_availability(status, seats),
        })

    if not sections:
        return None

    return {
        "course_code": course_code,
        "course_title": course_title,
        "last_update": last_update,
        "sections": sections,
    }


def upsert_course_to_db(conn, course_obj: dict) -> int:
    course_code = (course_obj.get("course_code") or "").strip()
    if not course_code:
        return 0

    last_update = _parse_iso_ts(course_obj.get("last_update", ""))
    seen_sections = set()

    with conn.cursor() as cur:
        for sec in course_obj.get("sections", []):
            section_number = (sec.get("section_number") or "").strip()
            if not section_number:
                continue

            seen_sections.add(section_number)

            cur.execute(
                f"""
                INSERT INTO public.{TABLE_NAME}
                    (
                        course_code,
                        section_number,
                        instructor,
                        schedule,
                        modality,
                        seat_availability,
                        units,
                        comments,
                        prereq,
                        advisory,
                        last_update
                    )
                VALUES
                    (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (course_code, section_number)
                DO UPDATE SET
                    instructor = EXCLUDED.instructor,
                    schedule = EXCLUDED.schedule,
                    modality = EXCLUDED.modality,
                    seat_availability = EXCLUDED.seat_availability,
                    units = EXCLUDED.units,
                    comments = EXCLUDED.comments,
                    prereq = EXCLUDED.prereq,
                    advisory = EXCLUDED.advisory,
                    last_update = EXCLUDED.last_update
                """,
                (
                    course_code,
                    section_number,
                    sec.get("instructor"),
                    Json(sec.get("schedule", [])),
                    sec.get("modality"),
                    sec.get("seat_availability"),
                    sec.get("units"),
                    sec.get("comments"),
                    sec.get("prereq"),
                    sec.get("advisory"),
                    last_update,
                ),
            )

        if seen_sections:
            cur.execute(
                f"""
                DELETE FROM public.{TABLE_NAME}
                WHERE course_code = %s
                  AND section_number <> ALL(%s)
                """,
                (course_code, list(seen_sections)),
            )

    conn.commit()
    return len(seen_sections)


def main():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not set in OpenAI_Chatbot_Integration/.env")

    if TEST_FILE:
        txt_files = [INPUT_DIR / TEST_FILE]
        print(f"Test mode: only processing {TEST_FILE}")
    else:
        txt_files = sorted(INPUT_DIR.glob("dvc_*.txt"))

    if not txt_files:
        print(f"No .txt files found in {INPUT_DIR.resolve()}")
        return

    conn = psycopg2.connect(DATABASE_URL)

    try:
        written = 0
        for txt_path in txt_files:
            if not txt_path.exists():
                print(f"File not found: {txt_path}")
                continue

            print(f"Processing {txt_path.name} ...")
            obj = parse_course_txt_to_object(txt_path)

            if not obj:
                print(f"Skipped (unparseable): {txt_path.name}")
                continue

            row_count = upsert_course_to_db(conn, obj)
            print(f"Done with {txt_path.name} -> {TABLE_NAME} ({obj.get('course_code', 'UNKNOWN')}, {row_count} section(s))")
            written += 1

        print(f"Finished. Synced {written} file(s) into {TABLE_NAME}.")
    finally:
        conn.close()
        print("Database connection closed.")


if __name__ == "__main__":
    main()