# dvc_playwright_singlepage.py
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError
from bs4 import BeautifulSoup
import re
from datetime import datetime  
import os                    

URL = "https://webapps.4cd.edu/apps/courseschedulesearch/search-course.aspx?search=dvc"

# --- EDIT THESE ---
TERM_VALUE   = "2026SP"
COURSES = [
    "BIOSC-101","BIOSC-102","BIOSC-116","BIOSC-117","BIOSC-119","BIOSC-120","BIOSC-126",
    "BIOSC-130","BIOSC-131","BIOSC-139","BIOSC-140","BIOSC-146","BIOSC-162","BIOSC-170",
    "BIOSC-171","BUS-240","CHEM-107","CHEM-108","CHEM-109","CHEM-120","CHEM-121","CHEM-227",
    "COMSC-010NC","COMSC-020NC","COMSC-101","COMSC-110","COMSC-140","COMSC-156","COMSC-165",
    "COMSC-171","COMSC-175","COMSC-178","COMSC-200","COMSC-210","COMSC-255","COMSC-260",
    "COMSC-295","ENGIN-110","ENGIN-120","ENGIN-121","ENGIN-130","ENGIN-131","ENGIN-135",
    "ENGIN-136","ENGIN-210","ENGIN-230","ENGIN-240","ENGIN-257","ENGL-122AL","ENGL-123",
    "ENGL-124","ENGL-126A","ENGL-140A","ENGL-151","ENGL-153","ENGL-154","ENGL-164","ENGL-166",
    "ENGL-168","ENGL-170","ENGL-173","ENGL-175","ENGL-176","ENGL-178","ENGL-180","ENGL-222",
    "ENGL-223","ENGL-224","ENGL-225","ENGL-253","ENGL-263","ENGL-C1000","ENGL-C1000E",
    "ENGL-C1001","MATH-002","MATH-081","MATH-082","MATH-092","MATH-121","MATH-121L","MATH-124",
    "MATH-135","MATH-135L","MATH-140","MATH-181","MATH-182","MATH-183","MATH-191","MATH-191L",
    "MATH-192","MATH-193","MATH-194","MATH-195","MATH-289","MATH-292","MATH-294","PHYS-110",
    "PHYS-112","PHYS-120","PHYS-121","PHYS-124","PHYS-125","PHYS-129","PHYS-130","PHYS-230",
    "PHYS-231","STAT-C1000","STAT-C1000E"
]

COURSE_VALUE = "" 
OUTPUT_FILE  = f"dvc_{TERM_VALUE}_{COURSE_VALUE}.txt"
OUTPUT_DIR = "dvc_txt" 
# ------------------
DELIM = ";"
TERM_SEL    = 'select[id$="SEC_TERM"]'
COURSE_SEL  = 'select[id$="X_COURSE"]'
SEARCH_BTN  = 'input[id$="btnSearch"]'
RESULTS_TAB = 'table[id$="gvResults"]'  

def extract_table_text(html: str) -> str:
    ts = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    soup = BeautifulSoup(html, "lxml")
    table = (soup.select_one(RESULTS_TAB)
             or soup.select_one("#ctl00_PlaceHolderMain_gvResults")
             or soup.select_one("#MainContent_gvResults"))
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

    rows_out = []
    for tr in table.select("tr"):
        cells = [c.get_text(strip=True, separator=" ") for c in tr.find_all(["th", "td"])]
        if not cells:
            continue
        line = DELIM.join(cells).strip()

        if skip_re.search(line):
            continue
        if len(cells) == 1 and not re.search(r"[A-Za-z]\d|\d[A-Za-z]", line):
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