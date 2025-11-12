import os
import json
from pathlib import Path
from flask import Flask, render_template, request, jsonify, session
from openai import OpenAI
from dotenv import load_dotenv
from datetime import datetime
import secrets
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError
import certifi

# NEW: stdlib imports used by the transfer assistant
import re   # NEW
import glob # NEW
import csv  # NEW

# Load environment variables
load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Initialize Flask app
app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", secrets.token_hex(32))  # For session management

# Initialize MongoDB connection
mongodb_uri = os.getenv("MONGODB_CONNECTION_URI")
mongo_client = None
db = None
conversations_collection = None

if mongodb_uri:
    try:
        # Use certifi for SSL certificate verification
        mongo_client = MongoClient(
            mongodb_uri, 
            serverSelectionTimeoutMS=10000,
            tlsCAFile=certifi.where()
        )
        # Test connection
        mongo_client.admin.command('ping')
        db = mongo_client['dvc_course_assistant']
        conversations_collection = db['conversations']
        print("✅ Connected to MongoDB successfully")
    except (ConnectionFailure, ServerSelectionTimeoutError) as e:
        print(f"⚠️ MongoDB connection failed: {e}")
        print("📝 Falling back to JSON file logging")
        mongo_client = None
    except Exception as e:
        print(f"⚠️ Unexpected MongoDB error: {e}")
        print("📝 Falling back to JSON file logging")
        mongo_client = None
