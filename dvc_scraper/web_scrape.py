# dvc_playwright_singlepage.py
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError
from bs4 import BeautifulSoup
import re
from datetime import datetime
import os

URL = "https://webapps.4cd.edu/apps/courseschedulesearch/search-course.aspx?search=dvc"

# --- EDIT THESE ---
TERM_VALUE   = "2026FA"
COURSES = [
    "BUS-240",
    "CHEM-107",
    "CHEM-108",
    "CHEM-109",
    "CHEM-120",
    "CHEM-121",
    "COMSC-010NC",
    "COMSC-020NC",
    "COMSC-101",
    "COMSC-110",
    "COMSC-140",
    "COMSC-156",
    "COMSC-165",
    "COMSC-200",
    "COMSC-210",
    "COMSC-255",
    "COMSC-260",
    "ENGIN-110",
    "ENGIN-120",
    "ENGIN-130",
    "ENGIN-131",
    "ENGIN-135",
    "ENGIN-136",
    "ENGIN-230",
    "ENGIN-240",
    "ENGL-175",
    "ENGL-C1000",
    "ENGL-C1000E",
    "MATH-002",
    "MATH-082",
    "MATH-121",
    "MATH-121L",
    "MATH-124",
    "MATH-135",
    "MATH-135L",
    "MATH-140",
    "MATH-182",
    "MATH-183",
    "MATH-191",
    "MATH-191L",
    "MATH-192",
    "MATH-193",
    "MATH-194",
    "MATH-195",
    "MATH-292",
    "MATH-294",
    "PHYS-110",
    "PHYS-112",
    "PHYS-120",
    "PHYS-121",
    "PHYS-124",
    "PHYS-125",
    "PHYS-129",
    "PHYS-130",
    "PHYS-230",
    "PHYS-231",
    "STAT-C1000",
    "STAT-C1000E"
]
#COURSES = ["WRKX-170"]  # for demo purposes

COURSE_VALUE = ""
OUTPUT_FILE  = f"dvc_{TERM_VALUE}_{COURSE_VALUE}.txt"
OUTPUT_DIR = "dvc_txt_FA2026"
# ------------------

DELIM = ";"
TERM_SEL    = 'select[id$="SEC_TERM"]'
COURSE_SEL  = 'select[id$="X_COURSE"]'
SEARCH_BTN  = 'input[id$="btnSearch"]'
RESULTS_TAB = 'table[id$="gvResults"]'

def sanitize_cell_text(text: str) -> str:
    # Prevent website semicolons from breaking our delimiter-based TXT format
    return text.replace(";", " - ").strip()

def collapse_repeated_meeting_block(cells):
    # Expected shape:
    # [term, location, section, course, date_range, ...variable meeting block..., units, instructor, comments..., status, seats]
    if len(cells) < 15:
        return cells

    units_idx = None
    for i in range(len(cells) - 1, -1, -1):
        if re.fullmatch(r"\d+\.\d{2}(?:/\d+\.\d{2})?", cells[i]):
            units_idx = i
            break

    if units_idx is None or units_idx <= 5:
        return cells

    prefix = cells[:5]
    middle = cells[5:units_idx]
    suffix = cells[units_idx:]

    if len(middle) % 2 == 0:
        half = len(middle) // 2
        if middle[:half] == middle[half:]:
            middle = middle[:half]

    return prefix + middle + suffix

UNITS_PATTERN = re.compile(r"^\d+\.\d{2}(?:/\d+\.\d{2})?$")
STATUS_PATTERN = re.compile(r"^(Open|Clsd|Closed|Waitlist|Waitlisted|Cancelled|Full)\b", re.I)

def split_comment_buckets(tokens):
    prereq_parts = []
    advisory_parts = []
    note_parts = []
    current = None

    for token in tokens:
        t = token.strip()
        if not t:
            continue

        low = t.lower()
        if low.startswith("prerequisite:"):
            current = "prereq"
            prereq_parts.append(t)
        elif low.startswith("advisory:"):
            current = "advisory"
            advisory_parts.append(t)
        elif low.startswith("note:"):
            current = "note"
            note_parts.append(t)
        else:
            if current == "prereq":
                prereq_parts.append(t)
            elif current == "advisory":
                advisory_parts.append(t)
            else:
                note_parts.append(t)

    return (
        sanitize_cell_text(" ".join(prereq_parts).strip()),
        sanitize_cell_text(" ".join(advisory_parts).strip()),
        sanitize_cell_text(" ".join(note_parts).strip()),
    )

def normalize_main_row(cells):
    """
    Normalize a main data row into:
    term;location;section;course;date_range;[schedule...];units;instructor;prereq;advisory;comments;status;seats
    """
    if len(cells) < 8:
        return cells

    units_idx = None
    for i in range(len(cells) - 1, -1, -1):
        if UNITS_PATTERN.fullmatch(cells[i]):
            units_idx = i
            break

    if units_idx is None or units_idx <= 4:
        return cells

    # determine status / seats from end
    if len(cells) >= 2 and STATUS_PATTERN.match(cells[-2]):
        status = cells[-2]
        seats = cells[-1]
        status_idx = len(cells) - 2
    elif STATUS_PATTERN.match(cells[-1]):
        status = cells[-1]
        seats = ""
        status_idx = len(cells) - 1
    else:
        return cells

    # expected:
    # prefix: term, location, section, course, date_range
    # middle: schedule tokens
    # units
    # instructor
    # comment tokens
    prefix = cells[:5]
    schedule_tokens = cells[5:units_idx]
    units = cells[units_idx]

    if units_idx + 1 >= status_idx:
        return cells

    instructor = cells[units_idx + 1]
    comment_tokens = cells[units_idx + 2:status_idx]

    prereq, advisory, comments = split_comment_buckets(comment_tokens)

    return prefix + schedule_tokens + [
        units,
        instructor,
        prereq,
        advisory,
        comments,
        status,
        seats,
    ]


