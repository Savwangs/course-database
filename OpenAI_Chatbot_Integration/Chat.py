import os, json, re
from pathlib import Path
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

db_path = Path.cwd().parent / "dvc_scraper" / "Full_STEM_DataBase.json"

if not db_path.exists():
    raise FileNotFoundError(f"❌ Could not find database at: {db_path}")

with open(db_path, "r", encoding="utf-8") as f:
    course_data = json.load(f)

print(f"✅ Loaded {len(course_data)} courses from {db_path}")

def search_courses(keyword, mode=None, status=None, day_filter=None, time_filter=None, instructor_filter=None):
    """Return courses filtered by code/title, and optionally by format/status/day/time/instructor.
    
    Args:
        keyword: str or list of str - Course code(s) to search for
        mode: str or list of str - Format filter (in-person, online, hybrid)
        status: str - Status filter (open, closed)
        day_filter: str - Day code filter (M, T, W, Th, F)
        time_filter: str - Time of day filter (morning, afternoon, evening)
        instructor_filter: str - Instructor name filter
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
                has_matching_meeting = False
                for meeting in section.get("meetings", []):
                    days = meeting.get("days", "")
                    time_str = meeting.get("time", "")
                    
                    # Check day filter
                    day_match = True
                    if day_filter:
                        # Check if the day code is in the days string
                        day_match = day_filter in days
                    
                    # Check time filter
                    time_match = True
                    if time_filter and time_str and time_str.lower() != "asynchronous":
                        # Parse time to check if it's in the range
                        try:
                            # Extract start time (e.g., "8:30AM - 11:00AM" -> "8:30AM")
                            start_time = time_str.split("-")[0].strip()
                            # Convert to 24-hour format for comparison
                            if "PM" in start_time and not start_time.startswith("12"):
                                hour = int(start_time.split(":")[0])
                                hour += 12
                            elif "AM" in start_time and start_time.startswith("12"):
                                hour = 0
                            else:
                                hour = int(start_time.split(":")[0])
                            
                            # Check time ranges
                            if time_filter == "morning":
                                time_match = hour < 12
                            elif time_filter == "afternoon":
                                time_match = 12 <= hour < 17
                            elif time_filter == "evening":
                                time_match = hour >= 17
                        except:
                            # If parsing fails, include the section
                            time_match = False
                    
                    # If both day and time match for this meeting, include the section
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
    """LLM-first parser → course_codes, subjects, intent, filters (constrained to DB)."""
    all_course_codes = sorted({c["course_code"].upper() for c in course_data})
    all_subject_prefixes = sorted({c["course_code"].split("-")[0].upper() for c in course_data})

    parser_system = (
        "You are an intent and entity parser for a community college course finder. "
        "Normalize and correct typos in the user's text (e.g., 'avalibale'→'available', "
        "'phycs'→'PHYS', 'prof julli'→'Julie') before extracting entities. "
        "Return STRICT JSON ONLY (no prose/markdown) with keys:\n"
        "{\n"
        '  "course_codes": [list of exact course codes like "COMSC-110"],\n'
        '  "subjects": [list of subject prefixes like "COMSC","MATH"],\n'
        '  "intent": "find_sections" | "prerequisites" | "instructors",\n'
        '  "filters": {\n'
        '     "mode": "in-person" | "online" | "hybrid" | null,\n'
        '     "status": "open" | "closed" | null,\n'
        '     "day": "M" | "T" | "W" | "Th" | "F" | null,\n'
        '     "time": "morning" | "afternoon" | "evening" | null,\n'
        '     "instructor": string or null\n'
        "  }\n"
        "}\n"
        "Rules:\n"
        "- Only choose course_codes from ALLOWED_COURSE_CODES.\n"
        "- Only choose subjects from ALLOWED_SUBJECT_PREFIXES.\n"
        "- If the user asks about prerequisites/prereq, set intent='prerequisites'.\n"
        "- If the user asks about professor/instructor/teacher/who teaches, set intent='instructors'.\n"
        "- Otherwise default to intent='find_sections'.\n"
        "- Extract simple filters if present; else use nulls."
    )

    parser_user = json.dumps({
        "USER_QUERY": user_query,
        "ALLOWED_COURSE_CODES": all_course_codes,
        "ALLOWED_SUBJECT_PREFIXES": all_subject_prefixes,
        "NOTES": "Days may be written as Monday/Mon/Tues/Thursday/etc.; map to M,T,W,Th,F."
    })

    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            temperature=temperature,  # 0.0 = deterministic parsing
            messages=[
                {"role": "system", "content": parser_system},
                {"role": "user", "content": parser_user},
            ],
        )
        parsed = json.loads(resp.choices[0].message.content.strip())
    except Exception:
        parsed = {}

    # Normalize + guard
    parsed = parsed if isinstance(parsed, dict) else {}
    parsed.setdefault("course_codes", [])
    parsed.setdefault("subjects", [])
    parsed.setdefault("intent", "find_sections")
    parsed.setdefault("filters", {"mode": None, "status": None, "day": None, "time": None, "instructor": None})

    parsed["course_codes"] = [str(c).upper() for c in parsed["course_codes"] if isinstance(c, str)]
    parsed["subjects"] = [str(s).upper() for s in parsed["subjects"] if isinstance(s, str)]
    if not isinstance(parsed["filters"], dict):
        parsed["filters"] = {"mode": None, "status": None, "day": None, "time": None, "instructor": None}

    # Enforce allow-lists so the parser can’t return codes/subjects not in your DB
    parsed["course_codes"] = [c for c in parsed["course_codes"] if c in all_course_codes]
    parsed["subjects"] = [s for s in parsed["subjects"] if s in all_subject_prefixes]
    return parsed


def ask_course_assistant(user_query: str, *, parser_temperature: float = 0.0, response_temperature: float = 0.2):
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

    # Optional: map “available/avaliable/avail” → open (parity with user phrasing)
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
        return (
            "I can help you find **DVC STEM courses** and details like sections, instructors, and prerequisites.\n\n"
            "**Try one of these:**\n"
            "- “Show me **open** MATH-193 sections **Monday morning**.”\n"
            "- “Who teaches **PHYS-130** on **Thursdays**?”\n"
            "- “What are the **prerequisites** for **COMSC-200**?”\n"
            "- “Show **online** **COMSC** classes.”\n\n"
            "Please include a **subject** (e.g., COMSC, MATH, PHYS, CHEM, BIOSC, ENGIN) or a specific **course code** (e.g., COMSC-110)."
        )

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
            return f"**{chosen['course_code']}: {chosen['course_title']}**\n\nPrerequisites: {prereqs}"
        return (
            f"I couldn’t find any courses for **{', '.join(keywords_for_prereq) if isinstance(keywords_for_prereq, list) else keywords_for_prereq}**.\n"
            "Double-check the course code/subject, or try another course (e.g., COMSC-110, MATH-193)."
        )

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
            return (
                f"I couldn’t find any courses for **{', '.join(keyword) if isinstance(keyword, list) else keyword}**.\n"
                "Please check the **subject/prefix** or **course code**, or try a broader query.\n\n"
                "**Examples:**\n"
                "- “Show **COMSC** classes.”\n"
                "- “Find **MATH-193** sections.”\n"
                "- “Any **online PHYS** this **evening**?”"
            )
        else:
            # The course/subject exists, but filters were too strict
            return (
                f"I found **no sections** with your current filters (**{applied_str}**) for "
                f"**{', '.join(keyword) if isinstance(keyword, list) else keyword}**.\n\n"
                "Try relaxing one or more filters. For example:\n"
                "- Remove the **instructor** name to see all sections\n"
                "- Try a different **day** or **time** window\n"
                "- Include **hybrid** or **online** if you only searched in-person\n\n"
                "Want me to show **all available sections** for this course/subject?"
            )

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

    context = f"I found {len(results)} matching course(s) for '{keyword_display}'.\n"
    if filter_bits: context += "Filters applied: " + ", ".join(filter_bits) + "\n"
    context += "\nHere is the JSON data (already filtered):\n" + json.dumps(results, indent=2)[:truncate_limit]

    # LLM formatter (explicit temperature)
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        temperature=response_temperature,
        messages=[
            {
                "role": "system",
                "content": """You are a DVC course assistant. Format course data clearly for students.

                CRITICAL RULES:
                1. Only use data from the assistant message - never invent information
                2. The data has already been filtered - show ALL sections provided
                3. When showing search results, organize into THREE SEPARATE GROUPS per course:
                
                ### HYBRID SECTIONS (includes in-person meetings):
                [List ALL sections where format is "hybrid"]
                
                ### IN-PERSON SECTIONS (fully in-person):
                [List ALL sections where format is "in-person"]
                
                ### ONLINE SECTIONS:
                [List ALL sections where format is "online"]

                4. For each section, display:
                - Section number, Instructor, Days, Time, Location, Units
                - Keep notes brief (only essential prereqs/requirements)

                5. If no sections in a category: "No [category] sections found."

                6. When showing results for MULTIPLE courses:
                - List EVERY course found
                - Group by course code
                - Show each course separately with its sections
                """
            },
            {"role": "user", "content": user_query},
            {"role": "assistant", "content": context},
        ],
    )
    return response.choices[0].message.content.strip()

test_queries = [
    "Show me all avaliable comsc-200 in person sections",
    "What math-292 section is taught by Professor Julie",
    "I want a fun stem class", 
    "Show me open MATH193 sections on monday mornings",
    "What are the prerequisites for physc 230"
]

for q in test_queries:
    print(f"🧩 Query: {q}")
    print(ask_course_assistant(q))
    print("\n" + "-"*80 + "\n")