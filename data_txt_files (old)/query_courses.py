import json
import os
from datetime import datetime

def load_data(filepath="../dvc_scraper/Full_STEM_DataBase.json"):
    """
    Load the full STEM course database from a single JSON file.
    """
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"File not found: {filepath}")
    with open(filepath, "r") as f:
        data = json.load(f)
    print(f"✅ Loaded course database from {filepath}")
    print(f"📘 Total courses loaded: {len(data)}")
    return data


def query_courses(data, course_code=None, format=None, days=None, status=None):
    """
    Query courses based on filters:
    - course_code: e.g., 'COMSC-110'
    - format: e.g., 'in-person', 'online', 'hybrid'
    - days: e.g., 'TTh', 'MW', 'Online', 'M W'
    - status: e.g., 'Open', 'Waitlist', 'Full'
    
    Returns one result per section (not per meeting).
    """
    results = []
    seen_sections = set()  # Track sections we've already added
    
    for course in data:
        if course_code and course_code.lower() != course["course_code"].lower():
            continue

        prereqs = course.get("prerequisites", "None listed")

        for section in course.get("sections", []):
            if status and section.get("status", "").lower() != status.lower():
                continue

            # Check if any meeting matches the filters
            matching_meetings = []
            for meeting in section.get("meetings", []):
                if format and format.lower() != meeting.get("format", "").lower():
                    continue

                if days:
                    normalized_days = meeting.get("days", "").replace(" ", "").lower()
                    if days.lower() not in normalized_days:
                        continue

                matching_meetings.append(meeting)

            # If we found matching meetings and haven't added this section yet
            section_id = f"{course['course_code']}-{section['section_number']}"
            if matching_meetings and section_id not in seen_sections:
                # Combine all meeting info for this section
                all_meetings_str = " | ".join([
                    f"{m['days']} {m['time']} ({m['format']})" 
                    for m in section.get("meetings", [])
                ])
                
                results.append({
                    "course_code": course["course_code"],
                    "title": course["course_title"],
                    "section": section["section_number"],
                    "instructor": section["instructor"],
                    "meetings": section.get("meetings", []),  # Store all meetings
                    "meetings_summary": all_meetings_str,
                    "status": section["status"],
                    "prerequisites": prereqs
                })
                seen_sections.add(section_id)

    return results


def print_results(results):
    """Pretty-print results."""
    if not results:
        print("No matching courses found.")
        return

    for r in results:
        print(f"\n{r['course_code']} - {r['title']}")
        print(f"  Section: {r['section']}")
        print(f"  Instructor: {r['instructor']}")
        print(f"  Status: {r['status']}")
        
        # Print all meetings for this section
        meetings = r.get('meetings', [])
        if len(meetings) > 1:
            print(f"  Meetings:")
            for m in meetings:
                days = m.get('days', 'N/A')
                time = m.get('time', 'N/A')
                room = m.get('room', 'N/A')
                fmt = m.get('format', 'N/A')
                if days or time != 'N/A':  # Only show if there's actual meeting info
                    print(f"    • {days} {time} | {room} ({fmt})")
        else:
            # Single meeting - show inline
            m = meetings[0] if meetings else {}
            print(f"  Days/Time: {m.get('days', 'N/A')} - {m.get('time', 'N/A')}")
            print(f"  Room: {m.get('room', 'N/A')} | Format: {m.get('format', 'N/A')}")
        
        print(f"  Prerequisites: {r['prerequisites']}")
        print("-" * 70)


def find_alternate_format(data, course_code, primary_format, fallback_format="hybrid"):
    """If no results for primary_format, suggest fallback format."""
    results = query_courses(data, course_code=course_code, format=primary_format)
    if results:
        return results, None
    fallback = query_courses(data, course_code=course_code, format=fallback_format)
    if fallback:
        return fallback, f"No {primary_format} sections found. Showing {fallback_format} options instead."
    return [], f"No {primary_format} or {fallback_format} sections available."

def parse_time_range(time_str):
    """Convert a time range like '9:35AM - 11:00AM' to (start_min, end_min)."""
    if " - " not in time_str:
        return None
    start_str, end_str = time_str.split(" - ")
    try:
        start = datetime.strptime(start_str.strip(), "%I:%M%p")
        end = datetime.strptime(end_str.strip(), "%I:%M%p")
        return (start.hour * 60 + start.minute, end.hour * 60 + end.minute)
    except ValueError:
        return None

