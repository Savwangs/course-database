import os
import json
from pathlib import Path
from flask import Flask, render_template, request, jsonify
from openai import OpenAI
from dotenv import load_dotenv
from datetime import datetime

# Load environment variables
load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Initialize Flask app
app = Flask(__name__)

# Load course database
db_path = Path(__file__).parent.parent / "dvc_scraper" / "Full_STEM_DataBase.json"

if not db_path.exists():
    raise FileNotFoundError(f"❌ Could not find database at: {db_path}")

with open(db_path, "r", encoding="utf-8") as f:
    course_data = json.load(f)

print(f"✅ Loaded {len(course_data)} courses from {db_path}")

# === LOGGING MODULE ===
log_file_path = Path(__file__).parent / "user_log.json"

def log_interaction(user_prompt: str, parsed_data: dict, response: str):
    """
    Log user interactions to a JSON file with automatic appending.
    
    Args:
        user_prompt: The raw user query
        parsed_data: The parsed query parameters from LLM
        response: The formatted response returned to user
    """
    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "user_prompt": user_prompt,
        "parsed_data": parsed_data,
        "response": response
    }
    
    # Load existing logs or create new list
    if log_file_path.exists():
        try:
            with open(log_file_path, "r", encoding="utf-8") as f:
                logs = json.load(f)
            if not isinstance(logs, list):
                logs = []
        except (json.JSONDecodeError, Exception):
            logs = []
    else:
        logs = []
    
    # Append new entry
    logs.append(log_entry)
    
    # Write back to file
    with open(log_file_path, "w", encoding="utf-8") as f:
        json.dump(logs, f, indent=2, ensure_ascii=False)
    
    print(f"📝 Logged interaction to {log_file_path}")

def search_courses(keyword, mode=None, status=None, day_filter=None, time_filter=None, instructor_filter=None):
    """Return courses filtered by code/title, and optionally by format/status/day/time/instructor.
       Now supports 'or'/'and' in filters. Examples:
       - mode:        "online or hybrid"
       - status:      "open or waitlist"
       - day_filter:  "M and W", "T or Th", "Mon and Wed", "Tue/Thu"
       - time_filter: "morning or evening"
       - instructor:  "Lo or Julie"
    """
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

    # Normalize flexible filters
    mode_norm = _normalize_mode(mode)                      # list[str] or None
    status_norm = _normalize_status(status)                # list[str] or None
    instr_norm = _normalize_instructor(instructor_filter)  # list[str] or None
    time_terms, time_all = _normalize_time(time_filter)    # list[str], bool
    day_terms, day_all = _normalize_day(day_filter)        # list[str], bool

    # Handle keyword as list or string
    keywords = [k.lower() for k in (keyword if isinstance(keyword, list) else [keyword])]

    results = []
    for course in course_data:
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
            all_formats = set(m["format"].lower() for m in section["meetings"] if m.get("format"))
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

            # INSTRUCTOR: OR semantics on substrings
            if instr_norm:
                instructor = section.get("instructor", "").lower()
                if not any(name.lower() in instructor for name in instr_norm):
                    continue

            # DAY/TIME: per-meeting checks with AND/OR semantics
            if day_terms or time_terms:
                has_matching_meeting = False
                for meeting in section.get("meetings", []):
                    days = meeting.get("days", "") or ""
                    time_str = meeting.get("time", "")

                    # Day check
                    day_ok = True
                    if day_terms:
                        def _has_day(code):
                            if code == "Th":
                                return "Th" in days
                            return code in days
                        day_ok = all(_has_day(c) for c in day_terms) if day_all else any(_has_day(c) for c in day_terms)

                    # Time check
                    time_ok = True
                    if time_terms and time_str and time_str.lower() != "asynchronous":
                        try:
                            start_raw = time_str.split("-")[0].strip()
                            if "PM" in start_raw and not start_raw.startswith("12"):
                                hour = int(start_raw.split(":")[0]) + 12
                            elif "AM" in start_raw and start_raw.startswith("12"):
                                hour = 0
                            else:
                                hour = int(start_raw.split(":")[0])

                            def _bucket(h):
                                if h < 12: return "morning"
                                if 12 <= h < 17: return "afternoon"
                                return "evening"

                            bucket = _bucket(hour)
                            time_ok = all(t == bucket for t in time_terms) if time_all else any(t == bucket for t in time_terms)
                        except:
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
                "sections": filtered_sections
            }
            if "prerequisites" in course:
                result["prerequisites"] = course["prerequisites"]
            results.append(result)

    return results

