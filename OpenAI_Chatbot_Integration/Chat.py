import os, json
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

def search_courses(keyword, mode=None, status=None):
    """Return courses filtered by code/title, and optionally by format/status.
    
    Args:
        keyword: str or list of str - Course code(s) to search for
        mode: str or list of str - Format filter (in-person, online, hybrid)
        status: str - Status filter (open, closed)
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
            
            if mode_match and (not status or status in stat):
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
def ask_course_assistant(user_query: str):
    """Send user query to GPT for a summary."""
    query_lower = user_query.lower()
    
    # Subject keyword mapping to course code prefixes
    subject_map = {
        "engineering": "ENGIN",
        "engineer": "ENGIN",
        "physics": "PHYS",
        "physical": "PHYS",
        "physc": "PHYS",  # Handle typo
        "biology": "BIOSC",
        "bio": "BIOSC",
        "biological": "BIOSC",
        "chemistry": "CHEM",
        "chem": "CHEM",
        "computer science": "COMSC",
        "compsci": "COMSC",
        "comsc": "COMSC",
        "cs": "COMSC",
        "math": "MATH",
        "mathematics": "MATH",
    }
    
    # Extract course code (specific like COMSC-110)
    keyword = ""
    for word in user_query.split():
        # Handle formats: COMSC-110, comsc-200, math 292, physc 230
        word_clean = word.strip(",.?!").upper()
        if "-" in word_clean and any(ch.isdigit() for ch in word_clean):
            # Handle cases like "comsc-110" or "physc-230"
            # Split and map the prefix
            parts = word_clean.split("-")
            prefix_lower = parts[0].lower()
            # Check if prefix needs mapping
            if prefix_lower in subject_map:
                keyword = f"{subject_map[prefix_lower]}-{parts[1]}"
            else:
                keyword = word_clean
            break
        # Handle space-separated like "math 292" or "physc 230"
        elif any(ch.isdigit() for ch in word_clean) and len(word_clean) <= 4:
            # Check if previous word was a subject
            words = user_query.split()
            for i, w in enumerate(words):
                w_clean = w.strip(",.?!").upper()
                if w_clean == word_clean and i > 0:
                    prev = words[i-1].strip(",.?!").lower()
                    # Check if prev is in subject map or matches a subject
                    mapped_prefix = None
                    if prev in subject_map:
                        mapped_prefix = subject_map[prev]
                    else:
                        # Check if it starts with any subject keyword
                        for subj_keyword in subject_map.keys():
                            if prev.startswith(subj_keyword):
                                mapped_prefix = subject_map[subj_keyword]
                                break
                    
                    if mapped_prefix:
                        keyword = f"{mapped_prefix}-{word_clean}"
                        break
            if keyword:
                break
    
    # If no specific course code, check for subject keywords (can match multiple)
    keywords = []
    if not keyword:
        for subject_keyword, course_prefix in subject_map.items():
            if subject_keyword in query_lower:
                if course_prefix not in keywords:
                    keywords.append(course_prefix)
        
        # If multiple subjects found, use all of them; if one found, use it
        if keywords:
            keyword = keywords if len(keywords) > 1 else keywords[0]
    
    # If still no keyword found, ask for more specificity
    if not keyword:
        return "To help you find a course, could you please be more specific about what subject you're interested in? (e.g., COMSC-110, engineering, physics, biology)"

    # ✅ Check if this is a prerequisite query
    if "prerequisite" in query_lower or "prereq" in query_lower:
        # Get course data without filtering by sections
        results = search_courses(keyword, mode=None, status=None)
        if results:
            course = results[0]
            prereqs = course.get("prerequisites", "No prerequisites listed")
            return f"**{course['course_code']}: {course['course_title']}**\n\nPrerequisites: {prereqs}"
        else:
            return f"No course found for {keyword}."
    
    # ✅ Detect filters from natural language
    mode = None
    status = None
    day_filter = None
    time_filter = None
    
    # Detect day mentions
    days_map = {
        "monday": "M", "mon": "M",
        "tuesday": "T", "tue": "T", "tues": "T",
        "wednesday": "W", "wed": "W",
        "thursday": "Th", "thu": "Th", "thur": "Th", "thurs": "Th",
        "friday": "F", "fri": "F"
    }
    for day_name, day_code in days_map.items():
        if day_name in query_lower:
            day_filter = day_code
            break
    
    # Detect time of day
    if "morning" in query_lower:
        time_filter = "morning"
    elif "afternoon" in query_lower:
        time_filter = "afternoon"
    elif "evening" in query_lower:
        time_filter = "evening"
    
    # Modality detection - FIXED: only set mode if explicitly mentioned
    # If days/times mentioned, don't auto-filter to in-person (show all formats)
    if "in-person" in query_lower or "in person" in query_lower:
        mode = ["in-person", "hybrid"]
    elif "online" in query_lower:
        mode = "online"
    elif "hybrid" in query_lower:
        mode = "hybrid"
    # If day/time mentioned but no explicit modality, don't filter mode
    # This allows showing online sections too
    
    if "open" in query_lower:
        status = "open"

    # Call updated search with filters
    results = search_courses(keyword, mode, status)
    
    # Format keyword display
    if isinstance(keyword, list):
        keyword_display = " and ".join(keyword)
    else:
        keyword_display = keyword
    
    # Determine truncation limit based on whether it's a subject search or specific course
    # For subject searches (e.g., all PHYS courses), allow more data
    is_subject_search = isinstance(keyword, list) or (isinstance(keyword, str) and "-" not in keyword)
    truncate_limit = 8000 if is_subject_search else 4000
    
    # Build context with additional filters info
    filter_info = []
    if day_filter:
        filter_info.append(f"Day filter: Only show sections on {day_filter}")
    if time_filter:
        time_ranges = {
            "morning": "before 12:00 PM",
            "afternoon": "between 12:00 PM and 5:00 PM",
            "evening": "after 5:00 PM"
        }
        filter_info.append(f"Time filter: Only show sections {time_ranges[time_filter]}")
    
    # Check if instructor name is mentioned
    instructor_mentioned = None
    common_titles = ["professor", "prof", "dr", "instructor"]
    for word in user_query.split():
        if word.lower() in common_titles:
            # Get the next word(s) as instructor name
            words = user_query.split()
            idx = words.index(word)
            if idx + 1 < len(words):
                instructor_mentioned = words[idx + 1].strip(",.?!")
                filter_info.append(f"Instructor filter: Only show sections taught by instructor with name containing '{instructor_mentioned}'")
                break
    
    context = (
        f"I found {len(results)} matching course(s) for '{keyword_display}'.\n"
    )
    if filter_info:
        context += f"\nIMPORTANT FILTERS TO APPLY:\n" + "\n".join(f"- {f}" for f in filter_info) + "\n"
    context += f"\nHere is the JSON data:\n{json.dumps(results, indent=2)[:truncate_limit]}"

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "system",
                "content": """You are a DVC course assistant. Format course data clearly for students.

