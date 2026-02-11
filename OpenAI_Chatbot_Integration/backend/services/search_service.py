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
from datetime import datetime, timezone

from backend.models import db
from backend.models.interaction_log import InteractionLog


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
    """Stateless service that searches course data and orchestrates the LLM."""

    def __init__(self, course_data: list, openai_client):
        """
        Args:
            course_data: The list of course dicts loaded from Full_STEM_DataBase.json
            openai_client: An initialized ``openai.OpenAI`` client instance
        """
        self.data = course_data
        self.client = openai_client

    # ------------------------------------------------------------------
    #  search_courses  (was the top-level function in app.py, lines 116-406)
    # ------------------------------------------------------------------
    def search(self, keyword, mode=None, status=None,
               day_filter=None, time_filter=None, instructor_filter=None):
        """Return courses filtered by code/title, and optionally by format/status/day/time/instructor.

        Supports 'or'/'and' in filters and compound day+time conditions.
        """
        # Detect compound conditions (day+time combos separated by "or")
        compound_conditions = []
        if day_filter and time_filter and " or " in f"{day_filter} {time_filter}".lower():
            combined = f"{day_filter} {time_filter}".lower()
            if "morning" in combined or "afternoon" in combined or "evening" in combined:
                or_parts = combined.split(" or ")

                name_to_code = {
                    "monday": "M", "mon": "M", "m": "M",
                    "tuesday": "T", "tue": "T", "tues": "T", "t": "T",
                    "wednesday": "W", "wed": "W", "w": "W",
                    "thursday": "Th", "thu": "Th", "thur": "Th", "thurs": "Th", "th": "Th",
                    "friday": "F", "fri": "F", "f": "F",
                }

                for part in or_parts:
                    part = part.strip()
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

        # Normalize flexible filters
        mode_norm = _normalize_mode(mode)
        status_norm = _normalize_status(status)
        instr_norm = _normalize_instructor(instructor_filter)
        time_terms, time_all = _normalize_time(time_filter)
        day_terms, day_all = _normalize_day(day_filter)

        # Handle keyword as list or string
        keywords = [k.lower() for k in (keyword if isinstance(keyword, list) else [keyword])]

        results = []
        for course in self.data:
            course_code_lower = course["course_code"].lower()
            course_title_lower = course["course_title"].lower()

            if not any(kw in course_code_lower or kw in course_title_lower for kw in keywords):
                continue

            filtered_sections = []
            for section in course["sections"]:
                stat = section["status"].lower()

                if not section.get("meetings"):
                    continue

                # Derive section_format from all meetings
                all_formats = set(
                    m["format"].lower() for m in section["meetings"] if m.get("format")
                )
                if "hybrid" in all_formats or len(all_formats) > 1:
                    section_format = "hybrid"
                elif "in-person" in all_formats:
                    section_format = "in-person"
                elif "online" in all_formats:
                    section_format = "online"
                else:
                    section_format = list(all_formats)[0] if all_formats else ""

                # MODE: OR semantics
                if mode_norm and section_format not in mode_norm:
                    continue

                # STATUS: OR semantics on substring tokens
                if status_norm and not any(s in stat for s in status_norm):
                    continue

                # INSTRUCTOR: OR semantics with flexible name matching
                if instr_norm:
                    instructor = section.get("instructor", "").lower()
                    matched = False
                    for name_query in instr_norm:
                        query_tokens = [
                            token.strip().lower()
                            for token in name_query.replace(",", " ").split()
                            if token.strip()
                        ]
                        if all(token in instructor for token in query_tokens):
                            matched = True
                            break
                    if not matched:
                        continue

                # DAY/TIME: per-meeting checks with AND/OR semantics and compound conditions
                if compound_conditions:
                    has_matching_meeting = False
                    for meeting in section.get("meetings", []):
                        days = meeting.get("days", "") or ""
                        time_str = meeting.get("time", "")

                        for required_day, required_time in compound_conditions:
                            day_match = _has_day_code(required_day, days)

                            time_match = False
                            if time_str and time_str.lower() != "asynchronous":
                                hour = _parse_start_hour(time_str)
                                if hour is not None:
                                    time_match = (_time_bucket(hour) == required_time)

                            if day_match and time_match:
                                has_matching_meeting = True
                                break

                        if has_matching_meeting:
                            break

                    if not has_matching_meeting:
                        continue

                elif day_terms or time_terms:
                    has_matching_meeting = False
                    for meeting in section.get("meetings", []):
                        days = meeting.get("days", "") or ""
                        time_str = meeting.get("time", "")

                        # Day check
                        day_ok = True
                        if day_terms:
                            if day_all:
                                day_ok = all(_has_day_code(c, days) for c in day_terms)
                            else:
                                day_ok = any(_has_day_code(c, days) for c in day_terms)

                        # Time check
                        time_ok = True
                        if time_terms and time_str and time_str.lower() != "asynchronous":
                            hour = _parse_start_hour(time_str)
                            if hour is not None:
                                bucket = _time_bucket(hour)
                                if time_all:
                                    time_ok = all(t == bucket for t in time_terms)
                                else:
                                    time_ok = any(t == bucket for t in time_terms)
                            else:
                                time_ok = False

                        if day_ok and time_ok:
                            has_matching_meeting = True
                            break

                    if not has_matching_meeting:
                        continue

                filtered_sections.append(section)

            if filtered_sections:
                result = {
                    "course_code": course["course_code"],
                    "course_title": course["course_title"],
                    "sections": filtered_sections,
                }
                if "prerequisites" in course:
                    result["prerequisites"] = course["prerequisites"]
                results.append(result)

        return results

    # ------------------------------------------------------------------
    #  llm_parse_query  (was top-level in app.py, lines 408-511)
    # ------------------------------------------------------------------
    def parse_query(self, user_query: str, *, temperature: float = 0.0) -> dict:
        """LLM-first parser -> course_codes, subjects, intent, filters (constrained to DB)."""
        all_course_codes = sorted({c["course_code"].upper() for c in self.data})
        all_subject_prefixes = sorted({c["course_code"].split("-")[0].upper() for c in self.data})

        allowed_titles_payload = [
            {"course_code": c["course_code"].upper(), "course_title": c.get("course_title", "")}
            for c in self.data
            if c.get("course_title")
        ]

        parser_system = (
            "You are an intent and entity parser for a community college course finder. "
            "Normalize and correct typos in the user's text (e.g., 'avalibale'→'available', "
            "'phycs'→'PHYS', 'prof julli'→'Julie') before extracting entities. "
            "Return STRICT JSON ONLY (no prose/markdown) with keys:\n"
            "{\n"
            '  \"course_codes\": [list of exact course codes like \"COMSC-110\"],\n'
            '  \"subjects\": [list of subject prefixes like \"COMSC\",\"MATH\"],\n'
            '  \"intent\": \"find_sections\" | \"prerequisites\" | \"instructors\",\n'
            '  \"filters\": {\n'
            '     \"mode\": \"in-person\" | \"online\" | \"hybrid\" | null,\n'
            '     \"status\": \"open\" | \"closed\" | null,\n'
            '     \"day\": \"M\" | \"T\" | \"W\" | \"Th\" | \"F\" | null (can include "and"/"or" like "M and W" or "T or Th"),\n'
            '     \"time\": \"morning\" | \"afternoon\" | \"evening\" | null (can include "and"/"or" like "morning and afternoon"),\n'
            '     \"instructor\": string or null\n'
            "  }\n"
            "}\n"
            "IMPORTANT - AND vs OR logic:\n"
            "- If user says 'Monday AND Wednesday' or 'M and W', they want sections that meet on BOTH days\n"
            "- If user says 'Monday OR Wednesday' or 'M or W', they want sections that meet on EITHER day\n"
            "- Same logic for time: 'morning AND afternoon' (meets both) vs 'morning OR afternoon' (meets either)\n"
            "- Include the 'and'/'or' in your filter string so backend can process it correctly\n"
            "\n"
            "COMPOUND CONDITIONS (VERY IMPORTANT):\n"
            "- If user says 'Monday morning OR Thursday afternoon', this is a COMPOUND condition\n"
            "- Pass it as: day='Monday or Thursday', time='morning or afternoon' (backend will parse the compound logic)\n"
            "- The backend detects compound patterns and matches sections with (Monday AND morning) OR (Thursday AND afternoon)\n"
            "- Other examples: 'Tuesday evening or Friday morning', 'Wednesday afternoon or Monday evening'\n"
            "Rules:\n"
            "- Only choose course_codes from ALLOWED_COURSE_CODES.\n"
            "- Only choose subjects from ALLOWED_SUBJECT_PREFIXES.\n"
            "- TITLE MAPPING (VERY IMPORTANT):\n"
            "  * If user says 'calculus classes' or 'calculus courses' (plural/general), find ALL courses with 'Calculus' in title\n"
            "  * If user says 'Calc 1' or 'Calculus 1' or 'Calculus I', match ONLY courses with 'Calculus I' in title\n"
            "  * If user says 'Calc 2' or 'Calculus 2' or 'Calculus II', match ONLY courses with 'Calculus II' in title\n"
            "  * If user says 'Calc 3' or 'Calculus 3' or 'Calculus III', match ONLY courses with 'Calculus III' in title\n"
            "  * Similar logic for 'Physics', 'Chemistry', 'Biology', 'Computer Science', etc.\n"
            "  * Be precise: 'Calc 1' ≠ 'Calculus for Business' (only match courses with roman numeral I)\n"
            "- Search ALLOWED_TITLES by matching course titles (case/typo-insensitive substring matching).\n"
            "- When mapping titles to codes, look at the actual course_title field in ALLOWED_TITLES.\n"
            "- If the user asks about prerequisites/prereq, set intent='prerequisites'.\n"
            "- If the user asks about professor/instructor/teacher/who teaches, set intent='instructors'.\n"
            "- Otherwise default to intent='find_sections'.\n"
            "- Extract simple filters if present; else use nulls."
        )

        parser_user = json.dumps({
            "USER_QUERY": user_query,
            "ALLOWED_COURSE_CODES": all_course_codes,
            "ALLOWED_SUBJECT_PREFIXES": all_subject_prefixes,
            "ALLOWED_TITLES": allowed_titles_payload,
            "NOTES": "Days may be written as Monday/Mon/Tues/Thursday/etc.; map to M,T,W,Th,F.",
        })

        try:
            resp = self.client.chat.completions.create(
                model="gpt-4.1",
                temperature=temperature,
                messages=[
                    {"role": "system", "content": parser_system},
                    {"role": "user", "content": parser_user},
                ],
            )
            parsed = json.loads(resp.choices[0].message.content.strip())
        except Exception:
            parsed = {}

        # ---- Normalize + guard ----
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

        parsed["course_codes"] = [str(c).upper() for c in parsed["course_codes"] if isinstance(c, str)]
        parsed["subjects"] = [str(s).upper() for s in parsed["subjects"] if isinstance(s, str)]
        if not isinstance(parsed["filters"], dict):
            parsed["filters"] = {
                "mode": None, "status": None, "day": None, "time": None, "instructor": None,
            }

        # ---- Final allow-list enforcement ----
        parsed["course_codes"] = [c for c in parsed["course_codes"] if c in all_course_codes]
        parsed["subjects"] = [s for s in parsed["subjects"] if s in all_subject_prefixes]

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

        parsed = self.parse_query(enhanced_query, temperature=parser_temperature)

        course_codes = parsed.get("course_codes", [])
        subjects = parsed.get("subjects", [])
        intent = parsed.get("intent", "find_sections")
        filters = parsed.get("filters", {}) or {}
        mode = filters.get("mode")
        status = filters.get("status")
        day_filter = filters.get("day")
        time_filter = filters.get("time")
        instructor_mentioned = filters.get("instructor")

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

        # Nothing useful parsed → guide the user
        if not course_codes and not subjects:
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
                self.log_interaction(user_query, parsed, response, start_ms)
            return response

        # ------ Prerequisite intent ------
        if intent == "prerequisites":
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

        if enable_logging:
            self.log_interaction(user_query, parsed, response, start_ms)
        return response

    # ------------------------------------------------------------------
    #  Logging  (writes to InteractionLog SQL table)
    # ------------------------------------------------------------------
    def log_interaction(self, user_query: str, parsed_data: dict,
                        response: str, start_ms: float | None = None):
        """Persist an interaction to the interaction_logs table."""
        latency = None
        if start_ms is not None:
            latency = int((time.perf_counter() - start_ms) * 1000)

        try:
            log_entry = InteractionLog(
                timestamp=datetime.now(timezone.utc),
                user_query=user_query,
                parsed_data=parsed_data,
                ai_response=response,
                latency_ms=latency,
            )
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
                        course_prereqs[code] = r.get("prerequisites", "")
                        break

            response = f"**Can you take {' and '.join(course_codes)} together?**\n\n"
            conflict_found = False
            for i, code1 in enumerate(course_codes):
                for code2 in course_codes[i + 1:]:
                    prereq1 = course_prereqs.get(code1, "").upper()
                    prereq2 = course_prereqs.get(code2, "").upper()

                    if code1.upper() in prereq2:
                        response += (
                            f"❌ **No** - {code2} requires {code1} as a prerequisite, "
                            f"so you must complete {code1} first.\n\n"
                            f"**{code2} prerequisites:** {course_prereqs.get(code2, 'Not listed')}\n"
                        )
                        conflict_found = True
                        break
                    elif code2.upper() in prereq1:
                        response += (
                            f"❌ **No** - {code1} requires {code2} as a prerequisite, "
                            f"so you must complete {code2} first.\n\n"
                            f"**{code1} prerequisites:** {course_prereqs.get(code1, 'Not listed')}\n"
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
                    prereq = course_prereqs.get(code, "No prerequisites listed")
                    response += f"**{code}:** {prereq}\n"
                response += (
                    "\n💡 Just make sure there are no schedule conflicts "
                    "between the sections you choose!"
                )

            if enable_logging:
                self.log_interaction(user_query, parsed, response, start_ms)
            return response

        # Regular prerequisite lookup
        if results:
            chosen = None
            if course_codes:
                wanted = set(course_codes)
                for r in results:
                    if r["course_code"].upper() in wanted:
                        chosen = r
                        break
            if not chosen:
                chosen = results[0]
            prereqs = chosen.get("prerequisites", "No prerequisites listed")
            response = f"**{chosen['course_code']}: {chosen['course_title']}**\n\nPrerequisites: {prereqs}"
            if enable_logging:
                self.log_interaction(user_query, parsed, response, start_ms)
            return response

        kw_display = ", ".join(keywords_for_prereq) if isinstance(keywords_for_prereq, list) else keywords_for_prereq
        response = (
            f"I couldn't find any courses for **{kw_display}**.\n"
            "Double-check the course code/subject, or try another course (e.g., COMSC-110, MATH-193)."
        )
        if enable_logging:
            self.log_interaction(user_query, parsed, response, start_ms)
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
            self.log_interaction(user_query, parsed, response, start_ms)
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
        total_sections_original = sum(len(c.get("sections", [])) for c in results)

        context += (
            f"I found {len(results)} matching course(s) with "
            f"{total_sections_original} total section(s) for '{keyword_display}'.\n"
        )

        if truncated:
            context += (
                f"NOTE: Showing {sections_to_send} sections below (truncated for brevity). "
                f"When you write your summary, say 'Found {sections_to_send} section(s)' "
                "to match what you're displaying.\n"
            )
        else:
            context += (
                f"IMPORTANT: When you write the summary, say 'Found {sections_to_send} section(s)' "
                "- this matches the exact count in the JSON below.\n"
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
                "1) Use ONLY the JSON in the assistant message. Do not invent or infer missing data.\n"
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
                "- If user asks \"what about [filter]?\", apply the new filter to the previous search.\n"
                "- If unclear, ask for clarification while being helpful.\n\n"
                "PREREQUISITE CHAIN ANALYSIS\n"
                "- If user asks \"Can I take X and Y together?\" or \"Can I take X with Y?\" check prerequisites:\n"
                "  * Look at X's prerequisites - does it require Y? If yes, must take Y first.\n"
                "  * Look at Y's prerequisites - does it require X? If yes, must take X first.\n"
                "  * If one requires the other → NO, they cannot be taken together.\n"
                "  * If neither requires the other → YES, they can be taken together (check for time conflicts too).\n"
                "- Provide clear recommendation.\n\n"
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
                "- Keep notes brief and only when present in the JSON.\n\n"
                "C) Friendly Wrap-Up:\n"
                "- Add 1-2 actionable \"Next steps\".\n\n"
                "STYLE & TONE\n"
                "- Use bullet lists; avoid long paragraphs.\n"
                "- Be consistent in label order and punctuation.\n"
                "- Keep it positive and helpful, but terse.\n"
                "- Be conversational and remember what the user asked before.\n\n"
                "NEVER DO\n"
                "- Do not reprint the raw JSON.\n"
                "- Do not add categories beyond the three specified.\n"
                "- Do not include sections that are not in the provided JSON.\n"
                "- Do not forget the conversation context."
            ),
        }

        messages = [system_message]
        if conversation_history:
            messages.extend(conversation_history[-10:])
        messages.append({"role": "user", "content": user_query})
        messages.append({"role": "assistant", "content": context})

        llm_response = self.client.chat.completions.create(
            model="gpt-4.1",
            temperature=response_temperature,
            messages=messages,
        )
        return llm_response.choices[0].message.content.strip()