else:
    print("⚠️ MONGODB_CONNECTION_URI not found in environment variables")
    print("📝 Using JSON file logging")

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
    Log user interactions to MongoDB (or JSON file as fallback).
    
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
    
    # Try MongoDB first
    if conversations_collection is not None:
        try:
            conversations_collection.insert_one(log_entry)
            print(f"✅ Logged interaction to MongoDB")
            return
        except Exception as e:
            print(f"⚠️ MongoDB logging failed: {e}")
            print("📝 Falling back to JSON file")
    
    # Fallback to JSON file logging
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
    
    logs.append(log_entry)
    
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
       
       COMPOUND CONDITIONS: Supports day+time combos like "Monday morning or Thursday afternoon"
       - These create specific (day, time) pairs that are checked independently
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

    # Detect compound conditions (day+time combos separated by "or")
    # Example: "Monday morning or Thursday afternoon"
    compound_conditions = []
    if day_filter and time_filter and " or " in f"{day_filter} {time_filter}".lower():
        # Try to parse compound conditions
        combined = f"{day_filter} {time_filter}".lower()
        if "morning" in combined or "afternoon" in combined or "evening" in combined:
            # Split by "or" to get individual conditions
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
                
                # Extract day
                for day_name, day_code in name_to_code.items():
                    if day_name in part:
                        day_found = day_code
                        break
                
                # Extract time
                if "morning" in part:
                    time_found = "morning"
                elif "afternoon" in part:
                    time_found = "afternoon"
                elif "evening" in part:
                    time_found = "evening"
                
                if day_found and time_found:
                    compound_conditions.append((day_found, time_found))
    
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

            # INSTRUCTOR: OR semantics with flexible name matching
            if instr_norm:
                instructor = section.get("instructor", "").lower()
                # For each instructor query, split into tokens and check if all tokens match
                matched = False
                for name_query in instr_norm:
                    # Split the query into tokens (handles "Joanne Strickland" → ["joanne", "strickland"])
                    query_tokens = [token.strip().lower() for token in name_query.replace(',', ' ').split() if token.strip()]
                    # Check if all query tokens appear anywhere in the instructor field
                    if all(token in instructor for token in query_tokens):
                        matched = True
                        break
                if not matched:
                    continue

            # DAY/TIME: per-meeting checks with AND/OR semantics and compound conditions
            if compound_conditions:
                # Handle compound conditions like "Monday morning or Thursday afternoon"
                has_matching_meeting = False
                for meeting in section.get("meetings", []):
                    days = meeting.get("days", "") or ""
                    time_str = meeting.get("time", "")
                    
                    # Check if this meeting matches any of the compound conditions
                    for required_day, required_time in compound_conditions:
                        # Check day
                        def _has_day(code):
                            if code == "Th":
                                return "Th" in days
                            return code in days
                        
                        day_match = _has_day(required_day)
                        
                        # Check time
                        time_match = False
                        if time_str and time_str.lower() != "asynchronous":
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
                                time_match = (bucket == required_time)
                            except:
                                pass
                        
                        # If this meeting matches this compound condition, include the section
                        if day_match and time_match:
                            has_matching_meeting = True
                            break
                    
                    if has_matching_meeting:
                        break
                
                if not has_matching_meeting:
                    continue
                    
            elif day_terms or time_terms:
                # Standard independent day/time filtering (no compound conditions)
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
        "ALLOWED_TITLES": allowed_titles_payload,  # LLM uses this to map titles → codes
        "NOTES": "Days may be written as Monday/Mon/Tues/Thursday/etc.; map to M,T,W,Th,F."
    })

    try:
        resp = client.chat.completions.create(
            model="gpt-4.1",
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

    # Ensure course_codes and subjects are lists (handle None case)
    if not isinstance(parsed["course_codes"], list):
        parsed["course_codes"] = [] if parsed["course_codes"] is None else [parsed["course_codes"]]
    if not isinstance(parsed["subjects"], list):
        parsed["subjects"] = [] if parsed["subjects"] is None else [parsed["subjects"]]
    
    parsed["course_codes"] = [str(c).upper() for c in parsed["course_codes"] if isinstance(c, str)]
    parsed["subjects"] = [str(s).upper() for s in parsed["subjects"] if isinstance(s, str)]
    if not isinstance(parsed["filters"], dict):
        parsed["filters"] = {"mode": None, "status": None, "day": None, "time": None, "instructor": None}

    # ---- Final allow-list enforcement ----
    parsed["course_codes"] = [c for c in parsed["course_codes"] if c in all_course_codes]
    parsed["subjects"] = [s for s in parsed["subjects"] if s in all_subject_prefixes]

    return parsed


# === UC Transfer Assistant (merged) ===
# Straight copy/condense of your ai_agent.py logic, adapted into callables for this Flask app.
# Uses the existing `client` and adds a small early hook in `ask_course_assistant`.

# Campus config (3 only)
CAMPUS_ALIASES = {
    "UCB": ["uc berkeley", "berkeley", "ucb", "cal"],
    "UCD": ["uc davis", "davis", "ucd"],
    "UCSD": ["uc san diego", "san diego", "ucsd"],
}
PRETTY_CAMPUS = {
    "UCB": "UC Berkeley",
    "UCD": "UC Davis",
    "UCSD": "UC San Diego",
}

# common typo fixes
TYPO_FIXES = {
    r"\busb\b": "uc berkeley",
    r"\bucb\b": "uc berkeley",
    r"\bberkley\b": "berkeley",
    r"\bucsd\b": "uc san diego",
    r"\buc sd\b": "uc san diego",
}

def _normalize_typos(q: str) -> str:
    t = q.lower()
    for pat, repl in TYPO_FIXES.items():
        t = re.sub(pat, repl, t)
    return t

def _has_transfer_intent(q: str) -> bool:
    t = _normalize_typos(q)
    triggers = [
        "transfer", "assist", "articulation", "major prep", "major preparation",
        "equivalen", "requirements", "uc berkeley", "uc davis", "uc san diego",
        "ucb", "ucd", "ucsd", "berkeley", "davis", "san diego"
    ]
    return any(x in t for x in triggers)

def _detect_campus_from_query(q: str):
    t = _normalize_typos(q)
    for key, aliases in CAMPUS_ALIASES.items():
        if any(a in t for a in aliases):
            return key
    return None

def _detect_campuses_from_query(q: str):
    t = _normalize_typos(q)
    found = []
    for key, aliases in CAMPUS_ALIASES.items():
        if any(a in t for a in aliases):
            found.append(key)
    return sorted(set(found))

# category detection
CATEGORY_ALIASES = {
    "major preparation": ["major preparation", "lower division major", "ld major"],
    "lower division major": ["lower division major", "ld major"],
    "general education": ["general education", "ge", "breadth"],
    "breadth": ["breadth", "ge area", "area"],
    "math": ["math", "mathematics"],
    "science": ["science", "natural science", "biology", "chemistry", "physics"],
    "computer science": ["computer science", "cs", "programming", "software"],
}

def _normalize_categories_freeform(text: str):
    low = _normalize_typos(text)
    picked = set()

    for m in re.finditer(r'category\s*:\s*["“](.+?)["”]', low):
        phrase = m.group(1).strip()
        if phrase:
            picked.add(phrase)

    for m in re.finditer(r'\bonly\s+([a-z0-9 \-/&]+)', low):
        phrase = re.split(r"[.,;:!?()\[\]{}]", m.group(1).strip())[0].strip()
        if phrase:
            picked.add(phrase)

    for m in re.finditer(r'\bshow\s+([a-z0-9 \-/&]+?)\s+only\b', low):
        phrase = m.group(1).strip()
        if phrase:
            picked.add(phrase)

    for canon, variants in CATEGORY_ALIASES.items():
        if canon in low:
            picked.add(canon); continue
        for v in variants:
            if v in low:
                picked.add(canon); break

    out = set()
    canon_keys = set(CATEGORY_ALIASES.keys())
    for p in picked:
        matched_key = None
        for ck in canon_keys:
            if ck in p:
                matched_key = ck; break
        out.add(matched_key or p)
    return sorted(out)

# load/collect/filter data
def _load_all_data(paths):
    data = {}
    for pattern in paths:
        for path in glob.glob(pattern):
            base = os.path.basename(path)
            campus_key = base.split("_")[0].upper()
            if campus_key not in PRETTY_CAMPUS:
                continue
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data[campus_key] = json.load(f)
            except Exception as e:
                print(f"Error reading {path}: {e}")
    return data

def _collect_course_rows(campus_json):
    out = []

    def _rec(o):
        if isinstance(o, dict):
            if "Category" in o and "Courses" in o:
                cat = o.get("Category", "")
                mr = o.get("Minimum_Required", "")
                courses = o.get("Courses", [])
                if isinstance(courses, list):
                    for pair in courses:
                        dvc_block = pair.get("DVC")
                        items = dvc_block if isinstance(dvc_block, list) else [dvc_block]
                        for d in items:
                            if isinstance(d, dict):
                                out.append({
                                    "category": cat,
                                    "minimum_required": mr,
                                    "dvc_code": d.get("Course_Code", "") or d.get("Code", ""),
                                    "dvc_title": d.get("Title", ""),
                                    "dvc_units": d.get("Units", "") or d.get("units", ""),
                                })
            for v in o.values(): _rec(v)
        elif isinstance(o, list):
            for i in o: _rec(i)

    _rec(campus_json)

    seen, dedup = set(), []
    for r in out:
        code = (r.get("dvc_code") or "").strip()
        if code and code not in seen:
            dedup.append(r); seen.add(code)
    return dedup

def _is_cs_row(r):
    code = (r.get("dvc_code") or "").upper()
    title = (r.get("dvc_title") or "").lower()
    cat = (r.get("category") or "").lower()
    return (
        code.startswith(("COMSC-", "COMSCI-", "COMPSC-", "CS-"))
        or "programming" in title
        or "data structures" in title
        or "software" in title
        or "major preparation" in cat
        or "lower division major" in cat
        or "computer science" in cat
    )

def _is_math_row(r):
    code = (r.get("dvc_code") or "").upper()
    cat = (r.get("category") or "").lower()
    title = (r.get("dvc_title") or "").lower()
    return (
        code.startswith(("MATH-", "STAT-"))
        or "mathematics" in cat or "math" in cat
        or "calculus" in title or "linear algebra" in title or "differential equations" in title
    )

def _is_science_row(r):
    code = (r.get("dvc_code") or "").upper()
    cat = (r.get("category") or "").lower()
    return (
        code.startswith(("PHYS-", "CHEM-", "BIOSC-", "BIOL-"))
        or "physics" in cat or "chemistry" in cat or "biology" in cat or "science" in cat
    )

def _row_matches_any_category(row, categories):
    if not categories:
        return True
    cat_text = (row.get("category") or "").lower()
    if not cat_text:
        return False
    for requested in categories:
        rlow = requested.lower()
        if rlow in CATEGORY_ALIASES:
            if any(alias in cat_text for alias in CATEGORY_ALIASES[rlow] + [rlow]):
                return True
        if rlow in cat_text:
            return True
    return False

def _filter_rows(rows, completed_courses, completed_domains, focus_only, required_only, categories_only):
    filtered = []
    completed_upper = {c.upper() for c in completed_courses}
    for r in rows:
        code = (r.get("dvc_code") or "").upper()
        if code in completed_upper: continue
        if "science" in completed_domains and _is_science_row(r): continue
        if "math" in completed_domains and _is_math_row(r): continue
        if "cs" in completed_domains and _is_cs_row(r): continue
        if focus_only == "cs" and not _is_cs_row(r): continue
        if focus_only == "math" and not _is_math_row(r): continue
        if focus_only == "science" and not _is_science_row(r): continue
        if required_only:
            mr = str(r.get("minimum_required", "")).lower()
            if not (mr == "all" or (mr.isdigit() and int(mr) > 0)): continue
        if not _row_matches_any_category(r, categories_only or []): continue
        filtered.append(r)
    return filtered

def _llm_chat_text(messages, model, temperature=0.0, response_format=None):
    params = dict(model=model, temperature=temperature, messages=messages)
    if response_format is not None:
        params["response_format"] = response_format
    resp = client.chat.completions.create(**params)
    return resp.choices[0].message.content.strip()

def _llm_parse_user_message(user_message):
    system = (
        "You are an assistant that parses TRANSFER-ONLY student questions for UC transfer planning from Diablo Valley College (DVC). "
        "Output STRICT JSON (no markdown). Keys: intent, parameters, filters.\n"
        "Allowed intents: find_requirements, find_equivalent_course.\n"
        "parameters.campus: UCB/UCD/UCSD or null.\n"
        "parameters.campuses: array of campuses (UCB, UCD, UCSD).\n"
        "filters.focus_only: 'cs'|'math'|'science'|'all'|null; filters.required_only: boolean; "
        "filters.domains_completed: ['cs'|'math'|'science']; filters.completed_courses: ['COMSC-110', ...]; "
        "filters.categories: e.g., 'major preparation','breadth'. If unsure, return null/empty."
    )
    text = _llm_chat_text(
        model="gpt-4.1",
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_message},
        ],
    )
    try:
        data = json.loads(text)
    except Exception:
        data = {}
    data.setdefault("intent", "find_requirements")
    data.setdefault("parameters", {})
    data.setdefault("filters", {})
    params, filt = data["parameters"], data["filters"]

    campuses_raw = params.get("campuses", [])
    if not isinstance(campuses_raw, list):
        campuses_raw = []
    single_campus = params.get("campus")
    if isinstance(single_campus, str) and single_campus.strip():
        campuses_raw.append(single_campus)
    campuses_raw.extend(_detect_campuses_from_query(user_message))

    campuses_norm = []
    for c in campuses_raw:
        if not isinstance(c, str): continue
        det = _detect_campus_from_query(c) or c.upper().strip()
        if det in PRETTY_CAMPUS:
            campuses_norm.append(det)
    campuses_norm = sorted(set(campuses_norm))
    params["campus"] = campuses_norm[0] if campuses_norm else None
    params["campuses"] = campuses_norm

    focus = filt.get("focus_only")
    if isinstance(focus, str):
        focus = focus.lower().strip()
        if focus not in {"cs","math","science","all"}:
            focus = None
    else:
        focus = None
    filt["focus_only"] = focus
    filt["required_only"] = bool(filt.get("required_only", False))

    domains = filt.get("domains_completed") or []
    if isinstance(domains, list):
        domains = {d for d in (x.lower().strip() for x in domains) if d in {"cs","math","science"}}
    else:
        domains = set()
    filt["domains_completed"] = sorted(domains)

    comp = filt.get("completed_courses") or []
    comp = comp if isinstance(comp, list) else []
    norm = set()
    for raw in comp:
        if isinstance(raw, str):
            s = raw.upper().strip().replace(" ", "-")
            m = re.match(r"^([A-Z&]+)[- ]?(\d+[A-Z]?)$", s)
            if m: s = f"{m.group(1)}-{m.group(2)}"
            norm.add(s)
    for code in re.findall(r"\b([A-Za-z]{2,}[- ]?\d+[A-Za-z]?)\b", user_message, flags=re.IGNORECASE):
        s = code.upper().strip().replace(" ", "-")
        m = re.match(r"^([A-Z&]+)[- ]?(\d+[A-Z]?)$", s)
        if m: s = f"{m.group(1)}-{m.group(2)}"
        norm.add(s)
    filt["completed_courses"] = sorted(norm)

    cats = filt.get("categories") or []
    cats = cats if isinstance(cats, list) else []
    cats_local = _normalize_categories_freeform(user_message)
    filt["categories"] = sorted(set([c for c in cats if isinstance(c, str) and c.strip()] + cats_local))

    return data

