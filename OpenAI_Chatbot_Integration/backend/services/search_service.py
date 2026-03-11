"""
CourseSearcher – the "brain" of the DVC Course Assistant.

Encapsulates:
  * search_courses()        → filter courses by keyword / mode / day / time / instructor
  * llm_parse_query()       → LLM-based intent + entity extraction
  * ask_course_assistant()  → full orchestration (parse → search → format)
  * log_interaction()       → write to InteractionLog table (SQLAlchemy)
"""

import json
import time
import re
from datetime import datetime, timezone

from backend.models import db
from backend.models.interaction_log import InteractionLog

import httpx
import os

import re
from sqlalchemy import text, bindparam

OPENAI_TIMEOUT_SECONDS = float(os.getenv("OPENAI_TIMEOUT_SECONDS", "20"))

COURSE_SECTIONS_TABLE = "course_sections_fall_2026"

# ---------------------------------------------------------------------------
#  Private helper functions (un-nested from the old search_courses)
# ---------------------------------------------------------------------------


def _split_tokens(s: str):
    """Split on natural separators without regex and detect AND vs OR."""
    s_low = s.lower().strip()
    is_and = " and " in s_low
    tmp = (
        s_low.replace(" and ", "|")
             .replace(" or ", "|")
             .replace(",", "|")
             .replace("/", "|")
    )
    parts = [p.strip() for p in tmp.split("|") if p.strip()]
    return parts, is_and


def _normalize_mode(m):
    if m is None:
        return None
    if isinstance(m, list):
        return [x.lower() for x in m]
    if isinstance(m, str):
        parts, _ = _split_tokens(m)
        return parts if parts else [m.lower()]
    return [str(m).lower()]


def _normalize_status(s):
    if s is None:
        return None
    if isinstance(s, list):
        return [x.lower() for x in s]
    if isinstance(s, str):
        parts, _ = _split_tokens(s)
        return parts if parts else [s.lower()]
    return [str(s).lower()]


def _normalize_instructor(i):
    if not i:
        return None
    if isinstance(i, str):
        parts, _ = _split_tokens(i)
        return parts if parts else [i]
    return [str(i)]


def _normalize_time(t):
    if not t:
        return None, False
    if isinstance(t, str):
        parts, is_and = _split_tokens(t)
        parts = [p for p in parts if p in {"morning", "afternoon", "evening"}]
        return (parts if parts else [t]), is_and
    if isinstance(t, list):
        return [x for x in t], False
    return [str(t)], False


def _normalize_day(d):
    """Return (tokens_as_codes, require_all). Accepts names or codes."""
    if not d:
        return None, False
    name_to_code = {
        "monday": "M", "mon": "M", "m": "M",
        "tuesday": "T", "tue": "T", "tues": "T", "t": "T",
        "wednesday": "W", "wed": "W", "w": "W",
        "thursday": "Th", "thu": "Th", "thur": "Th", "thurs": "Th", "th": "Th",
        "friday": "F", "fri": "F", "f": "F",
    }
    if isinstance(d, str):
        parts, is_and = _split_tokens(d)
        codes = [name_to_code.get(p, p) for p in parts]
        return codes, is_and
    if isinstance(d, list):
        return d, False
    return [str(d)], False


def _time_bucket(hour: int) -> str:
    if hour < 12:
        return "morning"
    if 12 <= hour < 17:
        return "afternoon"
    return "evening"


def _has_day_code(code: str, days_str: str) -> bool:
    """Check whether *code* (e.g. 'Th', 'M') appears in *days_str*."""
    if code == "Th":
        return "Th" in days_str
    return code in days_str


def _parse_start_hour(time_str: str) -> int | None:
    """Extract the starting hour (24-h) from a time string like '6:30PM - 7:55PM'."""
    try:
        start_raw = time_str.split("-")[0].strip()
        if "PM" in start_raw and not start_raw.startswith("12"):
            return int(start_raw.split(":")[0]) + 12
        if "AM" in start_raw and start_raw.startswith("12"):
            return 0
        return int(start_raw.split(":")[0])
    except Exception:
        return None


# ---------------------------------------------------------------------------
#  CourseSearcher
# ---------------------------------------------------------------------------

