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
        # Handle formats: COMSC-110, comsc-200, math 292, physc 230, MATH193
        word_clean = word.strip(",.?!").upper()
        word_lower = word.strip(",.?!").lower()
        
        # Case 1: Has dash like "comsc-110" or "physc-230"
        if "-" in word_clean and any(ch.isdigit() for ch in word_clean):
            parts = word_clean.split("-")
            prefix_lower = parts[0].lower()
            # Check if prefix needs mapping
            if prefix_lower in subject_map:
                keyword = f"{subject_map[prefix_lower]}-{parts[1]}"
            else:
                keyword = word_clean
            break
        
        # Case 2: No separator like "MATH193" or "comsc110"
        # Match pattern: letters followed by numbers (e.g., MATH193, biosc101)
        elif any(ch.isalpha() for ch in word_clean) and any(ch.isdigit() for ch in word_clean) and "-" not in word_clean:
            # Split into letter part and number part
            match = re.match(r'^([a-zA-Z]+)(\d+)$', word_clean)
            if match:
                prefix = match.group(1).lower()
                number = match.group(2)
                # Check if prefix needs mapping
                if prefix in subject_map:
                    keyword = f"{subject_map[prefix]}-{number}"
                else:
                    keyword = f"{prefix.upper()}-{number}"
                break
        
        # Case 3: Space-separated like "math 292" or "physc 230"
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
        results = search_courses(keyword, mode=None, status=None, day_filter=None, time_filter=None, instructor_filter=None)
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
                break

    # Call updated search with filters
    results = search_courses(keyword, mode, status, day_filter, time_filter, instructor_mentioned)
    
    # Format keyword display
    if isinstance(keyword, list):
        keyword_display = " and ".join(keyword)
    else:
        keyword_display = keyword
    
    # Determine truncation limit based on whether it's a subject search or specific course
    # For subject searches (e.g., all PHYS courses), allow more data
    is_subject_search = isinstance(keyword, list) or (isinstance(keyword, str) and "-" not in keyword)
    truncate_limit = 8000 if is_subject_search else 4000
    
    # Build context - filters already applied in search_courses
    filter_descriptions = []
    if day_filter:
        filter_descriptions.append(f"Day: {day_filter}")
    if time_filter:
        filter_descriptions.append(f"Time: {time_filter}")
    if instructor_mentioned:
        filter_descriptions.append(f"Instructor: {instructor_mentioned}")
    
    context = (
        f"I found {len(results)} matching course(s) for '{keyword_display}'.\n"
    )
    if filter_descriptions:
        context += f"Filters applied: {', '.join(filter_descriptions)}\n"
    context += f"\nHere is the JSON data (already filtered):\n{json.dumps(results, indent=2)[:truncate_limit]}"

    response = client.chat.completions.create(
        model="gpt-4o-mini",
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

Example Output:

**MATH-193: Calculus III**

### HYBRID SECTIONS:
No hybrid sections found.

### IN-PERSON SECTIONS:
- Section 6134
  - Instructor: Willett, Peter
  - Days: M W
  - Time: 8:30AM - 11:00AM
  - Location: 209
  - Units: 5.00

### ONLINE SECTIONS:
No online sections found.
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