def _llm_format_multi(campus_keys, campus_to_rows, parsed, completed_courses, completed_domains):
    chunks = []
    for ck in campus_keys:
        campus_name = PRETTY_CAMPUS.get(ck, ck)
        items = [{
            "course": (r.get("dvc_code") or "").strip(),
            "title": (r.get("dvc_title") or "").strip(),
            "units": r.get("dvc_units", "")
        } for r in campus_to_rows.get(ck, [])]

        payload = {
            "campus": campus_name,
            "intent": parsed.get("intent"),
            "parameters": parsed.get("parameters", {}),
            "filters": parsed.get("filters", {}),
            "excluding": {
                "completed_domains": sorted(list(completed_domains)),
                "completed_courses": sorted(list(completed_courses)),
            },
            "courses": items
        }
        text = _llm_chat_text(
            model="gpt-4.1",
            temperature=0.2,
            messages=[
                {"role": "system", "content":
                 "Format UC transfer mappings only (no availability/schedule).\n"
                 "Output:\n"
                 "• One summary line: 'Transfer prep for <Campus>:'\n"
                 "• Optional parenthetical note '(excluding completed domains: ...; completed courses: ... )'\n"
                 "• Bullets: '• COMSC-200 — Object Oriented Programming C++ (4 units)'\n"
                 "If empty, say: 'No DVC course mappings found.'"},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}
            ],
        )
        chunks.append(text.strip() if text else f"Transfer prep for {campus_name}:\nNo DVC course mappings found.")
    return "\n\n".join(chunks)