def llm_parse_query(user_query: str, *, temperature: float = 0.0):
    """LLM-first parser → course_codes, subjects, intent, filters (constrained to DB).
    Title→code matching is delegated entirely to the LLM (no local alias logic)."""
    # ----- Allow-lists from DB -----
    all_course_codes = sorted({c["course_code"].upper() for c in course_data})
    all_subject_prefixes = sorted({c["course_code"].split("-")[0].upper() for c in course_data})

    # Provide titles to the LLM for title↔code mapping
    allowed_titles_payload = [
        {"course_code": c["course_code"].upper(), "course_title": c.get("course_title", "")}
        for c in course_data
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
        '     \"day\": \"M\" | \"T\" | \"W\" | \"Th\" | \"F\" | null,\n'
        '     \"time\": \"morning\" | \"afternoon\" | \"evening\" | null,\n'
        '     \"instructor\": string or null\n'
        "  }\n"
        "}\n"
        "Rules:\n"
        "- Only choose course_codes from ALLOWED_COURSE_CODES.\n"
        "- Only choose subjects from ALLOWED_SUBJECT_PREFIXES.\n"
        "- If the user mentions a course by TITLE (e.g., 'differential equations', 'human biology'), "
        "  map it to the corresponding code(s) by looking it up in ALLOWED_TITLES (case/typo-insensitive) "
        "  and place those into course_codes.\n"
        "- If the user asks about prerequisites/prereq, set intent='prerequisites'.\n"
        "- If the user asks about professor/instructor/teacher/who teaches, set intent='instructors'.\n"
        "- Otherwise default to intent='find_sections'.\n"
        "- Extract simple filters if present; else use nulls."
    )

    parser_user = json.dumps({
        "USER_QUERY": user_query,
        "ALLOWED_COURSE_CODES": all_course_codes,
        "ALLOWED_SUBJECT_PREFIXES": all_subject_prefixes,
        "ALLOWED_TITLES": allowed_titles_payload,  # LLM uses this to map titles → codes
        "NOTES": "Days may be written as Monday/Mon/Tues/Thursday/etc.; map to M,T,W,Th,F."
    })

    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            temperature=temperature,  # deterministic parsing
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
    parsed.setdefault("filters", {"mode": None, "status": None, "day": None, "time": None, "instructor": None})

    parsed["course_codes"] = [str(c).upper() for c in parsed["course_codes"] if isinstance(c, str)]
    parsed["subjects"] = [str(s).upper() for s in parsed["subjects"] if isinstance(s, str)]
    if not isinstance(parsed["filters"], dict):
        parsed["filters"] = {"mode": None, "status": None, "day": None, "time": None, "instructor": None}

    # ---- Final allow-list enforcement ----
    parsed["course_codes"] = [c for c in parsed["course_codes"] if c in all_course_codes]
    parsed["subjects"] = [s for s in parsed["subjects"] if s in all_subject_prefixes]

    return parsed


