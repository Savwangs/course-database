# dvc_txt_to_json.py
import re
import json
from pathlib import Path

INPUT_DIR  = Path("dvc_txt")
OUTPUT_DIR = Path("dvc_json")
DELIM = ";"  # must match the scraper's delimiter

DAY_TOKENS = {"M", "T", "W", "Th", "F", "Sa", "Su", "Online"}

def _infer_format(*parts: str) -> str:
    blob = " ".join(p.lower() for p in parts if p)
    if "hybrid" in blob or "part-onl" in blob or ("part" in blob and "onl" in blob):
        return "hybrid"
    if "online" in blob:
        return "online"
    return "in-person"

def _normalize_days(s: str) -> str:
    if not s:
        return ""
    s = s.replace("TTh", "T Th").replace("MW", "M W")
    s = s.replace("/", " ").replace(",", " ")
    toks = [t for t in s.split() if t]
    if any(t.lower() == "online" for t in toks):
        return "Online"
    kept = [t for t in toks if t in DAY_TOKENS]
    return " ".join(kept) if kept else s

def _parse_course_code_title(cell: str) -> tuple[str, str]:
    m = re.search(r'([A-Z0-9-]{3,})\s*-\s*([A-Za-z0-9:,&\-\s]+?)\s+\d{1,2}/\d{1,2}/\d{4}', cell)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return "", ""

def _term_from_filename(name: str) -> str:
    m = re.search(r"dvc_([A-Za-z0-9]+)_", name)
    return m.group(1) if m else ""

def _extract_last_update(text: str) -> str:
    """
    Extract timestamp from the top line like:
    'PHYS-231 sections (2025-10-15T00:57:48):'
    """
    m = re.search(r"\((\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})\)", text)
    return m.group(1) if m else ""

def parse_course_txt_to_object(txt_path: Path) -> dict | None:
    txt = txt_path.read_text(encoding="utf-8").strip()
    lines = [ln.strip() for ln in txt.splitlines() if ln.strip()]
    if not lines:
        return None

    # Extract timestamp from the header
    last_update = _extract_last_update(lines[0])

    # Find header row (semicolon-delimited) that contains typical columns
    header_idx = None
    for i, ln in enumerate(lines):
        low = ln.lower()
        if all(k in low for k in ["term", "location", "section", "course", "instructor", "status"]):
            header_idx = i
            break
    if header_idx is None:
        return None

    term_value = _term_from_filename(txt_path.name)

    def is_new_section(ln: str) -> bool:
        return (term_value and ln.startswith(f"{term_value};")) or ln.startswith("202")

    course_code, course_title = "", ""
    sections = []
    i = header_idx + 1

    while i < len(lines):
        ln = lines[i]
        if not is_new_section(ln):
            i += 1
            continue

        cells = [c.strip() for c in ln.split(DELIM)]
        section_num = cells[2] if len(cells) > 2 else ""

        mega = cells[3] if len(cells) > 3 else ""
        code, title = _parse_course_code_title(mega)
        if code:  course_code = course_code or code
        if title: course_title = course_title or title

        units_idx = None
        for idx, c in enumerate(cells):
            if re.fullmatch(r"\d+\.\d{2}", c):
                units_idx = idx

        instructor = ""
        comments   = ""
        status     = ""
        if units_idx is not None:
            tail = cells[units_idx+1:]
            if len(tail) >= 1: instructor = tail[0].split(";")[0].strip()
            if len(tail) >= 3: comments   = tail[2].strip()
            if len(tail) >= 4: status     = tail[3].strip()

        section_obj = {
            "section_number": section_num,
            "instructor": instructor,
            "meetings": [],
            "status": status or "Open, Seats Available",
        }
        sections.append(section_obj)

        i += 1
        while i < len(lines) and not is_new_section(lines[i]):
            cont = lines[i]
            parts = [p.strip() for p in cont.split(DELIM)]
            days = parts[0] if len(parts) > 0 else ""
            time = parts[1] if len(parts) > 1 else ""
            bldg = parts[2] if len(parts) > 2 else ""
            room = parts[3] if len(parts) > 3 else ""

            fmt = _infer_format(days, time, bldg, room)
            ndays = _normalize_days(days) or ("Online" if "online" in (bldg + " " + room).lower() else "")
            ntime = time or ("Asynchronous" if "online" in (bldg + " " + room).lower() else "")
            nroom = room or ("Online" if "online" in (bldg + " " + time + " " + days).lower() else "")

            if ndays or ntime or nroom:
                tup = (ndays, ntime, nroom, fmt)
                if tup not in [(m["days"], m["time"], m["room"], m["format"]) for m in section_obj["meetings"]]:
                    section_obj["meetings"].append({
                        "days": ndays, "time": ntime, "room": nroom, "format": fmt
                    })
            i += 1

    if not sections:
        return None

    prereq = None
    mpr = re.search(r"Prerequisite:\s*(.+?)(?:\s*Note:|$)", "\n".join(lines),
                    flags=re.IGNORECASE | re.DOTALL)
    if mpr:
        prereq = mpr.group(1).strip()

    obj = {
        "course_code": course_code,
        "course_title": course_title,
        "last_update": last_update,
        "sections": sections,
    }
    if prereq:
        obj["prerequisites"] = prereq
    return obj

def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    txt_files = sorted(INPUT_DIR.glob("dvc_*.txt"))

    if not txt_files:
        print(f"⚠️  No .txt files found in {INPUT_DIR.resolve()}")
        return

    written = 0
    for txt_path in txt_files:
        obj = parse_course_txt_to_object(txt_path)
        if not obj:
            print(f"⚠️  Skipped (unparseable): {txt_path.name}")
            continue

        out_name = txt_path.with_suffix(".json").name
        out_path = OUTPUT_DIR / out_name
        out_path.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"✅ Wrote {out_path}")
        written += 1

    print(f"Done. Converted {written} file(s) into {OUTPUT_DIR.resolve()}")

if __name__ == "__main__":
    main()
