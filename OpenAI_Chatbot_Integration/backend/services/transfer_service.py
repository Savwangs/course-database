"""
TransferAssistant – handles UC-transfer-related queries.

Encapsulates all campus detection, agreement data loading, filtering,
LLM parsing and formatting that was formerly in app.py (lines 514-948).
"""

import json
import os
import re
import glob

import httpx
import os

OPENAI_TIMEOUT_SECONDS = float(os.getenv("OPENAI_TIMEOUT_SECONDS", "20"))

# ---------------------------------------------------------------------------
#  Constants
# ---------------------------------------------------------------------------

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

TYPO_FIXES = {
    r"\busb\b": "uc berkeley",
    r"\bucb\b": "uc berkeley",
    r"\bberkley\b": "berkeley",
    r"\bucsd\b": "uc san diego",
    r"\buc sd\b": "uc san diego",
}

CATEGORY_ALIASES = {
    "major preparation": ["major preparation", "lower division major", "ld major"],
    "lower division major": ["lower division major", "ld major"],
    "general education": ["general education", "ge", "breadth"],
    "breadth": ["breadth", "ge area", "area"],
    "math": ["math", "mathematics"],
    "science": ["science", "natural science", "biology", "chemistry", "physics"],
    "computer science": ["computer science", "cs", "programming", "software"],
}


# ---------------------------------------------------------------------------
#  Private helpers
# ---------------------------------------------------------------------------

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
        "ucb", "ucd", "ucsd", "berkeley", "davis", "san diego",
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


def _normalize_categories_freeform(text: str):
    low = _normalize_typos(text)
    picked = set()

    for m in re.finditer(r'category\s*:\s*[""](.+?)[""]', low):
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
            picked.add(canon)
            continue
        for v in variants:
            if v in low:
                picked.add(canon)
                break

    out = set()
    canon_keys = set(CATEGORY_ALIASES.keys())
    for p in picked:
        matched_key = None
        for ck in canon_keys:
            if ck in p:
                matched_key = ck
                break
        out.add(matched_key or p)
    return sorted(out)


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
            for v in o.values():
                _rec(v)
        elif isinstance(o, list):
            for i in o:
                _rec(i)

    _rec(campus_json)

    seen, dedup = set(), []
    for r in out:
        code = (r.get("dvc_code") or "").strip()
        if code and code not in seen:
            dedup.append(r)
            seen.add(code)
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


def _filter_rows(rows, completed_courses, completed_domains,
                 focus_only, required_only, categories_only):
    filtered = []
    completed_upper = {c.upper() for c in completed_courses}
    for r in rows:
        code = (r.get("dvc_code") or "").upper()
        if code in completed_upper:
            continue
        if "science" in completed_domains and _is_science_row(r):
            continue
        if "math" in completed_domains and _is_math_row(r):
            continue
        if "cs" in completed_domains and _is_cs_row(r):
            continue
        if focus_only == "cs" and not _is_cs_row(r):
            continue
        if focus_only == "math" and not _is_math_row(r):
            continue
        if focus_only == "science" and not _is_science_row(r):
            continue
        if required_only:
            mr = str(r.get("minimum_required", "")).lower()
            if not (mr == "all" or (mr.isdigit() and int(mr) > 0)):
                continue
        if not _row_matches_any_category(r, categories_only or []):
            continue
        filtered.append(r)
    return filtered


# ---------------------------------------------------------------------------
#  TransferAssistant
# ---------------------------------------------------------------------------