# lazy caches
_TRANSFER_DATA = None
_TRANSFER_ALL_ROWS = None

def _ensure_transfer_data_loaded():
    global _TRANSFER_DATA, _TRANSFER_ALL_ROWS
    if _TRANSFER_DATA is not None:
        return _TRANSFER_DATA
    base_patterns = [
        os.path.join("data", "uc*.json"),
        os.path.join("agreements_25-26", "*.json"),
    ]
    _TRANSFER_DATA = _load_all_data(base_patterns)
    _TRANSFER_ALL_ROWS = {ck: _collect_course_rows(_TRANSFER_DATA[ck]) for ck in _TRANSFER_DATA}
    if not _TRANSFER_DATA:
        print("⚠️ UC transfer: no campus files loaded. Check data/ and agreements_25-26/")
    return _TRANSFER_DATA

def maybe_handle_transfer(user_query: str) -> str | None:
    """
    If the query looks like a UC transfer request, return a formatted response string
    and log it using the same base logger. Otherwise return None.
    """
    mode = (os.getenv("TRANSFER_MODE") or "auto").lower()
    if mode == "off":
        return None
    is_transfer = _has_transfer_intent(user_query) or (mode == "always")
    if not is_transfer:
        return None

    data = _ensure_transfer_data_loaded()
    if not data:
        resp = "I couldn't load UC transfer mappings. Please add JSON files under `data/` or `agreements_25-26/`."
        # base-style log
        log_interaction(user_query, {"mode": "uc_transfer", "error": "no_data"}, resp)
        return resp

    parsed = _llm_parse_user_message(user_query)
    campus_keys = parsed.get("parameters", {}).get("campuses") or _detect_campuses_from_query(user_query)
    if not campus_keys:
        resp = "Which campus? I can help with **UC Berkeley (UCB)**, **UC Davis (UCD)**, or **UC San Diego (UCSD)**."
        log_interaction(user_query, {"mode": "uc_transfer", "parsed": parsed, "campuses": []}, resp)
        return resp

    completed_courses = set(parsed["filters"].get("completed_courses") or [])
    completed_domains = set(parsed["filters"].get("domains_completed") or [])
    focus_only = parsed["filters"].get("focus_only")
    required_only = bool(parsed["filters"].get("required_only"))
    categories_only = parsed["filters"].get("categories") or _normalize_categories_freeform(user_query)

    campus_to_remaining = {}
    for ck in campus_keys:
        if ck not in data:
            continue
        all_rows = _TRANSFER_ALL_ROWS.get(ck) if _TRANSFER_ALL_ROWS is not None else _collect_course_rows(data[ck])
        campus_to_remaining[ck] = _filter_rows(
            all_rows,
            completed_courses,
            completed_domains,
            focus_only,
            required_only,
            categories_only
        )

    resp_text = _llm_format_multi(
        campus_keys,
        campus_to_remaining,
        parsed,
        completed_courses,
        completed_domains
    )

    # base-style log (single JSON file)
    log_interaction(
        user_query,
        {
            "mode": "uc_transfer",
            "parsed": parsed,
            "campuses": campus_keys,
            "result_counts": {ck: len(campus_to_remaining.get(ck, [])) for ck in campus_keys}
        },
        resp_text
    )
    return resp_text
