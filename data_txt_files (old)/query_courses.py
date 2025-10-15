import json
import os

def load_data(filepath="../dvc_scraper/dvc_json/Full_STEM_DataBase.json"):
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
    """
    results = []
    for course in data:
        if course_code and course_code.lower() not in course["course_code"].lower():
            continue

        prereqs = course.get("prerequisites", "None listed")

        for section in course.get("sections", []):
            if status and section.get("status", "").lower() != status.lower():
                continue

            for meeting in section.get("meetings", []):
                if format and format.lower() != meeting.get("format", "").lower():
                    continue

                if days:
                    normalized_days = meeting.get("days", "").replace(" ", "").lower()
                    if days.lower() not in normalized_days:
                        continue

                results.append({
                    "course_code": course["course_code"],
                    "title": course["course_title"],
                    "section": section["section_number"],
                    "instructor": section["instructor"],
                    "days": meeting["days"],
                    "time": meeting["time"],
                    "room": meeting["room"],
                    "format": meeting["format"],
                    "status": section["status"],
                    "prerequisites": prereqs
                })

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
        print(f"  Days/Time: {r['days']} - {r['time']}")
        print(f"  Room: {r['room']} | Format: {r['format']}")
        print(f"  Status: {r['status']}")
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
    print("2️⃣  Are there any online ENGL-122 sections still open?")
    print("="*80)
    res = query_courses(data, course_code="ENGL-122", format="online", status="Open")
    print_results(res)

    print("\n" + "="*80)
    print("3️⃣  I need a CHEM-120 class that doesn’t overlap with MATH-192.")
    print("="*80)
    print("⏳ Note: Overlap-checking logic not implemented yet (requires parsing meeting times).")
    print("Showing all CHEM-120 and MATH-192 sections for manual review:\n")
    chem = query_courses(data, course_code="CHEM-120")
    math = query_courses(data, course_code="MATH-192")
    print("CHEM-120 Sections:")
    print_results(chem)
    print("\nMATH-192 Sections:")
    print_results(math)

    print("\n" + "="*80)
    print("4️⃣  List all open BIOSC courses suitable for CS transfer students.")
    print("="*80)
    res = query_courses(data, course_code="BIOSC", status="Open")
    print_results(res)

    print("\n" + "="*80)
    print("5️⃣  Show all MATH-292 (Calculus III) sections on TTH afternoons.")
    print("="*80)
    res = query_courses(data, course_code="MATH-292", days="TTh")
    print_results(res)

    print("\n" + "="*80)
    print("6️⃣  Find equivalent courses for ENGL-C1000 that also satisfy CS transfer requirements.")
    print("="*80)
    print("ℹ️  Note: This requires Assist.org mapping — placeholder for now.")
    print("Equivalent course data may be added later into the JSON (e.g., ENGL-122).")

    print("\n" + "="*80)
    print("7️⃣  Which STAT-244 sections are still open for Spring 2026?")
    print("="*80)
    res = query_courses(data, course_code="STAT-244", status="Open")
    print_results(res)