class TransferAssistant:
    """Handles UC transfer queries using agreement JSON data and LLM formatting."""

    def __init__(self, openai_client, log_callback=None):
        """
        Args:
            openai_client: An initialized ``openai.OpenAI`` client instance
            log_callback:  callable(user_query, parsed_data, response) for logging
        """
        self.client = openai_client
        self.log_callback = log_callback
        # Lazy-loaded caches
        self._transfer_data = None
        self._transfer_all_rows = None

    # ------------------------------------------------------------------
    #  Public API
    # ------------------------------------------------------------------
    def maybe_handle(self, user_query: str) -> str | None:
        """If the query looks like a UC transfer request, return a formatted
        response string. Otherwise return ``None``."""
        mode = (os.getenv("TRANSFER_MODE") or "auto").lower()
        if mode == "off":
            return None
        is_transfer = _has_transfer_intent(user_query) or (mode == "always")
        if not is_transfer:
            return None

        data = self._ensure_data_loaded()
        if not data:
            resp = (
                "I couldn't load UC transfer mappings. "
                "Please add JSON files under `data/` or `agreements_25-26/`."
            )
            self._log(user_query, {"mode": "uc_transfer", "error": "no_data"}, resp)
            return resp

        parsed = self._llm_parse_user_message(user_query)
        campus_keys = (
            parsed.get("parameters", {}).get("campuses")
            or _detect_campuses_from_query(user_query)
        )
        if not campus_keys:
            resp = (
                "Which campus? I can help with **UC Berkeley (UCB)**, "
                "**UC Davis (UCD)**, or **UC San Diego (UCSD)**."
            )
            self._log(user_query, {"mode": "uc_transfer", "parsed": parsed, "campuses": []}, resp)
            return resp

        completed_courses = set(parsed["filters"].get("completed_courses") or [])
        completed_domains = set(parsed["filters"].get("domains_completed") or [])
        focus_only = parsed["filters"].get("focus_only")
        required_only = bool(parsed["filters"].get("required_only"))
        categories_only = (
            parsed["filters"].get("categories")
            or _normalize_categories_freeform(user_query)
        )

        campus_to_remaining = {}
        for ck in campus_keys:
            if ck not in data:
                continue
            all_rows = (
                self._transfer_all_rows.get(ck)
                if self._transfer_all_rows is not None
                else _collect_course_rows(data[ck])
            )
            campus_to_remaining[ck] = _filter_rows(
                all_rows, completed_courses, completed_domains,
                focus_only, required_only, categories_only,
            )

        resp_text = self._llm_format_multi(
            campus_keys, campus_to_remaining, parsed,
            completed_courses, completed_domains,
        )

        self._log(
            user_query,
            {
                "mode": "uc_transfer",
                "parsed": parsed,
                "campuses": campus_keys,
                "result_counts": {
                    ck: len(campus_to_remaining.get(ck, []))
                    for ck in campus_keys
                },
            },
            resp_text,
        )
        return resp_text

    # ------------------------------------------------------------------
    #  Data loading
    # ------------------------------------------------------------------
    def _ensure_data_loaded(self):
        if self._transfer_data is not None:
            return self._transfer_data
        base_patterns = [
            os.path.join("data", "uc*.json"),
            os.path.join("agreements_25-26", "*.json"),
        ]
        self._transfer_data = _load_all_data(base_patterns)
        self._transfer_all_rows = {
            ck: _collect_course_rows(self._transfer_data[ck])
            for ck in self._transfer_data
        }
        if not self._transfer_data:
            print("⚠️ UC transfer: no campus files loaded. Check data/ and agreements_25-26/")
        return self._transfer_data

    # ------------------------------------------------------------------
    #  LLM helpers
    # ------------------------------------------------------------------
    def _llm_chat_text(self, messages, model, temperature=0.0, response_format=None):
        params = dict(
            model=model,
            temperature=temperature,
            messages=messages,
            timeout=OPENAI_TIMEOUT_SECONDS,
        )

        if response_format is not None:
            params["response_format"] = response_format

        try:
            resp = self.client.chat.completions.create(**params)
            return resp.choices[0].message.content.strip()

        except (httpx.TimeoutException, httpx.ReadTimeout):
            print("⚠️ OpenAI request timed out.")
            return "The assistant is taking too long to respond. Please try again in a moment."

        except Exception as e:
            print(f"⚠️ OpenAI error: {e}")
            return "The assistant encountered an unexpected error. Please try again."

    def _llm_parse_user_message(self, user_message):
        system = (
            "You are an assistant that parses TRANSFER-ONLY student questions for UC transfer "
            "planning from Diablo Valley College (DVC). "
            "Output STRICT JSON (no markdown). Keys: intent, parameters, filters.\n"
            "Allowed intents: find_requirements, find_equivalent_course.\n"
            "parameters.campus: UCB/UCD/UCSD or null.\n"
            "parameters.campuses: array of campuses (UCB, UCD, UCSD).\n"
            "filters.focus_only: 'cs'|'math'|'science'|'all'|null; "
            "filters.required_only: boolean; "
            "filters.domains_completed: ['cs'|'math'|'science']; "
            "filters.completed_courses: ['COMSC-110', ...]; "
            "filters.categories: e.g., 'major preparation','breadth'. "
            "If unsure, return null/empty."
        )
        text = self._llm_chat_text(
            model="gpt-4.1",
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_message},
            ],
            timeout=OPENAI_TIMEOUT_SECONDS,
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
            if not isinstance(c, str):
                continue
            det = _detect_campus_from_query(c) or c.upper().strip()
            if det in PRETTY_CAMPUS:
                campuses_norm.append(det)
        campuses_norm = sorted(set(campuses_norm))
        params["campus"] = campuses_norm[0] if campuses_norm else None
        params["campuses"] = campuses_norm

        focus = filt.get("focus_only")
        if isinstance(focus, str):
            focus = focus.lower().strip()
            if focus not in {"cs", "math", "science", "all"}:
                focus = None
        else:
            focus = None
        filt["focus_only"] = focus
        filt["required_only"] = bool(filt.get("required_only", False))

        domains = filt.get("domains_completed") or []
        if isinstance(domains, list):
            domains = {
                d for d in (x.lower().strip() for x in domains)
                if d in {"cs", "math", "science"}
            }
        else:
            domains = set()
        filt["domains_completed"] = sorted(domains)

        comp = filt.get("completed_courses") or []
        comp = comp if isinstance(comp, list) else []
        norm = set()
        for raw in comp:
            if isinstance(raw, str):
                s = raw.upper().strip().replace(" ", "-")
                m = re.match(r"^([A-Z&]+)[- ]?(\d+[A-Za-z]?)$", s)
                if m:
                    s = f"{m.group(1)}-{m.group(2)}"
                norm.add(s)
        for code in re.findall(
            r"\b([A-Za-z]{2,}[- ]?\d+[A-Za-z]?)\b", user_message, flags=re.IGNORECASE,
        ):
            s = code.upper().strip().replace(" ", "-")
            m = re.match(r"^([A-Z&]+)[- ]?(\d+[A-Za-z]?)$", s)
            if m:
                s = f"{m.group(1)}-{m.group(2)}"
            norm.add(s)
        filt["completed_courses"] = sorted(norm)

        cats = filt.get("categories") or []
        cats = cats if isinstance(cats, list) else []
        cats_local = _normalize_categories_freeform(user_message)
        filt["categories"] = sorted(
            set([c for c in cats if isinstance(c, str) and c.strip()] + cats_local)
        )

        return data

    def _llm_format_multi(self, campus_keys, campus_to_rows, parsed,
                          completed_courses, completed_domains):
        chunks = []
        for ck in campus_keys:
            campus_name = PRETTY_CAMPUS.get(ck, ck)
            items = [
                {
                    "course": (r.get("dvc_code") or "").strip(),
                    "title": (r.get("dvc_title") or "").strip(),
                    "units": r.get("dvc_units", ""),
                }
                for r in campus_to_rows.get(ck, [])
            ]

            payload = {
                "campus": campus_name,
                "intent": parsed.get("intent"),
                "parameters": parsed.get("parameters", {}),
                "filters": parsed.get("filters", {}),
                "excluding": {
                    "completed_domains": sorted(list(completed_domains)),
                    "completed_courses": sorted(list(completed_courses)),
                },
                "courses": items,
            }
            text = self._llm_chat_text(
                model="gpt-4.1",
                temperature=0.2,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Format UC transfer mappings only (no availability/schedule).\n"
                            "Output:\n"
                            "• One summary line: 'Transfer prep for <Campus>:'\n"
                            "• Optional parenthetical note "
                            "'(excluding completed domains: ...; completed courses: ... )'\n"
                            "• Bullets: '• COMSC-200 — Object Oriented Programming C++ (4 units)'\n"
                            "If empty, say: 'No DVC course mappings found.'\n\n"
                            "POLICY: Do not make definitive guarantees about admission (e.g. 'You will get into X'). "
                            "Requirements are based on articulation data; students should verify with assist.org and the university. "
                            "If the user asks whether they will get in, say they should verify with assist.org and the UC campus."
                        ),
                    },
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ],
                timeout=OPENAI_TIMEOUT_SECONDS,
            )
            chunks.append(
                text.strip() if text
                else f"Transfer prep for {campus_name}:\nNo DVC course mappings found."
            )
        return "\n\n".join(chunks)

    # ------------------------------------------------------------------
    #  Logging shim
    # ------------------------------------------------------------------
    def _log(self, user_query, parsed_data, response):
        if self.log_callback is not None:
            self.log_callback(user_query, parsed_data, response)