# === End UC Transfer Assistant (merged) ===


def ask_course_assistant(user_query: str, *, conversation_history: list = None, parser_temperature: float = 0.0, response_temperature: float = 0.1, enable_logging: bool = True):
    """LLM parses → we search → LLM formats. Includes conversation history for follow-up questions.
    
    Args:
        user_query: The current user question
        conversation_history: List of previous messages [{"role": "user"/"assistant", "content": "..."}]
        parser_temperature: Temperature for parsing query
        response_temperature: Temperature for formatting response
        enable_logging: Whether to log the interaction
    """
    if conversation_history is None:
        conversation_history = []
    
    # NEW: Early hook for UC transfer requests
    transfer_try = maybe_handle_transfer(user_query)
    if transfer_try:
        return transfer_try  # already logged inside maybe_handle_transfer


    query_lower = user_query.lower()
    
    # Check if this is a follow-up question by looking at conversation history
    is_followup = len(conversation_history) > 0
    
    # Enhanced parser prompt with conversation context
    if is_followup:
        # Build context from recent conversation
        context_summary = "\n".join([
            f"{'User' if msg['role'] == 'user' else 'Assistant'}: {msg['content'][:200]}..."
            for msg in conversation_history[-4:]  # Last 2 exchanges
        ])
        enhanced_query = f"Previous conversation context:\n{context_summary}\n\nCurrent question: {user_query}"
    else:
        enhanced_query = user_query
    
    parsed = llm_parse_query(enhanced_query, temperature=parser_temperature)

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
            "I can help you find DVC STEM courses and details and transfer from DVC agreements.\n\n"
            "Try one of these:\n"
            '- "Show me open MATH-193 sections Monday morning."\n'
            '- "Who teaches PHYS-130 on Thursdays?"\n'
            '- "What are the prerequisites for COMSC-200?"\n'
            '- "I have completed Math 192, what does that cover at UCB?"\n'
            '- "What GE courses should I take at DVC for UC Berkeley?"'
        )
        if enable_logging:
            log_interaction(user_query, parsed, response)
        return response

    # Fast path for prerequisite intent
    if intent == "prerequisites":
        keywords_for_prereq = course_codes or subjects
        results = search_courses(keywords_for_prereq)
        
        # Check if this is a "can I take together" question
        can_take_together_patterns = ["can i take", "take together", "take at the same time", "together with", "take both"]
        is_take_together_question = any(pattern in query_lower for pattern in can_take_together_patterns)
        
        if is_take_together_question and len(course_codes) >= 2:
            # User asking about taking multiple courses together
            # Find prerequisite info for each course
            course_prereqs = {}
            for code in course_codes:
                for r in results:
                    if r["course_code"].upper() == code.upper():
                        course_prereqs[code] = r.get("prerequisites", "")
                        break
            
            # Build response explaining relationships
            response = f"**Can you take {' and '.join(course_codes)} together?**\n\n"
            
            # Check if any course is a prerequisite for another
            conflict_found = False
            for i, code1 in enumerate(course_codes):
                for code2 in course_codes[i+1:]:
                    prereq1 = course_prereqs.get(code1, "").upper()
                    prereq2 = course_prereqs.get(code2, "").upper()
                    
                    if code1.upper() in prereq2:
                        response += f"❌ **No** - {code2} requires {code1} as a prerequisite, so you must complete {code1} first.\n\n"
                        response += f"**{code2} prerequisites:** {course_prereqs.get(code2, 'Not listed')}\n"
                        conflict_found = True
                        break
                    elif code2.upper() in prereq1:
                        response += f"❌ **No** - {code1} requires {code2} as a prerequisite, so you must complete {code2} first.\n\n"
                        response += f"**{code1} prerequisites:** {course_prereqs.get(code1, 'Not listed')}\n"
                        conflict_found = True
                        break
                if conflict_found:
                    break
            
            if not conflict_found:
                response += f"✅ **Yes** - Based on prerequisites, these courses can be taken together as neither requires the other.\n\n"
                for code in course_codes:
                    prereq = course_prereqs.get(code, "No prerequisites listed")
                    response += f"**{code}:** {prereq}\n"
                response += "\n💡 Just make sure there are no schedule conflicts between the sections you choose!"
            
            if enable_logging:
                log_interaction(user_query, parsed, response)
            return response
        
        # Regular prerequisite lookup
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
    
    # Serialize results to JSON and check if truncation needed
    results_json = json.dumps(results, indent=2)
    
    if len(results_json) > truncate_limit:
        # If we need to truncate, reduce number of sections per course to fit
        truncated_results = []
        char_count = 0
        
        for course in results:
            # Keep course metadata
            course_copy = {
                "course_code": course["course_code"],
                "course_title": course["course_title"],
                "sections": []
            }
            
            # Add sections until we hit the limit
            for section in course.get("sections", []):
                section_json = json.dumps(section, indent=2)
                if char_count + len(section_json) < truncate_limit - 500:  # Leave room for metadata
                    course_copy["sections"].append(section)
                    char_count += len(section_json)
                else:
                    break
            
            if course_copy["sections"]:  # Only add courses that have sections
                truncated_results.append(course_copy)
                
        results_to_send = truncated_results
        results_json = json.dumps(truncated_results, indent=2)
        truncated = True
    else:
        results_to_send = results
        truncated = False
    
    # Count sections from what we're actually sending
    sections_to_send = sum(len(course.get("sections", [])) for course in results_to_send)
    total_sections_original = sum(len(course.get("sections", [])) for course in results)
    
    context += f"I found {len(results)} matching course(s) with {total_sections_original} total section(s) for '{keyword_display}'.\n"
    
    if truncated:
        context += f"NOTE: Showing {sections_to_send} sections below (truncated for brevity). When you write your summary, say 'Found {sections_to_send} section(s)' to match what you're displaying.\n"
    else:
        context += f"IMPORTANT: When you write the summary, say 'Found {sections_to_send} section(s)' - this matches the exact count in the JSON below.\n"
    
    if filter_bits: 
        context += "Filters applied: " + ", ".join(filter_bits) + "\n"
        context += "The JSON data below has been PRE-FILTERED to match these exact criteria. Show ONLY the sections in this data.\n"
        if instructor_mentioned:
            context += f"NOTE: User specifically asked about instructor '{instructor_mentioned}' - show ONLY sections taught by this instructor.\n"
    
    context += "\nHere is the JSON data (already filtered):\n" + results_json

    # Build messages with conversation history for context-aware responses
    system_message = {
        "role": "system",
        "content": """You are a DVC course assistant. Your job is to turn PRE-FILTERED JSON into a clear, student-friendly answer.
        You maintain conversation context and can answer follow-up questions.

        CORE PRINCIPLES
        1) Use ONLY the JSON in the assistant message. Do not invent or infer missing data.
        2) The JSON is already PRE-FILTERED to match the user's request. Respect those filters exactly.
        3) If the assistant context lists filters (e.g., Instructor: Lo), show ONLY sections that match them.
        4) Never include sections that fail the filters.
        5) Present results clearly, concisely, and consistently for fast scanning.
        6) CONVERSATION CONTEXT: Remember previous questions and answers. If the user asks a follow-up (e.g., "What about evening?", "Who teaches that?"), reference the previous course/subject they asked about.

        FOLLOW-UP HANDLING
        - If user says "that course", "those classes", "the same one", etc., refer to the most recent course discussed.
        - If user asks "what about [filter]?", apply the new filter to the previous search.
        - If unclear, ask for clarification while being helpful.
        
        PREREQUISITE CHAIN ANALYSIS
        - If user asks "Can I take X and Y together?" or "Can I take X with Y?" check prerequisites:
          * Look at X's prerequisites - does it require Y? If yes, must take Y first.
          * Look at Y's prerequisites - does it require X? If yes, must take X first.
          * If one requires the other → NO, they cannot be taken together.
          * If neither requires the other → YES, they can be taken together (check for time conflicts too).
        - Provide clear recommendation: "No, COMSC-200 requires COMSC-165 as prerequisite, so take 165 first" or "Yes, these can be taken together as neither is a prerequisite for the other."

        OUTPUT STRUCTURE
        A) One-line Summary:
        - Use the EXACT count from the assistant context message (it says "I found X matching course(s)"). Do NOT recount the JSON yourself.
        - Briefly restate the user's goal and show this count (e.g., "Found 3 sections for MATH-193 (Mon, morning).").
        - If no results, return a short, helpful message and stop (also include 1–3 next-step suggestions).
        - For follow-ups, acknowledge the context (e.g., "For those COMSC-110 sections you asked about earlier...").

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

        STYLE & TONE
        - Use bullet lists; avoid long paragraphs.
        - Be consistent in label order and punctuation.
        - Keep it positive and helpful, but terse.
        - Be conversational and remember what the user asked before.

        NEVER DO
        - Do not reprint the raw JSON.
        - Do not add categories beyond the three specified.
        - Do not include sections that are not in the provided JSON.
        - Do not forget the conversation context.
        """
    }
    
    # Build message history
    messages = [system_message]
    
    # Add conversation history (limit to last 10 messages to avoid token limits)
    if conversation_history:
        messages.extend(conversation_history[-10:])
    
    # Add current user query
    messages.append({"role": "user", "content": user_query})
    
    # Add the search results context
    messages.append({"role": "assistant", "content": context})
    
    # LLM formatter with conversation context
    llm_response = client.chat.completions.create(
        model="gpt-4.1",
        temperature=response_temperature,
        messages=messages,
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
    API endpoint to handle user queries with conversation memory
    
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
        
        # Initialize conversation history in session if not exists
        if 'conversation_history' not in session:
            session['conversation_history'] = []
        
        # Get conversation history from session
        conversation_history = session['conversation_history']
        
        # Call the chatbot assistant with conversation history
        response = ask_course_assistant(
            user_query, 
            conversation_history=conversation_history,
            enable_logging=True
        )
        
        # Update conversation history
        conversation_history.append({"role": "user", "content": user_query})
        conversation_history.append({"role": "assistant", "content": response})
        
        # Keep only last 20 messages (10 exchanges) to prevent session from growing too large
        if len(conversation_history) > 20:
            conversation_history = conversation_history[-20:]
        
        # Save back to session
        session['conversation_history'] = conversation_history
        session.modified = True
        
        return jsonify({
            'success': True,
            'response': response,
            'message_count': len(conversation_history)  # For debugging
        })
        
    except Exception as e:
        print(f"❌ Error in /ask route: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': 'An error occurred processing your request'
        }), 500