def ask_course_assistant(user_query: str, *, parser_temperature: float = 0.0, response_temperature: float = 0.1, enable_logging: bool = True):
    """LLM parses → we search → LLM formats. Includes fallbacks + out-of-scope and no-results handling."""
    query_lower = user_query.lower()
    parsed = llm_parse_query(user_query, temperature=parser_temperature)

    course_codes = parsed.get("course_codes", [])
    subjects = parsed.get("subjects", [])
    intent = parsed.get("intent", "find_sections")
    filters = parsed.get("filters", {}) or {}
    mode = filters.get("mode"); status = filters.get("status")
    day_filter = filters.get("day"); time_filter = filters.get("time")
    instructor_mentioned = filters.get("instructor")

    # Optional: map "available/avaliable/avail" → open (parity with user phrasing)
    if not status and ("available" in query_lower or "avaliable" in query_lower or "avail" in query_lower):
        status = "open"

    # Match previous behavior: "in-person" also includes "hybrid"
    if mode == "in-person":
        mode = ["in-person", "hybrid"]

    # Instructor title fallback (prof/Dr/instructor + next token)
    if not instructor_mentioned:
        titles = {"professor", "prof", "dr", "instructor", "teacher"}
        words = user_query.split()
        for i, w in enumerate(words):
            if w.strip(",.?!").lower() in titles and i + 1 < len(words):
                instructor_mentioned = words[i+1].strip(",.?!")
                break

    # If the parse yields nothing useful, treat as out-of-scope/nonspecific and guide the user.
    if not course_codes and not subjects:
        response = (
            "I can help you find DVC STEM courses and details like sections, instructors, and prerequisites.\n\n"
            "Try one of these:\n"
            '- "Show me open MATH-193 sections Monday morning."\n'
            '- "Who teaches PHYS-130 on Thursdays?"\n'
            '- "What are the prerequisites for COMSC-200?"\n'
            '- "Show online COMSC classes."\n\n'
            "Please include a subject (e.g., COMSC, MATH, PHYS, CHEM, BIOSC, ENGIN) or a specific course code (e.g., COMSC-110)."
        )
        if enable_logging:
            log_interaction(user_query, parsed, response)
        return response

    # Fast path for prerequisite intent
    if intent == "prerequisites":
        keywords_for_prereq = course_codes or subjects
        results = search_courses(keywords_for_prereq)
        if results:
            chosen = None
            if course_codes:
                wanted = set(course_codes)
                for r in results:
                    if r["course_code"].upper() in wanted:
                        chosen = r; break
            if not chosen:
                chosen = results[0]
            prereqs = chosen.get("prerequisites", "No prerequisites listed")
            response = f"**{chosen['course_code']}: {chosen['course_title']}**\n\nPrerequisites: {prereqs}"
            if enable_logging:
                log_interaction(user_query, parsed, response)
            return response
        response = (
            f"I couldn't find any courses for **{', '.join(keywords_for_prereq) if isinstance(keywords_for_prereq, list) else keywords_for_prereq}**.\n"
            "Double-check the course code/subject, or try another course (e.g., COMSC-110, MATH-193)."
        )
        if enable_logging:
            log_interaction(user_query, parsed, response)
        return response

    # Search with parsed filters
    keyword = course_codes if course_codes else subjects
    results = search_courses(keyword, mode, status, day_filter, time_filter, instructor_mentioned)

    # If nothing matched under the current filters, try unfiltered to diagnose
    if not results:
        baseline = search_courses(keyword, mode=None, status=None, day_filter=None, time_filter=None, instructor_filter=None)
        # Build a short filter description to show the user what was applied
        applied = []
        if mode: applied.append(f"mode={mode if isinstance(mode, str) else ','.join(mode)}")
        if status: applied.append(f"status={status}")
        if day_filter: applied.append(f"day={day_filter}")
        if time_filter: applied.append(f"time={time_filter}")
        if instructor_mentioned: applied.append(f"instructor={instructor_mentioned}")
        applied_str = ", ".join(applied) if applied else "none"

        if not baseline:
            # Nothing exists for this keyword at all (likely wrong code/prefix)
            response = (
                f"I couldn't find any courses for **{', '.join(keyword) if isinstance(keyword, list) else keyword}**.\n"
                "Please check the **subject/prefix** or **course code**, or try a broader query.\n\n"
                "**Examples:**\n"
                '- "Show **COMSC** classes."\n'
                '- "Find **MATH-193** sections."\n'
                '- "Any **online PHYS** this **evening**?"'
            )
            if enable_logging:
                log_interaction(user_query, parsed, response)
            return response
        else:
            # The course/subject exists, but filters were too strict
            response = (
                f"I found **no sections** with your current filters (**{applied_str}**) for "
                f"**{', '.join(keyword) if isinstance(keyword, list) else keyword}**.\n\n"
                "Try relaxing one or more filters. For example:\n"
                "- Remove the **instructor** name to see all sections\n"
                "- Try a different **day** or **time** window\n"
                "- Include **hybrid** or **online** if you only searched in-person\n\n"
                "Want me to show **all available sections** for this course/subject?"
            )
            if enable_logging:
                log_interaction(user_query, parsed, response)
            return response

    # Build formatting context (matches your original assistant prompt shape)
    if isinstance(keyword, list):
        is_subject_search = all("-" not in k for k in keyword)
        keyword_display = " and ".join(keyword)
    else:
        is_subject_search = "-" not in keyword
        keyword_display = keyword
    truncate_limit = 8000 if is_subject_search else 4000

    filter_bits = []
    if day_filter: filter_bits.append(f"Day: {day_filter}")
    if time_filter: filter_bits.append(f"Time: {time_filter}")
    if instructor_mentioned: filter_bits.append(f"Instructor: {instructor_mentioned}")
    if status: filter_bits.append(f"Status: {status}")
    if mode: filter_bits.append(f"Mode: {mode if isinstance(mode, str) else ','.join(mode)}")

    context = f"User asked: '{user_query}'\n\n"
    context += f"I found {len(results)} matching course(s) for '{keyword_display}'.\n"
    if filter_bits: 
        context += "Filters applied: " + ", ".join(filter_bits) + "\n"
        context += "IMPORTANT: The JSON data below has been PRE-FILTERED to match these exact criteria. Show ONLY the sections in this data.\n"
        if instructor_mentioned:
            context += f"NOTE: User specifically asked about instructor '{instructor_mentioned}' - show ONLY sections taught by this instructor.\n"
    context += "\nHere is the JSON data (already filtered):\n" + json.dumps(results, indent=2)[:truncate_limit]

    # LLM formatter (explicit temperature)
    llm_response = client.chat.completions.create(
        model="gpt-4o-mini",
        temperature=response_temperature,
        messages=[
            {
                "role": "system",
                "content": """You are a DVC course assistant. Your job is to turn PRE-FILTERED JSON into a clear, student-friendly answer.

            CORE PRINCIPLES
            1) Use ONLY the JSON in the assistant message. Do not invent or infer missing data.
            2) The JSON is already PRE-FILTERED to match the user's request. Respect those filters exactly.
            3) If the assistant context lists filters (e.g., Instructor: Lo), show ONLY sections that match them.
            4) Never include sections that fail the filters.
            5) Present results clearly, concisely, and consistently for fast scanning.

            OUTPUT STRUCTURE
            A) One-line Summary:
            - Briefly restate the user's goal and show a quick count (e.g., "Found 3 sections for MATH-193 (Mon, morning).").
            - If no results, return a short, helpful message and stop (also include 1–3 next-step suggestions).

            B) Per-Course Listing (for EVERY course in the JSON):
            - Format: **COURSE_CODE: Course Title**
            - Group sections into THREE headings (always in this order):
                ### HYBRID SECTIONS (includes in-person meetings)
                ### IN-PERSON SECTIONS (fully in-person)
                ### ONLINE SECTIONS
            - Under each heading, list ALL matching sections or write "No [category] sections found."
            - For each section, show:
                - Section number
                - Instructor
                - Days
                - Time
                - Location
                - Units
            - Keep notes brief and only when present in the JSON (e.g., essential advisories). Do not paraphrase missing notes.

            C) Friendly Wrap-Up:
            - Add 1-2 actionable "Next steps" (e.g., "Prefer evenings? Say "evening"," "Want online only? Say "online"," "Ask for prerequisites.").

            OPTIONAL ENHANCEMENTS (only when prompted or context indicates)
            - If the user asks for "all available", "more options", or "other available courses", include an extra section:
            **Other available options that meet your filters**
            - List other courses/sections from the provided JSON that satisfy the same filters (still obey all filtering rules).
            - If the assistant context includes articulation or comparison data (e.g., alternatives array), render it in a short, bulleted block after the main listings.
            - If the assistant context includes a flag/text indicating "Show alternatives" or similar, add the above section.

            STYLE & TONE
            - Use bullet lists; avoid long paragraphs.
            - Be consistent in label order and punctuation.
            - Keep it positive and helpful, but terse.

            NEVER DO
            - Do not reprint the raw JSON.
            - Do not add categories beyond the three specified.
            - Do not include sections that are not in the provided JSON.
            """

            },
            {"role": "user", "content": user_query},
            {"role": "assistant", "content": context},
        ],
    )
    final_response = llm_response.choices[0].message.content.strip()
    
    # Log the interaction
    if enable_logging:
        log_interaction(user_query, parsed, final_response)
    
    return final_response