CRITICAL RULES:
1. Only use data from the assistant message - never invent information
2. If "IMPORTANT FILTERS TO APPLY" is provided, you MUST apply those filters strictly:
   - Instructor filter: Only show sections where instructor name contains the specified name
   - Day filter: Only show sections where "days" field contains the specified day code
   - Time filter: Parse the "time" field and only show sections in the specified time range
3. Show ALL courses and ALL sections that match the filters - do not summarize or skip any
4. When showing in-person search results, organize into TWO SEPARATE GROUPS per course:
   
   ### HYBRID SECTIONS (includes in-person meetings):
   [List ALL matching sections classified as hybrid]
   
   ### IN-PERSON SECTIONS (fully in-person):
   [List ALL matching sections classified as in-person, NOT hybrid]
   
   ### ONLINE SECTIONS:
   [List ALL matching sections classified as online]

5. For each section, display:
   - Section number, Instructor, Days, Time, Location, Units
   - Keep notes brief (only essential prereqs/requirements)

6. If no matches after applying filters: "No sections found matching your criteria."

7. When showing results for MULTIPLE courses (e.g., all physics courses):
   - List EVERY course found
   - Group by course code
   - Show each course separately with matching sections

Example with Filters:

FILTERS APPLIED: Only Monday sections, Morning time (before 12 PM)

**MATH-193: Calculus III**

### HYBRID SECTIONS:
- Section 1234
  - Instructor: Smith, John
  - Days: M W
  - Time: 10:00AM - 11:30AM
  - Location: MATH 101
  - Units: 5.00

### IN-PERSON SECTIONS:
No in-person sections found on Monday mornings.

### ONLINE SECTIONS:
No online sections found (online courses don't have specific meeting times).
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
    "Show me open MATH-193 sections on monday mornings",
    "What are the prerequisites for physc 230"
]

for q in test_queries:
    print(f"🧩 Query: {q}")
    print(ask_course_assistant(q))
    print("\n" + "-"*80 + "\n")