@app.route('/clear', methods=['POST'])
def clear_conversation():
    """
    Clear the conversation history and start fresh
    
    Returns JSON: {"success": true}
    """
    try:
        session['conversation_history'] = []
        session.modified = True
        
        return jsonify({
            'success': True,
            'message': 'Conversation history cleared'
        })
        
    except Exception as e:
        print(f"❌ Error in /clear route: {str(e)}")
        return jsonify({
            'success': False,
            'error': 'Failed to clear conversation'
        }), 500

@app.route('/conversation/status', methods=['GET'])
def conversation_status():
    """
    Get the current conversation status
    
    Returns JSON: {"message_count": int, "has_history": bool}
    """
    try:
        history = session.get('conversation_history', [])
        
        return jsonify({
            'success': True,
            'message_count': len(history),
            'has_history': len(history) > 0,
            'exchange_count': len(history) // 2  # Number of Q&A pairs
        })
        
    except Exception as e:
        print(f"❌ Error in /conversation/status route: {str(e)}")
        return jsonify({
            'success': False,
            'error': 'Failed to get conversation status'
        }), 500

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    mongo_status = "not_connected"
    mongo_error = None
    
    if conversations_collection is not None:
        mongo_status = "connected"
        try:
            # Try to ping MongoDB
            mongo_client.admin.command('ping')
            mongo_status = "connected_and_working"
        except Exception as e:
            mongo_status = "connected_but_error"
            mongo_error = str(e)
    
    return jsonify({
        'status': 'healthy',
        'courses_loaded': len(course_data),
        'mongodb_status': mongo_status,
        'mongodb_error': mongo_error,
        'mongodb_uri_set': bool(os.getenv("MONGODB_CONNECTION_URI"))
    })