def extract_table_text(html: str) -> str:
    ts = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    soup = BeautifulSoup(html, "lxml")
    table = (
        soup.select_one(RESULTS_TAB)
        or soup.select_one("#ctl00_PlaceHolderMain_gvResults")
        or soup.select_one("#MainContent_gvResults")
    )
    if not table:
        tables = soup.select("table")
        table = tables[0] if tables else None
    if not table:
        return f"{COURSE_VALUE} sections ({ts}):\n"

    skip_re = re.compile(
        r"""
        ^\s*Course\s+Search\s*$|
        ^\s*Click\s+on\s+the\s+Section\s+#\s+to\s+view\s+course\s+details:\s*$|
        <<\s*Prev\s*|Next\s*>>|
        ^\s*\d+\s*-\s*\d+\s*of\s*\d+\s*$
        """,
        re.IGNORECASE | re.VERBOSE,
    )

    header_line = "Term;Location;Section #;Course;Start Date - End Date;Meeting Days/Time/Building/Room;Units;Instructor(s);Prereq;Advisory;Comments;Status;Seats Available"

    rows_out = [header_line]
    last_instructor = None
    last_main_row = ""

    for tr in table.select("tr"):
        raw_cells = tr.find_all(["th", "td"])
        if not raw_cells:
            continue

        cleaned_cells = []

        for cell in raw_cells:
            parts = [
                sanitize_cell_text(re.sub(r"\s+", " ", p).strip())
                for p in cell.get_text("\n", strip=True).split("\n")
            ]
            parts = [p for p in parts if p]

            if not parts:
                continue

            split_parts = []
            for p in parts:
                m = re.search(
                    r"^(.*?)(\d{1,2}/\d{1,2}/\d{4}\s*-\s*\d{1,2}/\d{1,2}/\d{4})$",
                    p
                )
                if m:
                    left = sanitize_cell_text(m.group(1).strip())
                    right = sanitize_cell_text(m.group(2).strip())
                    if left:
                        split_parts.append(left)
                    split_parts.append(right)
                else:
                    split_parts.append(sanitize_cell_text(p))

            cleaned_cells.extend(split_parts)

        if not cleaned_cells:
            continue

        line_preview = ";".join(cleaned_cells).strip()
        if skip_re.search(line_preview):
            continue

        # skip site header row; we write our own
        if cleaned_cells and cleaned_cells[0].lower() == "term":
            continue

        # remove repeated adjacent cells
        deduped_cells = []
        for cell_value in cleaned_cells:
            if deduped_cells and deduped_cells[-1] == cell_value:
                continue
            deduped_cells.append(cell_value)
        cleaned_cells = deduped_cells

        # remove repeated meeting block if whole meeting block appears twice
        cleaned_cells = collapse_repeated_meeting_block(cleaned_cells)

        if len(cleaned_cells) == 1:
            single = cleaned_cells[0]
            if last_instructor and single == last_instructor:
                continue
            if re.fullmatch(r"[A-Za-z'. -]+,\s*[A-Za-z'. -]+", single):
                continue
            line = single
        else:
            cleaned_cells = normalize_main_row(cleaned_cells)
            line = DELIM.join(cleaned_cells).strip()

            if len(cleaned_cells) > 6:
                last_instructor = cleaned_cells[-6]

            last_main_row = line

        # skip continuation row if already contained in prior main row
        if len(cleaned_cells) in (2, 4):
            if last_main_row and line in last_main_row:
                continue

        rows_out.append(line)

    return f"{COURSE_VALUE} sections ({ts}):\n" + "\n".join(rows_out).strip()


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        page.goto(URL, wait_until="networkidle")

        page.wait_for_selector(TERM_SEL, timeout=10000)
        page.select_option(TERM_SEL, value=TERM_VALUE)
        page.wait_for_load_state("networkidle")

        page.wait_for_selector(COURSE_SEL, timeout=10000)
        options = page.query_selector_all(f"{COURSE_SEL} > option")
        values = {o.get_attribute("value") for o in options if o.get_attribute("value")}

        missing = [c for c in COURSES if c not in values]
        if missing:
            raise RuntimeError(f"Course(s) not found in dropdown: {missing}")

        for course in COURSES:
            page.goto(URL, wait_until="domcontentloaded")
            page.wait_for_selector(TERM_SEL, timeout=10000)
            page.select_option(TERM_SEL, value=TERM_VALUE)
            page.wait_for_load_state("networkidle")
            page.wait_for_selector(COURSE_SEL, timeout=10000)

            global COURSE_VALUE
            COURSE_VALUE = course

            page.select_option(COURSE_SEL, value=course)
            page.click(SEARCH_BTN)

            try:
                page.wait_for_selector(RESULTS_TAB, timeout=15000)
            except PWTimeoutError:
                page.wait_for_load_state("networkidle")

            html = page.content()
            text = extract_table_text(html)
            output_path = os.path.join(OUTPUT_DIR, f"dvc_{TERM_VALUE}_{course}.txt")
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(text)
            print(f"✅ Saved table text to {output_path}")

        browser.close()


if __name__ == "__main__":
    main()