def normalize_days(days_str):
    """Normalize day formats like 'T Th', 'TuTh', 'MW' → ['M', 'T', 'W', 'Th', 'F']"""
    days_str = days_str.replace(" ", "").lower()
    normalized = []
    i = 0
    while i < len(days_str):
        if days_str[i:i+2] == "th":
            normalized.append("Th")
            i += 2
        elif days_str[i] in "mtwf":
            normalized.append(days_str[i].upper())
            i += 1
        else:
            i += 1
    return normalized


def meetings_overlap(meetings1, meetings2):
    """
    Check if any meeting from meetings1 overlaps with any meeting from meetings2.
    meetings1 and meetings2 should be lists of meeting dictionaries.
    """
    for m1 in meetings1:
        for m2 in meetings2:
            if "online" in m1.get("format", "").lower() or "online" in m2.get("format", "").lower():
                continue

            days1 = normalize_days(m1.get("days", ""))
            days2 = normalize_days(m2.get("days", ""))
            time1 = parse_time_range(m1.get("time", ""))
            time2 = parse_time_range(m2.get("time", ""))
            
            if not time1 or not time2:
                continue

            # Overlap in time?
            start1, end1 = time1
            start2, end2 = time2
            time_conflict = not (end1 <= start2 or end2 <= start1)

            # Overlap in any shared day?
            day_conflict = any(d in days2 for d in days1)

            if time_conflict and day_conflict:
                return True
    
    return False


if __name__ == "__main__":
    # Load database
    data = load_data()

    print("\n" + "="*80)
    print("1️⃣  I want to take an in-person COMSC-110 in Spring 2026 — what options are available?")
    print("="*80)
    res, note = find_alternate_format(data, "COMSC-110", "in-person")
    if note: print(note)
    print_results(res)

    print("\n" + "="*80)
    print("2️⃣  Are there any online ENGL-C1000 sections still open?")
    print("="*80)
    res = query_courses(data, course_code="ENGL-C1000", format="online", status="Open")
    print_results(res)

    print("\n" + "="*80)
    print("3️⃣  I need a CHEM-120 class that doesn't overlap with MATH-192.")
    print("="*80)

    # --- Load sections ---
    chem_sections = query_courses(data, course_code="CHEM-120")
    math_sections = query_courses(data, course_code="MATH-192")

    # --- Filter out overlapping CHEM sections ---
    non_conflicting = []

    for chem in chem_sections:
        conflict_found = False
        for math in math_sections:
            if meetings_overlap(chem['meetings'], math['meetings']):
                conflict_found = True
                break
        if not conflict_found:
            non_conflicting.append(chem)

    # --- Display Results ---
    if non_conflicting:
        print("\n✅ CHEM-120 sections that do NOT overlap with any MATH-192 section:\n")
        print_results(non_conflicting)
    else:
        print("\n❌ All CHEM-120 sections overlap with MATH-192.")
        
    print("\n" + "="*80)
    print("4️⃣  Show all MATH-292 (Calculus III) sections on TTH afternoons.")
    print("="*80)
    res = query_courses(data, course_code="MATH-292", days="TTh")
    print_results(res)

    print("\n" + "="*80)
    print("5️⃣  Find equivalent courses for ENGL-C1000 that also satisfy CS transfer requirements.")
    print("="*80)

    # Find the dictionary in the list that contains the key
    equivalents = []
    for item in data:
        if isinstance(item, dict) and "equivalent_courses_for_ENGL-C1000" in item:
            equivalents = item["equivalent_courses_for_ENGL-C1000"]
            break

    print("\n6. Equivalent courses for ENGL-C1000:\n")
    if equivalents:
        for eq in equivalents:
            course_code = eq.get("course_code", "Unknown")
            title = eq.get("course_title", "")
            print(f"• {course_code} - {title}")
    else:
        print("No equivalent courses found.")

    print("\n" + "="*80)
    print("6️⃣  Which STAT-C1000 sections are still open for Spring 2026?")
    print("="*80)
    res = query_courses(data, course_code="STAT-C1000", status="Open")
    print_results(res)

    print("\n" + "="*80)
    print("7️⃣  List all open BIOSC courses suitable for CS transfer students.")
    print("="*80)


    biosc_130 = query_courses(data, course_code="BIOSC-130", status="Open")
    biosc_131 = query_courses(data, course_code="BIOSC-131", status="Open")


    res = biosc_130 + biosc_131

    if res:
        print(f"\nFound {len(biosc_130)} BIOSC-130 sections and {len(biosc_131)} BIOSC-131 sections:\n")
        print_results(res)
    else:
        print("No open BIOSC-130 or BIOSC-131 sections found.")