# === FLASK ROUTES ===

@app.route('/')
def index():
    """Serve the landing page"""
    return render_template('landing.html')

@app.route('/chatbot')
def chatbot():
    """Serve the chatbot interface"""
    return render_template('chatbot.html')

@app.route('/ask', methods=['POST'])
def ask():
    """
    API endpoint to handle user queries
    
    Expects JSON: {"query": "user question here"}
    Returns JSON: {"response": "formatted answer", "success": true/false}
    """
    try:
        data = request.get_json()
        
        if not data or 'query' not in data:
            return jsonify({
                'success': False,
                'error': 'No query provided'
            }), 400
        
        user_query = data['query'].strip()
        
        if not user_query:
            return jsonify({
                'success': False,
                'error': 'Empty query'
            }), 400
        
        # Call the chatbot assistant
        response = ask_course_assistant(user_query, enable_logging=True)
        
        return jsonify({
            'success': True,
            'response': response
        })
        
    except Exception as e:
        print(f"❌ Error in /ask route: {str(e)}")
        return jsonify({
            'success': False,
            'error': 'An error occurred processing your request'
        }), 500

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'courses_loaded': len(course_data)
    })

if __name__ == '__main__':
    print("\n" + "="*80)
    print("🎓 DVC Course Assistant - Flask Web App")
    print("="*80)
    print(f"✅ Loaded {len(course_data)} courses")
    print("🌐 Starting server at http://127.0.0.1:5000")
    print("="*80 + "\n")
    app.run(debug=True, host='127.0.0.1', port=5000)