class CourseSearcher:
    """Stateless service that searches Cloud SQL tables and orchestrates the LLM."""

    def __init__(self, openai_client):
        self.client = openai_client

    # ------------------------------------------------------------------
    #  search_courses  (was the top-level function in app.py, lines 116-406)
    # ------------------------------------------------------------------
    def search(self, keyword, mode=None, status=None,
            day_filter=None, time_filter=None, instructor_filter=None):
        """
        Cloud SQL version of the original JSON search:
        - Pull candidate rows from course_sections (by course_code or subject prefix)
        - Apply OG filtering logic in Python (mode/status/day/time/instructor + compound OR)
        - Return same shape:
        [
            {"course_code": "...", "course_title": "", "sections": [ ... ] }
        ]
        """

        # ----------------------------
        # 0) Normalize keywords
        # ----------------------------
        keywords = keyword if isinstance(keyword, list) else [keyword]
        keywords = [str(k).strip() for k in keywords if k and str(k).strip()]
        if not keywords:
            return []

        is_course_code_search = any("-" in k for k in keywords)

        # ----------------------------
        # 1) Detect compound day+time OR pairs (OG behavior)
        # Example: "Monday morning or Thursday afternoon"
        # ----------------------------
        compound_conditions = []
        if day_filter and time_filter:
            combined = f"{day_filter} {time_filter}".lower()
            if " or " in combined and any(x in combined for x in ("morning", "afternoon", "evening")):
                or_parts = [p.strip() for p in combined.split(" or ") if p.strip()]
                name_to_code = {
                    "monday": "M", "mon": "M", "m": "M",
                    "tuesday": "T", "tue": "T", "tues": "T", "t": "T",
                    "wednesday": "W", "wed": "W", "w": "W",
                    "thursday": "Th", "thu": "Th", "thur": "Th", "thurs": "Th", "th": "Th",
                    "friday": "F", "fri": "F", "f": "F",
                }

                for part in or_parts:
                    day_found = None
                    time_found = None

                    for day_name, day_code in name_to_code.items():
                        if day_name in part:
                            day_found = day_code
                            break

                    if "morning" in part:
                        time_found = "morning"
                    elif "afternoon" in part:
                        time_found = "afternoon"
                    elif "evening" in part:
                        time_found = "evening"

                    if day_found and time_found:
                        compound_conditions.append((day_found, time_found))

        # ----------------------------
        # 2) Normalize filters (OG helpers)
        # ----------------------------
        mode_norm = _normalize_mode(mode)               # list or None
        status_norm = _normalize_status(status)         # list or None
        instr_norm = _normalize_instructor(instructor_filter)  # list or None
        day_terms, day_all = _normalize_day(day_filter)         # (list|None, bool)
        time_terms, time_all = _normalize_time(time_filter)     # (list|None, bool)

        # ----------------------------
        # 3) Query candidate rows (minimal DB filtering only)
        # ----------------------------


        def _normalize_code(s: str) -> str:
            return re.sub(r"[^A-Za-z0-9]", "", (s or "")).upper()

        # ...

        is_sqlite = db.engine.dialect.name == "sqlite"

        if is_course_code_search:
            wanted_norm = [_normalize_code(k) for k in keywords]

            if is_sqlite:
                # SQLite: no regexp_replace; normalize with REPLACE(UPPER(...))
                sql = text("""
                    SELECT
                    cs.course_code,
                    cs.section_number,
                    cs.instructor,
                    cs.schedule,
                    cs.modality,
                    cs.seat_availability,
                    cs.units,
                    cs.comments,
                    cs.prereq,
                    cs.advisory
                    FROM course_sections_fall_2026 cs
                    WHERE UPPER(REPLACE(REPLACE(REPLACE(REPLACE(cs.course_code, '-', ''), ' ', ''), '_', ''), '.', '')) IN :codes_norm
                    ORDER BY cs.course_code, cs.section_number
                """).bindparams(bindparam("codes_norm", expanding=True))
            else:
                sql = text("""
                    SELECT
                    cs.course_code,
                    cs.section_number,
                    cs.instructor,
                    cs.schedule,
                    cs.modality,
                    cs.seat_availability,
                    cs.units,
                    cs.comments,
                    cs.prereq,
                    cs.advisory
                    FROM course_sections_fall_2026 cs
                    WHERE upper(regexp_replace(cs.course_code, '[^A-Za-z0-9]', '', 'g')) IN :codes_norm
                    ORDER BY cs.course_code, cs.section_number
                """).bindparams(bindparam("codes_norm", expanding=True))

            params = {"codes_norm": wanted_norm}

        else:
            subjects_upper = [k.upper() for k in keywords]
            if is_sqlite:
                # SQLite: no split_part; use LIKE for subject prefix
                placeholders = ", ".join([f"cs.course_code LIKE :s{i}" for i in range(len(subjects_upper))])
                sql = text(f"""
                    SELECT
                    cs.course_code,
                    cs.section_number,
                    cs.instructor,
                    cs.schedule,
                    cs.modality,
                    cs.seat_availability,
                    cs.units,
                    cs.comments,
                    cs.prereq,
                    cs.advisory
                    FROM course_sections_fall_2026 cs
                    WHERE {placeholders}
                    ORDER BY cs.course_code, cs.section_number
                """)
                params = {f"s{i}": f"{s}-%" for i, s in enumerate(subjects_upper)}
            else:
                sql = text("""
                    SELECT
                    cs.course_code,
                    cs.section_number,
                    cs.instructor,
                    cs.schedule,
                    cs.modality,
                    cs.seat_availability,
                    cs.units,
                    cs.comments,
                    cs.prereq,
                    cs.advisory
                    FROM course_sections_fall_2026 cs
                    WHERE split_part(cs.course_code, '-', 1) IN :subjects
                    ORDER BY cs.course_code, cs.section_number
                """).bindparams(bindparam("subjects", expanding=True))
                params = {"subjects": subjects_upper}

        rows = db.session.execute(sql, params).mappings().all()
        if not rows:
            return []

        # ----------------------------
        # 4) Row -> course->sections (OG shape)
        # Also normalize schedule into (days, time) for OG day/time logic
        # ----------------------------

        by_course = {}
        for r in rows:
            code = (r.get("course_code") or "").replace(" ", "").upper()
            if not code:
                continue

            if code not in by_course:
                by_course[code] = {
                    "course_code": code,
                    "course_title": "",
                    "sections": [],
                }

            schedule_raw = r.get("schedule")
            meetings = []

            if isinstance(schedule_raw, list):
                for m in schedule_raw:
                    if isinstance(m, dict):
                        meetings.append({
                            "days": m.get("days") or "",
                            "time": m.get("time") or "",
                            "format": (m.get("format") or r.get("modality") or "").lower(),
                            "location": " ".join(
                                x for x in [m.get("building"), m.get("room")] if x
                            ) or None,
                            "building": m.get("building"),
                            "room": m.get("room"),
                        })
            elif isinstance(schedule_raw, str) and schedule_raw.strip():
                try:
                    parsed_schedule = json.loads(schedule_raw)
                    if isinstance(parsed_schedule, list):
                        for m in parsed_schedule:
                            if isinstance(m, dict):
                                meetings.append({
                                    "days": m.get("days") or "",
                                    "time": m.get("time") or "",
                                    "format": (m.get("format") or r.get("modality") or "").lower(),
                                    "location": " ".join(
                                        x for x in [m.get("building"), m.get("room")] if x
                                    ) or None,
                                    "building": m.get("building"),
                                    "room": m.get("room"),
                                })
                except Exception:
                    pass

            by_course[code]["sections"].append({
                "section_number": r.get("section_number"),
                "instructor": r.get("instructor"),
                "status": r.get("seat_availability") or "",
                "units": r.get("units"),
                "prereq": r.get("prereq"),
                "advisory": r.get("advisory"),
                "comments": r.get("comments"),
                "meetings": meetings,
            })

        # ----------------------------
        # 5) Apply OG filtering logic in Python
        # ----------------------------
        out_courses = []

        for code, course in by_course.items():
            filtered_sections = []

            for section in course.get("sections", []):
                meetings = section.get("meetings") or []

                # Derive section_format EXACTLY like OG approach
                all_formats = set(
                    (m.get("format") or "").lower()
                    for m in meetings if m.get("format")
                )
                if "hybrid" in all_formats or len(all_formats) > 1:
                    section_format = "hybrid"
                elif "in-person" in all_formats:
                    section_format = "in-person"
                elif "online" in all_formats:
                    section_format = "online"
                else:
                    section_format = list(all_formats)[0] if all_formats else ""

                # MODE
                if mode_norm and section_format not in mode_norm:
                    continue

                # STATUS (substring OR)
                stat = (section.get("status") or "").lower()
                if status_norm and not any(s in stat for s in status_norm):
                    continue

                # INSTRUCTOR (token AND inside each query; OR across queries)
                if instr_norm:
                    instructor = (section.get("instructor") or "").lower()
                    matched = False
                    for name_query in instr_norm:
                        q_tokens = [
                            t.strip().lower()
                            for t in str(name_query).replace(",", " ").split()
                            if t.strip()
                        ]
                        if q_tokens and all(t in instructor for t in q_tokens):
                            matched = True
                            break
                    if not matched:
                        continue

                # DAY/TIME matching (meetings loop) + compound support
                def _meeting_matches_day_time(m):
                    days = (m.get("days") or "")
                    time_str = (m.get("time") or "")

                    # Compound: (day+time) OR (day+time)
                    if compound_conditions:
                        for required_day, required_time in compound_conditions:
                            if not _has_day_code(required_day, days):
                                continue

                            if not time_str or str(time_str).lower() == "asynchronous":
                                continue

                            hour = _parse_start_hour(time_str)
                            if hour is None:
                                continue
                            if _time_bucket(hour) == required_time:
                                return True
                        return False

                    # Non-compound: independent day/time filters
                    day_ok = True
                    if day_terms:
                        if day_all:
                            day_ok = all(_has_day_code(c, days) for c in day_terms)
                        else:
                            day_ok = any(_has_day_code(c, days) for c in day_terms)

                    time_ok = True
                    if time_terms:
                        if not time_str or str(time_str).lower() == "asynchronous":
                            time_ok = False
                        else:
                            hour = _parse_start_hour(time_str)
                            if hour is None:
                                time_ok = False
                            else:
                                bucket = _time_bucket(hour)
                                if time_all:
                                    time_ok = all(t == bucket for t in time_terms)
                                else:
                                    time_ok = any(t == bucket for t in time_terms)

                    return day_ok and time_ok

                if (day_terms or time_terms or compound_conditions) and not any(_meeting_matches_day_time(m) for m in meetings):
                    continue

                filtered_sections.append(section)

            if filtered_sections:
                out_courses.append({
                    "course_code": course["course_code"],
                    "course_title": course.get("course_title") or "",
                    "sections": filtered_sections,
                })

        return out_courses
    # ------------------------------------------------------------------
    #  llm_parse_query  (was top-level in app.py, lines 408-511)
    # ------------------------------------------------------------------
    def parse_query(self, user_query: str, *, temperature: float = 0.0) -> dict:
        """LLM-first parser -> course_codes, subjects, intent, filters (constrained to DB)."""

        # Build allow-lists from course_sections only
        rows = db.session.execute(text(f"""
            SELECT DISTINCT course_code
            FROM {COURSE_SECTIONS_TABLE}
            WHERE course_code IS NOT NULL AND course_code <> ''
        """)).mappings().all()

        all_course_codes = sorted({r["course_code"].upper() for r in rows if r.get("course_code")})
        all_subject_prefixes = sorted({c.split("-")[0].upper() for c in all_course_codes if "-" in c})

        # Hard fallback extraction so COMSC-110 always works
        hard_codes = set(re.findall(r"\b[A-Za-z]{3,5}\s*-\s*\d{2,3}[A-Za-z]?\b", user_query))
        hard_codes = {c.replace(" ", "").upper() for c in hard_codes}

        hard_subjects = set(re.findall(r"\b[A-Za-z]{3,5}\b", user_query))
        hard_subjects = {s.upper() for s in hard_subjects if s.upper() in all_subject_prefixes}

        parser_system = (
            "You are an intent and entity parser for a community college course finder. "
            "Return STRICT JSON ONLY with keys:\n"
            "{\n"
            '  "course_codes": ["COMSC-110"],\n'
            '  "subjects": ["COMSC"],\n'
            '  "intent": "find_sections" | "prerequisites" | "instructors",\n'
            '  "filters": {"mode": "in-person" | "online" | "hybrid" | null,'
            '             "status": "open" | "closed" | null,'
            '             "day": "M"|"T"|"W"|"Th"|"F"|null,'
            '             "time": "morning"|"afternoon"|"evening"|null,'
            '             "instructor": string|null}\n'
            "}\n"
            "Rules:\n"
            "- Extract course_codes and subjects ONLY from the current user message. Do not use course codes or subjects from example prompts or from previous assistant or user messages.\n"
            "- Only choose course_codes from ALLOWED_COURSE_CODES.\n"
            "- Only choose subjects from ALLOWED_SUBJECT_PREFIXES.\n"
            "- If user asks about prerequisites, set intent='prerequisites'.\n"
            "- If user asks about instructor, set intent='instructors'.\n"
            "- If the user is only asking about GE requirements, transfer, or which UC campus (e.g. 'What GE for UC?', 'What do I need for UC?'), return empty course_codes and empty subjects so the assistant can ask which campus.\n"
            "- Otherwise intent='find_sections'.\n"
        )

        parser_user = json.dumps({
            "USER_QUERY": user_query,
            "ALLOWED_COURSE_CODES": all_course_codes,
            "ALLOWED_SUBJECT_PREFIXES": all_subject_prefixes,
        })

        try:
            resp = self.client.chat.completions.create(
                model="gpt-4.1",
                temperature=temperature,
                messages=[
                    {"role": "system", "content": parser_system},
                    {"role": "user", "content": parser_user},
                ],
                timeout=OPENAI_TIMEOUT_SECONDS,
            )
            parsed = json.loads(resp.choices[0].message.content.strip())
        except Exception:
            parsed = {}

        parsed = parsed if isinstance(parsed, dict) else {}
        parsed.setdefault("course_codes", [])
        parsed.setdefault("subjects", [])
        parsed.setdefault("intent", "find_sections")
        parsed.setdefault("filters", {
            "mode": None, "status": None, "day": None, "time": None, "instructor": None,
        })

        if not isinstance(parsed["course_codes"], list):
            parsed["course_codes"] = [] if parsed["course_codes"] is None else [parsed["course_codes"]]
        if not isinstance(parsed["subjects"], list):
            parsed["subjects"] = [] if parsed["subjects"] is None else [parsed["subjects"]]

        parsed["course_codes"] = [str(c).replace(" ", "").upper() for c in parsed["course_codes"] if isinstance(c, str)]
        parsed["subjects"] = [str(s).upper() for s in parsed["subjects"] if isinstance(s, str)]

        # Enforce allow-lists
        parsed["course_codes"] = [c for c in parsed["course_codes"] if c in all_course_codes]
        parsed["subjects"] = [s for s in parsed["subjects"] if s in all_subject_prefixes]

        # Merge hard fallbacks (restores “always works” behavior)
        parsed["course_codes"] = sorted(set(parsed["course_codes"]) | (hard_codes & set(all_course_codes)))
        parsed["subjects"] = sorted(set(parsed["subjects"]) | hard_subjects)

        return parsed

    # ------------------------------------------------------------------
    #  ask  (was ask_course_assistant in app.py, lines 952-1313)
    # ------------------------------------------------------------------
    def ask(self, user_query: str, *, conversation_history: list | None = None,
            parser_temperature: float = 0.0, response_temperature: float = 0.1,
            enable_logging: bool = True, transfer_handler=None):
        """LLM parses → we search → LLM formats.

        Args:
            transfer_handler: callable(user_query) -> str|None  (UC transfer hook)
        """
        start_ms = time.perf_counter()

        if conversation_history is None:
            conversation_history = []

        # Early hook for UC transfer requests
        if transfer_handler is not None:
            transfer_try = transfer_handler(user_query)
            if transfer_try:
                return transfer_try  # already logged inside transfer handler

        # Emotional/relationship support: fixed short response only, no course search
        try:
            from backend import guardrails
            emotional_response = guardrails.get_emotional_support_response(user_query)
            if emotional_response:
                if enable_logging:
                    self.log_interaction(user_query, {"emotional_support_redirect": True}, emotional_response, start_ms, status="emotional_support_redirect")
                return emotional_response
        except Exception:
            pass

        query_lower = user_query.lower()

        # Follow-up detection
        is_followup = len(conversation_history) > 0
        if is_followup:
            context_summary = "\n".join([
                f"{'User' if msg['role'] == 'user' else 'Assistant'}: {msg['content'][:200]}..."
                for msg in conversation_history[-4:]
            ])
            enhanced_query = f"Previous conversation context:\n{context_summary}\n\nCurrent question: {user_query}"
        else:
            enhanced_query = user_query

        parsed = self.parse_query(user_query, temperature=parser_temperature)

        course_codes = parsed.get("course_codes", [])
        subjects = parsed.get("subjects", [])
        intent = parsed.get("intent", "find_sections")
        filters = parsed.get("filters", {}) or {}
        mode = filters.get("mode")
        status = filters.get("status")
        day_filter = filters.get("day")
        time_filter = filters.get("time")
        instructor_mentioned = filters.get("instructor")

        # GE/UC safeguard: if current message is GE/UC-only and has no course code, force "Which campus?" path
        q_low = user_query.lower()
        ge_uc_intent = any(
            x in q_low for x in (
                "what ge", "ge for", "ge do", "ge courses", "need for uc", "for uc transfer",
                "for uc", "uc transfer", "which uc", "for berkeley", "for davis", "for san diego"
            )
        )
        course_code_in_message = bool(
            re.search(r"[A-Za-z]{3,5}\s*-\s*\d{2,3}", user_query, re.I)
            or re.search(r"\b[A-Za-z]{3,5}\s+\d{2,3}\b", user_query, re.I)
        )
        if ge_uc_intent and not course_code_in_message:
            course_codes, subjects = [], []

        # Map "available" → open
        if not status and ("available" in query_lower or "avaliable" in query_lower or "avail" in query_lower):
            status = "open"

        # "in-person" also includes "hybrid"
        if mode == "in-person":
            mode = ["in-person", "hybrid"]

        # Instructor title fallback
        if not instructor_mentioned:
            titles = {"professor", "prof", "dr", "instructor", "teacher"}
            words = user_query.split()
            for i, w in enumerate(words):
                if w.strip(",.?!").lower() in titles and i + 1 < len(words):
                    instructor_mentioned = words[i + 1].strip(",.?!")
                    break

        # Nothing useful parsed → guide the user or ask for clarification
        if not course_codes and not subjects:
            # UC / GE / transfer without campus → ask which campus
            q_low = user_query.lower()
            if any(x in q_low for x in ("ge ", "ge courses", "uc ", "uc transfer", "for uc", "for berkeley", "for davis", "for san diego", "which uc")):
                response = (
                    "Which campus? I can help with **UC Berkeley (UCB)**, **UC Davis (UCD)**, or **UC San Diego (UCSD)**. "
                    "Try: \"What GE courses for UC Berkeley?\" or \"What should I take for UCB transfer?\""
                )
            else:
                response = (
                    "I can help you find DVC STEM courses and details and transfer from DVC agreements.\n\n"
                    "Try one of these:\n"
                    '- "Show me open MATH-193 sections Monday morning."\n'
                    '- "Who teaches PHYS-130 on Thursdays?"\n'
                    '- "What are the prerequisites for COMSC-200?"\n'
                    '- "I have completed Math 192, what does that cover at UCB?"\n'
                    '- "What GE courses should I take at DVC for UC Berkeley?"'
                )
            if enable_logging:
                self.log_interaction(user_query, parsed, response, start_ms, status="needs_clarification")
            return response

        # ------ Prerequisite intent ------
        if intent == "prerequisites":
            # If user asked for a specific course that wasn't parsed (filtered out), return no-such-course
            requested_in_query = set(re.findall(r"[A-Za-z]{3,5}-\d{2,3}[A-Za-z]?", user_query, re.IGNORECASE))
            requested_in_query = {c.replace(" ", "").upper() for c in requested_in_query}
            if requested_in_query and not course_codes and not subjects:
                code_display = ", ".join(sorted(requested_in_query))
                response = (
                    f"I couldn't find that course in the catalog (**{code_display}**). "
                    "Please check the course code (e.g. COMSC-200, MATH-193) and try again."
                )
                if enable_logging:
                    self.log_interaction(user_query, parsed, response, start_ms, status="no_results")
                return response
            return self._handle_prerequisites(
                user_query, query_lower, parsed, course_codes, subjects,
                enable_logging, start_ms,
            )

        # ------ Section search ------
        keyword = course_codes if course_codes else subjects
        results = self.search(keyword, mode, status, day_filter, time_filter, instructor_mentioned)

        # If nothing matched, diagnose
        if not results:
            return self._handle_no_results(
                user_query, parsed, keyword, mode, status,
                day_filter, time_filter, instructor_mentioned,
                enable_logging, start_ms,
            )

        # Format results via LLM
        response = self._format_results(
            user_query, keyword, results, day_filter, time_filter,
            instructor_mentioned, status, mode, conversation_history,
            response_temperature,
        )

        allowed_codes = {c["course_code"].upper() for c in results}
        upper_resp = response.upper()

        # If the model mentions a course code not in allowed list (basic heuristic)
        mentioned = set(re.findall(r"[A-Z]{3,5}-\d{2,3}[A-Z]?", upper_resp))
        unexpected = {c for c in mentioned if c not in allowed_codes}

        if unexpected:
            # If user clearly asked for a specific course that's in unexpected, they likely got no/few results for it
            requested_in_query = set(re.findall(r"[A-Za-z]{3,5}-\d{2,3}[A-Za-z]?", user_query, re.IGNORECASE))
            requested_in_query = {c.replace(" ", "").upper() for c in requested_in_query}
            asked_but_missing = requested_in_query & unexpected
            if asked_but_missing:
                code_display = ", ".join(sorted(asked_but_missing))
                safe = (
                    f"I couldn't find any courses for **{code_display}**.\n"
                    "Please check the course code or try a broader search (e.g. \"Show me MATH sections\")."
                )
            else:
                safe = (
                    "I can only summarize the sections returned from the database for your request, "
                    "and I may have referenced something not in the results. "
                    "Can you confirm the exact course code you want (e.g., COMSC-110)?"
                )
            if enable_logging:
                self.log_interaction(user_query, parsed, safe, start_ms, status="output_guardrail_triggered")
            return safe

        if enable_logging:
            self.log_interaction(user_query, parsed, response, start_ms, status="success")
        return response

    # ------------------------------------------------------------------
    #  Logging  (writes to InteractionLog SQL table)
    # ------------------------------------------------------------------
    
    def log_interaction(
        self,
        user_query: str,
        parsed_data: dict,
        response: str,
        start_ms: float | None = None,
        *,
        status: str | None = None,
        confidence_level: str | None = None,
        result_count: int | None = None,
        confidence: float | None = None,
    ):
        """Persist an interaction to the interaction_logs table (Cloud SQL) safely."""
        latency = None
        if start_ms is not None:
            latency = int((time.perf_counter() - start_ms) * 1000)

        def _clean_text(s: str | None, max_len: int | None = None) -> str | None:
            if not s:
                return None
            # normalize whitespace (turn newlines/tabs into single spaces)
            s = " ".join(s.replace("\t", " ").replace("\r", " ").split())
            # optional: remove a leading UI emoji
            if s.startswith("💬"):
                s = s.lstrip("💬").strip()
            return s[:max_len] if (max_len and len(s) > max_len) else s

        # If not passed, infer simple confidence_level
        if confidence_level is None:
            if status == "success":
                confidence_level = "high"
            elif status in {"needs_clarification", "no_results"}:
                confidence_level = "low"
            else:
                confidence_level = "medium"

        payload = {
            "timestamp": datetime.now(timezone.utc),
            "user_query": _clean_text(user_query, 5000),
            "parsed_data": parsed_data,
            "ai_response": _clean_text(response, 5000),
            "latency_ms": latency,
        }

        try:
            model_cols = set(InteractionLog.__table__.columns.keys())
            safe_payload = {k: v for k, v in payload.items() if k in model_cols}

            if "parsed_data" in safe_payload and not isinstance(safe_payload["parsed_data"], (str, type(None))):
                safe_payload["parsed_data"] = json.dumps(safe_payload["parsed_data"], default=str)

            log_entry = InteractionLog(**safe_payload)
            db.session.add(log_entry)
            db.session.commit()

        except Exception as e:
            db.session.rollback()
            print(f"⚠️ Failed to log interaction to DB: {e}")



    # ------------------------------------------------------------------
    #  Private helpers
    # ------------------------------------------------------------------
    def _handle_prerequisites(self, user_query, query_lower, parsed,
                            course_codes, subjects, enable_logging, start_ms):
        keywords_for_prereq = course_codes or subjects
        results = self.search(keywords_for_prereq)

        # "Can I take X and Y together?" pattern
        can_take_together_patterns = [
            "can i take", "take together", "take at the same time",
            "together with", "take both",
        ]
        is_take_together = any(p in query_lower for p in can_take_together_patterns)

        if is_take_together and len(course_codes) >= 2:
            course_prereqs = {}
            for code in course_codes:
                for r in results:
                    if r["course_code"].upper() == code.upper():
                        course_prereqs[code] = {
                            "prereq": r["sections"][0].get("prereq") or "",
                            "advisory": r["sections"][0].get("advisory") or "",
                            "comments": r["sections"][0].get("comments") or "",
                        }
                        break

            response = f"**Can you take {' and '.join(course_codes)} together?**\n\n"
            conflict_found = False
            for i, code1 in enumerate(course_codes):
                for code2 in course_codes[i + 1:]:
                    prereq1 = course_prereqs.get(code1, {}).get("prereq", "").upper()
                    prereq2 = course_prereqs.get(code2, {}).get("prereq", "").upper()

                    if code1.upper() in prereq2:
                        response += (
                            f"❌ **No** - {code2} requires {code1} as a prerequisite, "
                            f"so you must complete {code1} first.\n\n"
                            f"**{code2} prerequisites (required):** {course_prereqs.get(code2, {}).get('prereq') or 'Not listed'}\n"
                            f"**{code2} advisory (recommended):** {course_prereqs.get(code2, {}).get('advisory') or 'Not listed'}\n"
                        )
                        conflict_found = True
                        break
                    elif code2.upper() in prereq1:
                        response += (
                            f"❌ **No** - {code1} requires {code2} as a prerequisite, "
                            f"so you must complete {code2} first.\n\n"
                            f"**{code1} prerequisites (required):** {course_prereqs.get(code1, {}).get('prereq') or 'Not listed'}\n"
                            f"**{code1} advisory (recommended):** {course_prereqs.get(code1, {}).get('advisory') or 'Not listed'}\n"
                        )
                        conflict_found = True
                        break
                if conflict_found:
                    break

            if not conflict_found:
                response += (
                    "✅ **Yes** - Based on prerequisites, these courses can be taken "
                    "together as neither requires the other.\n\n"
                )
                for code in course_codes:
                    prereq = course_prereqs.get(code, {}).get("prereq") or "No prerequisites listed"
                    advisory = course_prereqs.get(code, {}).get("advisory") or "No advisory listed"
                    response += (
                        f"**{code} prerequisites (required):** {prereq}\n"
                        f"**{code} advisory (recommended):** {advisory}\n"
                    )
                response += (
                    "\n💡 Just make sure there are no schedule conflicts "
                    "between the sections you choose!"
                )

            if enable_logging:
                self.log_interaction(user_query, parsed, response, start_ms, status="success")
            return response

        # Regular prerequisite lookup
        requested_in_query = set(re.findall(r"[A-Za-z]{3,5}-\d{2,3}[A-Za-z]?", user_query, re.IGNORECASE))
        requested_in_query = {c.replace(" ", "").upper() for c in requested_in_query}
        result_codes = {r["course_code"].upper() for r in results} if results else set()

        if results:
            # If user clearly asked for a specific course that's not in results, say we couldn't find it
            if requested_in_query and not (requested_in_query & result_codes):
                code_display = ", ".join(sorted(requested_in_query))
                response = (
                    f"I couldn't find that course in the catalog (**{code_display}**). "
                    "Please check the course code (e.g. COMSC-200, MATH-193) and try again."
                )
                if enable_logging:
                    self.log_interaction(user_query, parsed, response, start_ms, status="no_results")
                return response
            chosen = None
            if course_codes:
                wanted = set(course_codes)
                for r in results:
                    if r["course_code"].upper() in wanted:
                        chosen = r
                        break
            if not chosen and requested_in_query & result_codes:
                for r in results:
                    if r["course_code"].upper() in requested_in_query:
                        chosen = r
                        break
            if not chosen:
                chosen = results[0]
            prereqs = ""
            advisory = ""
            comments = ""

            if chosen.get("sections"):
                first_section = chosen["sections"][0]
                prereqs = first_section.get("prereq") or ""
                advisory = first_section.get("advisory") or ""
                comments = first_section.get("comments") or ""

            response = f"**{chosen['course_code']}: {chosen['course_title']}**\n\n"
            response += f"**Prerequisites (required):** {prereqs or 'No prerequisites listed'}\n"
            response += f"**Advisory (recommended, not required):** {advisory or 'No advisory listed'}"

            if comments:
                response += f"\n**Notes:** {comments}"
            if enable_logging:
                self.log_interaction(user_query, parsed, response, start_ms, status="success")
            return response

        kw_display = ", ".join(keywords_for_prereq) if isinstance(keywords_for_prereq, list) else keywords_for_prereq
        if requested_in_query:
            code_display = ", ".join(sorted(requested_in_query))
            response = (
                f"I couldn't find that course in the catalog (**{code_display}**). "
                "Please check the course code (e.g. COMSC-200, MATH-193) and try again."
            )
        else:
            response = (
                f"I couldn't find any courses for **{kw_display}**.\n"
                "Double-check the course code/subject, or try another course (e.g., COMSC-110, MATH-193)."
            )
        if enable_logging:
            self.log_interaction(user_query, parsed, response, start_ms, status="no_results")
        return response

    def _handle_no_results(self, user_query, parsed, keyword, mode, status,
                           day_filter, time_filter, instructor_mentioned,
                           enable_logging, start_ms):
        baseline = self.search(keyword)

        applied = []
        if mode:
            applied.append(f"mode={mode if isinstance(mode, str) else ','.join(mode)}")
        if status:
            applied.append(f"status={status}")
        if day_filter:
            applied.append(f"day={day_filter}")
        if time_filter:
            applied.append(f"time={time_filter}")
        if instructor_mentioned:
            applied.append(f"instructor={instructor_mentioned}")
        applied_str = ", ".join(applied) if applied else "none"

        kw_display = ", ".join(keyword) if isinstance(keyword, list) else keyword

        if not baseline:
            response = (
                f"I couldn't find any courses for **{kw_display}**.\n"
                "Please check the **subject/prefix** or **course code**, or try a broader query.\n\n"
                "**Examples:**\n"
                '- "Show **COMSC** classes."\n'
                '- "Find **MATH-193** sections."\n'
                '- "Any **online PHYS** this **evening**?"'
            )
        else:
            response = (
                f"I found **no sections** with your current filters (**{applied_str}**) for "
                f"**{kw_display}**.\n\n"
                "Try relaxing one or more filters. For example:\n"
                "- Remove the **instructor** name to see all sections\n"
                "- Try a different **day** or **time** window\n"
                "- Include **hybrid** or **online** if you only searched in-person\n\n"
                "Want me to show **all available sections** for this course/subject?"
            )

        if enable_logging:
            self.log_interaction(user_query, parsed, response, start_ms, status="no_results")
        return response

    def _format_results(self, user_query, keyword, results,
                        day_filter, time_filter, instructor_mentioned,
                        status, mode, conversation_history, response_temperature):
        """Serialize results and ask the LLM to format them for the student."""
        if isinstance(keyword, list):
            is_subject_search = all("-" not in k for k in keyword)
            keyword_display = " and ".join(keyword)
        else:
            is_subject_search = "-" not in keyword
            keyword_display = keyword
        truncate_limit = 8000 if is_subject_search else 4000

        filter_bits = []
        if day_filter:
            filter_bits.append(f"Day: {day_filter}")
        if time_filter:
            filter_bits.append(f"Time: {time_filter}")
        if instructor_mentioned:
            filter_bits.append(f"Instructor: {instructor_mentioned}")
        if status:
            filter_bits.append(f"Status: {status}")
        if mode:
            filter_bits.append(f"Mode: {mode if isinstance(mode, str) else ','.join(mode)}")

        context = f"User asked: '{user_query}'\n\n"

        results_json = json.dumps(results, indent=2)

        if len(results_json) > truncate_limit:
            truncated_results = []
            char_count = 0
            for course in results:
                course_copy = {
                    "course_code": course["course_code"],
                    "course_title": course["course_title"],
                    "sections": [],
                }
                for section in course.get("sections", []):
                    section_json = json.dumps(section, indent=2)
                    if char_count + len(section_json) < truncate_limit - 500:
                        course_copy["sections"].append(section)
                        char_count += len(section_json)
                    else:
                        break
                if course_copy["sections"]:
                    truncated_results.append(course_copy)
            results_to_send = truncated_results
            results_json = json.dumps(truncated_results, indent=2)
            truncated = True
        else:
            results_to_send = results
            truncated = False

        sections_to_send = sum(len(c.get("sections", [])) for c in results_to_send)

        context += (
            f"There are exactly {sections_to_send} section(s) in the JSON below for '{keyword_display}'.\n"
            f"IMPORTANT: In your one-line summary you MUST say exactly 'Found {sections_to_send} section(s)' "
            f"(or 'Found {sections_to_send} matching section(s)')—the count must match the number of sections you list.\n"
        )

        if filter_bits:
            context += "Filters applied: " + ", ".join(filter_bits) + "\n"
            context += (
                "The JSON data below has been PRE-FILTERED to match these exact criteria. "
                "Show ONLY the sections in this data.\n"
            )
            if instructor_mentioned:
                context += (
                    f"NOTE: User specifically asked about instructor '{instructor_mentioned}' "
                    "- show ONLY sections taught by this instructor.\n"
                )

        context += "\nHere is the JSON data (already filtered):\n" + results_json

        system_message = {
            "role": "system",
            "content": (
                "You are a DVC course assistant. Your job is to turn PRE-FILTERED JSON "
                "into a clear, student-friendly answer.\n"
                "You maintain conversation context and can answer follow-up questions.\n\n"
                "CORE PRINCIPLES\n"
                "1) Use ONLY the JSON provided in the conversation. Do not invent or infer missing data.\n"
                "2) The JSON is already PRE-FILTERED to match the user's request. Respect those filters exactly.\n"
                "3) If the assistant context lists filters (e.g., Instructor: Lo), show ONLY sections that match them.\n"
                "4) Never include sections that fail the filters.\n"
                "5) Present results clearly, concisely, and consistently for fast scanning.\n"
                "6) CONVERSATION CONTEXT: Remember previous questions and answers. "
                "If the user asks a follow-up (e.g., \"What about evening?\", \"Who teaches that?\"), "
                "reference the previous course/subject they asked about.\n\n"
                "FOLLOW-UP HANDLING\n"
                "- If user says \"that course\", \"those classes\", \"the same one\", etc., "
                "refer to the most recent course discussed.\n"
                "- - If the user asks for a new filter (e.g., \"what about evening?\") that is NOT already reflected in the provided JSON, do NOT claim you filtered. Ask a short clarifying question or instruct the user to run a new search with that filter."
                "- If unclear, ask for clarification while being helpful.\n\n"
                "PREREQUISITE CHAIN ANALYSIS\n"
                "- If user asks \"Can I take X and Y together?\" or \"Can I take X with Y?\" check required prerequisites only:\n"
                "  * Use 'prereq' as required prerequisites.\n"
                "  * Use 'advisory' as recommended background only, not a blocker.\n"
                "  * If X is listed inside Y's required prerequisites, then X must be completed first.\n"
                "  * If Y is listed inside X's required prerequisites, then Y must be completed first.\n"
                "  * Advisory alone should never be treated as a hard requirement.\n"
                "  * If neither course requires the other, they can be taken together unless there is a schedule conflict.\n"
                "- Provide a clear recommendation and distinguish required vs recommended.\n\n"
                "OUTPUT STRUCTURE\n"
                "A) One-line Summary:\n"
                "- Use the EXACT count from the assistant context message. "
                "Do NOT recount the JSON yourself.\n"
                "- Briefly restate the user's goal and show this count.\n"
                "- If no results, return a short, helpful message and stop.\n"
                "- For follow-ups, acknowledge the context.\n\n"
                "B) Per-Course Listing (for EVERY course in the JSON):\n"
                "- Format: **COURSE_CODE: Course Title**\n"
                "- Group sections into THREE headings (always in this order):\n"
                "    ### HYBRID SECTIONS (includes in-person meetings)\n"
                "    ### IN-PERSON SECTIONS (fully in-person)\n"
                "    ### ONLINE SECTIONS\n"
                "- Under each heading, list ALL matching sections or write \"No [category] sections found.\"\n"
                "- For each section, show: Section number, Instructor, Days, Time, Location, Units\n"
                "- When present and relevant, also mention Notes, Prerequisites, and Advisory.\n"
                "- Keep notes brief and only when present in the JSON.\n"
                "- If a section has comments/notes, include them when relevant, especially for restrictions, learning communities, online access instructions, or special enrollment requirements.\n"
                "- If a section has prerequisites or advisory and the user's question relates to requirements, mention them clearly and distinguish required prerequisites from recommended advisory.\n\n"
                "C) Friendly Wrap-Up:\n"
                "- Add 1-2 actionable \"Next steps\".\n\n"
                "STYLE & TONE\n"
                "- Use bullet lists; avoid long paragraphs.\n"
                "- Be consistent in label order and punctuation.\n"
                "- Keep it positive and helpful, but terse.\n"
                "- Be conversational and remember what the user asked before.\n\n"
                "POLICY BOUNDARIES\n"
                "- Do not give medical, legal, or financial advice. If the user asks, say you can only help with DVC courses and transfer info.\n"
                "- Do not provide relationship or emotional support advice. If the user needs such support, politely say you can only help with DVC courses and transfer and suggest they contact campus counseling or student services.\n\n"
                "SCOPE / REDIRECT\n"
                "- If the user's latest message is only about emotional support, relationship issues, GE requirements without a specific course, or is off-topic, respond with a brief redirect only (e.g. suggest DVC Counseling for personal/relationship issues, or \"Which campus? I can help with UCB, UCD, UCSD\" for GE/UC). Do not list any course sections and do not reuse section data from previous turns.\n\n"
                "NEVER DO\n"
                "- Do not reprint the raw JSON.\n"
                "- Do not add categories beyond the three specified.\n"
                "- Do not include sections that are not in the provided JSON.\n"
                "- Do not forget the conversation context."
            ),
        }

        messages = [system_message]
        if conversation_history:
            messages.extend(conversation_history[-4:])
        messages.append({"role": "user", "content": user_query})
        messages.append({"role": "user", "content": context})

        try:
            llm_response = self.client.chat.completions.create(
                model="gpt-4.1",
                temperature=response_temperature,
                messages=messages,
                timeout=OPENAI_TIMEOUT_SECONDS,
            )
            return llm_response.choices[0].message.content.strip()

        except (httpx.TimeoutException, httpx.ReadTimeout):
            print("⚠️ OpenAI formatting request timed out.")
            return "The assistant is taking too long to respond. Please try again."

        except Exception as e:
            print(f"⚠️ OpenAI formatting error: {e}")
            return "The assistant encountered an unexpected error. Please try again."