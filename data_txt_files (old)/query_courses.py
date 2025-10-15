import json

def load_data(filepath="courses_data.json"):
    """Load JSON course data."""
    with open(filepath, "r") as f:
        return json.load(f)

def query_courses(data, course_code=None, format=None, days=None):
    """
    Query courses based on filters:
    - course_code: e.g., 'COMSC-110'
    - format: e.g., 'in-person', 'online', 'hybrid'
    - days: e.g., 'TTh', 'MW', 'F'
    """
    results = []
    for course in data:
        if course_code and course_code.lower() not in course["course_code"].lower():
            continue

        # Capture prerequisites once per course
        prereqs = course.get("prerequisites", "None listed")

        for section in course["sections"]:
            for meeting in section["meetings"]:
                if format and format.lower() != meeting["format"].lower():
                    continue
                if days and days.lower() not in meeting["days"].replace(" ", "").lower():
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
    """Print query results neatly."""
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


if __name__ == "__main__":
    data = load_data()

    # Test 1
    print("In-person COMSC-110 sections:\n")
    res = query_courses(data, course_code="COMSC-110", format="in-person")
    print_results(res)

    # Test 2
    print("\nLinear Algebra (MATH-194) on TTh:\n")
    res = query_courses(data, course_code="MATH-194", days="TTh")
    print_results(res)
