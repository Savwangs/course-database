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
    Also prints to console for cloud platforms like Render where filesystem is ephemeral.
    
    Args:
        user_prompt: The raw user query
        parsed_data: The parsed query parameters from LLM
        response: The formatted response returned to user
    """
    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "user_prompt": user_prompt,
        "parsed_data": parsed_data,
        "response": response[:500] + "..." if len(response) > 500 else response  # Truncate for console
    }
    
    # Always print to console (captured by Render logs)
    print(f"📝 USER LOG: {json.dumps(log_entry, ensure_ascii=False)}")
    
    # Try to write to file (works locally, may not persist on Render due to ephemeral filesystem)
    try:
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
        logs.append({
            "timestamp": datetime.now().isoformat(),
            "user_prompt": user_prompt,
            "parsed_data": parsed_data,
            "response": response
        })
        
        # Write back to file
        with open(log_file_path, "w", encoding="utf-8") as f:
            json.dump(logs, f, indent=2, ensure_ascii=False)
        
        print(f"✅ Logged to file: {log_file_path}")
    except Exception as e:
        # If file logging fails (e.g., on Render), don't crash - console log is already done
        print(f"⚠️ File logging failed (ephemeral filesystem?): {e}")
        print("💡 Logs are still captured in console output (check Render logs)")

def search_courses(keyword, mode=None, status=None, day_filter=None, time_filter=None, instructor_filter=None, filter_logic="AND"):
    """Return courses filtered by code/title, and optionally by format/status/day/time/instructor.
    
    Args:
        keyword: str or list of str - Course code(s) to search for
        mode: str or list of str - Format filter (in-person, online, hybrid)
        status: str - Status filter (open, closed)
        day_filter: str, list - Day code filter (M, T, W, Th, F) or list of days
        time_filter: str, list - Time of day filter (morning, afternoon, evening) or list of times
        instructor_filter: str - Instructor name filter
        filter_logic: str - "AND" (all criteria must match) or "OR" (any criteria can match)
    """
    # Handle keyword as list or string
    if isinstance(keyword, list):
        keywords = [k.lower() for k in keyword]
    else:
        keywords = [keyword.lower()]
    
    results = []
    for course in course_data:
        course_code_lower = course["course_code"].lower()
        course_title_lower = course["course_title"].lower()
        
        # Check if any keyword matches
        match = False
        for kw in keywords:
            if kw in course_code_lower or kw in course_title_lower:
                match = True
                break
        
        if not match:
            continue
        filtered_sections = []
        for section in course["sections"]:
            stat = section["status"].lower()
            
            # Determine the overall format of the section by examining ALL meetings
            if not section.get("meetings"):
                continue
            
            # Get all unique formats from all meetings
            all_formats = set(m["format"].lower() for m in section["meetings"] if m.get("format"))
            
            # Determine section's primary classification
            # If it has multiple different formats OR explicitly says "hybrid", it's hybrid
            if "hybrid" in all_formats or len(all_formats) > 1:
                section_format = "hybrid"
            elif "in-person" in all_formats:
                section_format = "in-person"
            elif "online" in all_formats:
                section_format = "online"
            else:
                section_format = list(all_formats)[0] if all_formats else ""
            
            # Check if mode matches (can be a list of modes or single mode)
            mode_match = False
            if not mode:
                mode_match = True
            elif isinstance(mode, list):
                mode_match = section_format in mode
            else:
                mode_match = mode == section_format
            
            # Apply status filter
            if status and status not in stat:
                continue
            
            if not mode_match:
                continue
            
            # Apply instructor filter
            if instructor_filter:
                instructor = section.get("instructor", "").lower()
                if instructor_filter.lower() not in instructor:
                    continue
            
            # Apply day and time filters by checking meetings
            if day_filter or time_filter:
                # Normalize filters to lists for uniform handling
                day_list = day_filter if isinstance(day_filter, list) else ([day_filter] if day_filter else [])
                time_list = time_filter if isinstance(time_filter, list) else ([time_filter] if time_filter else [])
                
                # Helper function to check if a time matches a time filter
                def time_matches(time_str, time_filter_val):
                    if not time_str or time_str.lower() == "asynchronous":
                        return False
                    try:
                        start_time = time_str.split("-")[0].strip()
                        if "PM" in start_time and not start_time.startswith("12"):
                            hour = int(start_time.split(":")[0]) + 12
                        elif "AM" in start_time and start_time.startswith("12"):
                            hour = 0
                        else:
                            hour = int(start_time.split(":")[0])
                        
                        if time_filter_val == "morning":
                            return hour < 12
                        elif time_filter_val == "afternoon":
                            return 12 <= hour < 17
                        elif time_filter_val == "evening":
                            return hour >= 17
                    except:
                        return False
                    return False
                
                has_matching_meeting = False
                
                if filter_logic == "OR" and day_list and time_list:
                    # OR logic with paired combinations: (day[0]+time[0]) OR (day[1]+time[1]) etc.
                    # Example: "Wednesday mornings OR Thursday afternoons"
                    # Pairs: (W, morning), (Th, afternoon)
                    max_pairs = max(len(day_list), len(time_list))
                    for meeting in section.get("meetings", []):
                        days = meeting.get("days", "")
                        time_str = meeting.get("time", "")
                        
                        # Check if this meeting matches ANY of the paired combinations
                        for i in range(max_pairs):
                            day_val = day_list[i] if i < len(day_list) else day_list[-1]
                            time_val = time_list[i] if i < len(time_list) else time_list[-1]
                            
                            day_match = day_val in days if day_val else True
                            time_match = time_matches(time_str, time_val) if time_val else True
                            
                            if day_match and time_match:
                                has_matching_meeting = True
                                break
                        
                        if has_matching_meeting:
                            break
                
                else:
                    # AND logic (default): Check if section has meetings matching all criteria
                    for meeting in section.get("meetings", []):
                        days = meeting.get("days", "")
                        time_str = meeting.get("time", "")
                        
                        # For AND with lists: check if meeting matches ANY day in list AND ANY time in list
                        day_match = True
                        if day_list:
                            day_match = any(d in days for d in day_list)
                        
                        time_match = True
                        if time_list:
                            time_match = any(time_matches(time_str, t) for t in time_list)
                        
                        if day_match and time_match:
                            has_matching_meeting = True
                            break
                
                # Skip section if no meetings match the filters
                if not has_matching_meeting:
                    continue
            
            filtered_sections.append(section)
        if filtered_sections:
            result = {
                "course_code": course["course_code"],
                "course_title": course["course_title"],
                "sections": filtered_sections
            }
            # Include prerequisites if available
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
        '     \"mode\": \"in-person\" | \"online\" | \"hybrid\" | [list] | null,\n'
        '     \"status\": \"open\" | \"closed\" | null,\n'
        '     \"day\": \"M\" | \"T\" | \"W\" | \"Th\" | \"F\" | [list of days] | null,\n'
        '     \"time\": \"morning\" | \"afternoon\" | \"evening\" | [list of times] | null,\n'
        '     \"instructor\": string or null\n'
        "  },\n"
        '  \"filter_logic\": \"AND\" | \"OR\"\n'
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
        "- Extract simple filters if present; else use nulls.\n\n"
        "IMPORTANT - Handling 'OR' and 'AND' logic:\n"
        "- If user uses 'OR' (e.g., 'Monday mornings OR Thursday afternoons'), set filter_logic='OR' "
        "  and provide lists for filters that have multiple options.\n"
        "  Example: 'Wednesday mornings or Thursday afternoons' → "
        '  {\"day\": [\"W\", \"Th\"], \"time\": [\"morning\", \"afternoon\"], \"filter_logic\": \"OR\"}\n'
        "- If user uses 'AND' or commas without 'or', set filter_logic='AND' and combine criteria.\n"
        "  Example: 'Monday and Wednesday mornings' → "
        '  {\"day\": [\"M\", \"W\"], \"time\": \"morning\", \"filter_logic\": \"AND\"}\n'
        "- Default filter_logic is 'AND' if not specified.\n"
        "- When filter_logic='OR', a section matches if it satisfies ANY of the combined day/time pairs.\n"
        "- When filter_logic='AND', a section must satisfy ALL specified criteria."
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
    parsed.setdefault("filter_logic", "AND")  # Default to AND logic
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
    filter_logic = parsed.get("filter_logic", "AND")  # Get OR/AND logic from parsed data
    results = search_courses(keyword, mode, status, day_filter, time_filter, instructor_mentioned, filter_logic=filter_logic)

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
    """Serve the main page"""
    return render_template('index.html')

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
    
    # Get port from environment variable (Render provides this)
    port = int(os.environ.get('PORT', 5000))
    
    # Determine if running locally or in production
    is_production = os.environ.get('RENDER') is not None
    
    if is_production:
        # Production settings for Render
        print(f"🌐 Starting production server on 0.0.0.0:{port}")
        print("="*80 + "\n")
        app.run(debug=False, host='0.0.0.0', port=port)
    else:
        # Local development settings
        print(f"🌐 Starting development server at http://127.0.0.1:{port}")
        print("="*80 + "\n")
        app.run(debug=True, host='127.0.0.1', port=port)