@app.route('/logs', methods=['GET'])
def view_logs():
    """
    View conversation logs from MongoDB
    
    Query parameters:
        - limit: Number of logs to retrieve (default: 50, max: 500)
        - skip: Number of logs to skip for pagination (default: 0)
    
    Returns JSON: {"success": bool, "count": int, "logs": [...]}
    """
    try:
        # Get query parameters
        limit = request.args.get('limit', 50, type=int)
        skip = request.args.get('skip', 0, type=int)
        
        # Enforce limits
        limit = min(limit, 500)
        skip = max(skip, 0)
        
        if conversations_collection is not None:
            # Fetch from MongoDB (newest first)
            logs = list(conversations_collection.find(
                {},
                {'_id': 0}  # Exclude MongoDB's internal _id field
            ).sort('timestamp', -1).skip(skip).limit(limit))
            
            total_count = conversations_collection.count_documents({})
            
            return jsonify({
                'success': True,
                'count': len(logs),
                'total': total_count,
                'source': 'mongodb',
                'logs': logs
            })
        else:
            # Fallback to JSON file
            if log_file_path.exists():
                with open(log_file_path, "r", encoding="utf-8") as f:
                    all_logs = json.load(f)
                
                # Return newest first
                all_logs.reverse()
                logs = all_logs[skip:skip+limit]
                
                return jsonify({
                    'success': True,
                    'count': len(logs),
                    'total': len(all_logs),
                    'source': 'json_file',
                    'logs': logs
                })
            else:
                return jsonify({
                    'success': True,
                    'count': 0,
                    'total': 0,
                    'source': 'none',
                    'logs': []
                })
    
    except Exception as e:
        print(f"❌ Error in /logs route: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

if __name__ == '__main__':
    # Get port from environment variable (Render provides this) or default to 5001
    # Note: Using 5001 locally to avoid conflict with macOS AirPlay Receiver on port 5000
    port = int(os.environ.get("PORT", 5001))
    # Bind to 0.0.0.0 to allow external access (required for Render)
    host = '0.0.0.0'
    # Disable debug mode in production
    debug = os.environ.get("FLASK_ENV") != "production"
    
    print("\n" + "="*80)
    print("🎓 DVC Course Assistant - Flask Web App")
    print("="*80)
    print(f"✅ Loaded {len(course_data)} courses")
    print(f"🌐 Starting server at http://{host}:{port}")
    print(f"🔧 Debug mode: {debug}")
    print("="*80 + "\n")
    app.run(debug=debug, host=host, port=port)
