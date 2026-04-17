from __future__ import annotations

import json
import re

from bs4 import BeautifulSoup
from openai import OpenAI

import config


_client: OpenAI | None = None


def _ai() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(
            api_key=config.AI_API_KEY or "hackclub",
            base_url=config.AI_BASE_URL,
        )
    return _client


def strip_page_noise(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup.find_all(["script", "style", "noscript", "iframe",
                               "svg", "path", "meta", "link"]):
        tag.decompose()

    main = (
        soup.find("main") or
        soup.find("article") or
        soup.find("div", {"role": "main"}) or
        soup.find("div", {"id": re.compile(r"content|main", re.I)}) or
        soup.find("div", {"class": re.compile(
            r"content|main|staff|faculty|directory|listing", re.I)})
    )
    target = main or soup.find("body") or soup
    text = target.get_text(separator="\n", strip=True)

    mailto_lines: list[str] = []
    for a in (main or soup).find_all("a", href=True):
        href = a["href"]
        if "mailto:" in href:
            email = href.replace("mailto:", "").split("?")[0].strip()
            label = a.get_text(strip=True)
            if email:
                mailto_lines.append(f"{label}: {email}" if label else email)
    if mailto_lines:
        text += "\n\nEmails in links:\n" + "\n".join(mailto_lines)

    return re.sub(r"\n{3,}", "\n\n", text)


def split_into_chunks(text: str, size: int = config.HTML_CHUNK_SIZE) -> list[str]:
    if len(text) <= size:
        return [text]
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = start + size
        if end >= len(text):
            chunks.append(text[start:])
            break
        bp = text.rfind("\n\n", start + size // 2, end)
        if bp == -1:
            bp = text.rfind("\n", start + size // 2, end)
        if bp > start:
            end = bp
        chunks.append(text[start:end])
        start = end
    return chunks


_BAD_FRAGMENTS = [
    "directory", "staff", "faculty", "department", "school",
    "district", "instruction", "contact", "search", "start over",
    "home", "email address", "office phone",
    "powerteacher", "powerschool", "schoolmessenger", "acceptable use",
    "agreement", "current topics", "score", "gradebook", "grading",
    "how to", "set up", "setup", "print", "reports", "help guides",
    "teacher help", "standards based", "recalculate",
]


def looks_like_name(text: str) -> bool:
    words = [w for w in text.strip().split() if w]
    if not (2 <= len(words) <= 5):
        return False
    if not (5 <= len(text) <= 60):
        return False
    if any(ch.isdigit() for ch in text):
        return False
    if any(frag in text.lower() for frag in _BAD_FRAGMENTS):
        return False
    if not re.match(r"^[A-Za-z][A-Za-z.\-\',\s]+$", text):
        return False
    clean = [t.strip(".,") for t in words]
    alpha = [t for t in clean if re.match(r"^[A-Za-z][A-Za-z'\-]*$", t)]
    return len(alpha) >= 2 and sum(1 for t in alpha if t[0].isupper()) >= 2


_NOISE_TERMS = [
    "powerteacher", "powerschool", "schoolmessenger", "acceptable use",
    "how to", "help guide", "teacher help", "gradebook", "grading",
    "reports", "scoresheet", "current topics", "setup", "set up",
]


def _is_noise(person: dict) -> bool:
    if not looks_like_name(person.get("name") or ""):
        return True
    haystack = " ".join([
        person.get("name") or "",
        person.get("role") or "",
        person.get("department") or "",
    ]).lower()
    if any(t in haystack for t in _NOISE_TERMS):
        return True
    if not person.get("role"):
        if len((person.get("name") or "").split()) > 3:
            return True
    email = (person.get("email") or "").lower()
    if email and email.split("@")[0].count(".") >= 2 and not person.get("role"):
        return True
    return False


def _drop_noise(records: list[dict]) -> list[dict]:
    return [r for r in records if not _is_noise(r)]


def _looks_like_real_directory(records: list[dict]) -> bool:
    if not records:
        return False
    n = len(records)
    good_names    = sum(1 for r in records if looks_like_name(r.get("name") or ""))
    has_contact   = sum(1 for r in records if r.get("email") or r.get("phone"))
    has_role      = sum(1 for r in records if (r.get("role") or "").strip())
    if n <= 3:
        return good_names >= 1 and (has_contact >= 1 or has_role >= 1)
    if good_names / n < 0.7:
        return False
    return has_contact >= 2 or has_role / n >= 0.4


_HINTS = {
    "math":       ["math", "mathematics", "algebra", "calculus",
                   "geometry", "trigonometry", "statistics"],
    "science":    ["science", "biology", "chemistry", "physics",
                   "earth science", "environmental science", "anatomy"],
    "stem":       ["stem", "steam", "engineering", "robotics",
                   "computer science", "coding", "programming"],
    "technology": ["technology", "tech ed", "information technology",
                   "computer", "coding", "makerspace"],
}


def detect_page_subject(text: str, page_url: str) -> str | None:
    combined = f"{text[:12000]} {page_url}".lower()
    matches = {
        label for label, aliases in _HINTS.items()
        if any(a in combined for a in aliases)
    }
    return next(iter(matches)) if len(matches) == 1 else None


def _tag_with_subject(records: list[dict], hint: str | None) -> list[dict]:
    if not hint:
        return records
    for r in records:
        r["page_subject_hint"] = hint
        if not r.get("department"):
            r["department"] = hint
    return records


def _parse_labeled_rows(text: str) -> list[dict]:
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    people: list[dict] = []
    i = 0

    while i < len(lines):
        line = lines[i]
        if not looks_like_name(line):
            i += 1
            continue

        window = " ".join(lines[i + 1: i + 9]).lower()
        if not any(k in window for k in ("titles:", "email:", "locations:", "phone:")):
            i += 1
            continue

        person: dict = {"name": line}
        j, consumed = i + 1, 0

        while j < len(lines) and consumed < 8:
            cur = lines[j].strip()
            cl  = cur.lower()

            if cl.startswith("titles:"):
                person["role"] = cur.split(":", 1)[1].strip()
            elif cl.startswith(("locations:", "location:")):
                person["department"] = cur.split(":", 1)[1].strip()
            elif cl.startswith("email:"):
                m = re.search(config.EMAIL_REGEX, cur)
                if m:
                    person["email"] = m.group().lower()
            elif cl.startswith(("phone:", "office phone:")):
                person["phone"] = cur.split(":", 1)[1].strip()
            else:
                m = re.search(config.EMAIL_REGEX, cur)
                if m and not person.get("email"):
                    person["email"] = m.group().lower()
                    j += 1
                    break
                if consumed >= 1 and looks_like_name(cur):
                    break

            j += 1
            consumed += 1

        if person.get("email") or person.get("role"):
            people.append(person)
            i = j
        else:
            i += 1

    return people


_SKIP = {
    "skip to", "search", "select", "jump to", "find us",
    "phone:", "fax:", "showing", "of ", "page", "next",
    "previous", "copyright", "all rights", "powered by",
    "translate", "menu", "schools", "home", "keyword",
    "first name", "last name", "location", "all locations",
    "departments", "school district", "high school",
    "middle school", "elementary", "central school",
    "community school", "central office", "school board", "equity",
}
_JUNK = {
    "staff directory", "faculty directory", "directory", "keyword",
    "first name", "last name", "all locations", "departments",
}
_PHONE = re.compile(r"[\(]?\d{3}[\)]?[\s\-\.]\d{3}[\s\-\.]\d{4}")
_ROLE_SIGNAL = re.compile(
    r"\b(teacher|principal|assistant principal|counselor|director|"
    r"coordinator|specialist|librarian|psychologist|nurse|coach|"
    r"instructor|professor|educator|interventionist|paraeducator|"
    r"administrator|dean|secretary)\b"
)


def _parse_free_text(text: str) -> list[dict]:
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    records: list[dict] = []
    i = 0

    while i < len(lines):
        line = lines[i]
        if len(line) < 3 or len(line) > 80:
            i += 1
            continue
        if any(kw in line.lower() for kw in _SKIP):
            i += 1
            continue

        words = line.split()
        is_name = (
            2 <= len(words) <= 5 and
            re.match(r"^[A-Za-z\s.\-\',]+$", line) and
            not re.search(config.EMAIL_REGEX, line) and
            not _PHONE.search(line) and
            not re.search(r"\d", line) and
            len(line) >= 5 and
            not any(p in line.lower() for p in _JUNK) and
            not re.search(r"\bschool\b", line.lower())
        )

        if not is_name:
            i += 1
            continue

        name = line.strip()
        if name == name.upper():
            name = name.title()

        person: dict = {"name": name}
        i += 1
        consumed = 0

        while i < len(lines) and consumed < 6:
            nxt = lines[i].strip()
            if not nxt or len(nxt) < 2:
                i += 1
                consumed += 1
                continue

            em = re.search(config.EMAIL_REGEX, nxt)
            ph = _PHONE.search(nxt)

            if em and not person.get("email"):
                person["email"] = em.group().lower()
                i += 1
                consumed += 1
            elif nxt.lower().startswith(("school:", "phone:")) and ph:
                person["phone"] = ph.group()
                i += 1
                consumed += 1
            elif ph and not em and not person.get("phone"):
                person["phone"] = ph.group()
                i += 1
                consumed += 1
            elif not person.get("role") and len(nxt) > 3 and not re.match(r"^\d+$", nxt):
                person["role"] = nxt
                i += 1
                consumed += 1
            elif not person.get("department") and 3 < len(nxt) < 80:
                person["department"] = nxt
                i += 1
                consumed += 1
            else:
                break

        role_l = (person.get("role") or "").lower()
        has_contact = bool(person.get("email") or person.get("phone"))
        has_role    = bool(_ROLE_SIGNAL.search(role_l))

        if person.get("name") and (has_contact or has_role):
            records.append(person)

    return records


def _strip_thinking_tags(text: str) -> str:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    text = re.sub(r"<think>.*",          "", text, flags=re.DOTALL)
    text = re.sub(r"^```(?:json)?\s*\n?", "", text.strip(), flags=re.MULTILINE)
    text = re.sub(r"\n?```\s*$",          "", text.strip(), flags=re.MULTILINE)
    return text.strip()


def _safe_json_array(text: str) -> list[dict] | None:
    text = _strip_thinking_tags(text)
    try:
        r = json.loads(text)
        if isinstance(r, list):
            return r
    except json.JSONDecodeError:
        pass
    s, e = text.find("["), text.rfind("]")
    if s != -1 and e > s:
        candidate = text[s: e + 1]
        try:
            r = json.loads(candidate)
            if isinstance(r, list):
                return r
        except json.JSONDecodeError:
            for fix in ["]", "}]", '"}]', '", "phone": null}]']:
                try:
                    r = json.loads(candidate + fix)
                    if isinstance(r, list):
                        return r
                except json.JSONDecodeError:
                    continue
    return None


def _safe_json_object(text: str) -> dict:
    text = _strip_thinking_tags(text)
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        try:
            r = json.loads(m.group())
            if isinstance(r, dict):
                return r
        except json.JSONDecodeError:
            pass
    try:
        r = json.loads(text)
        if isinstance(r, dict):
            return r
    except json.JSONDecodeError:
        pass
    return {}


def _llm_extract(text: str, page_url: str) -> list[dict]:
    if not config.AI_API_KEY:
        return []
    client = get_ai_client()
    chunks = split_into_chunks(text)
    hint   = detect_page_subject(text, page_url)
    all_records: list[dict] = []
    print(f"    [AI] {len(chunks)} chunk(s), subject={hint!r}")

    extra: dict = {}
    if "qwen" in config.AI_MODEL.lower():
        extra["extra_body"] = {"chat_template_kwargs": {"thinking": False}}

    for i, chunk in enumerate(chunks):
        prompt = config.STAFF_EXTRACTION_PROMPT + f"\n\nContent:\n{chunk}"
        try:
            resp = client.chat.completions.create(
                model=config.AI_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=4000,
                **extra,
            )
            raw    = (resp.choices[0].message.content or "").strip()
            parsed = _safe_json_array(raw)
            if parsed:
                parsed = _drop_noise(parsed)
                parsed = _tag_with_subject(parsed, hint)
                print(f"    [AI] chunk {i+1}: {len(parsed)} record(s)")
                all_records.extend(parsed)
            else:
                print(f"    [AI] chunk {i+1}: nothing extracted")
        except Exception as exc:
            print(f"    [AI] chunk {i+1} error: {exc}")

    return all_records


def get_ai_client() -> OpenAI:
    return _ai()


def parse_staff_from_html(html: str, page_url: str = "") -> list[dict]:
    text = strip_page_noise(html)
    if not text.strip() or len(text.strip()) < 50:
        return []

    hint = detect_page_subject(text, page_url)

    records = _parse_labeled_rows(text)
    if records:
        records = _drop_noise(records)
        records = _tag_with_subject(records, hint)
        if _looks_like_real_directory(records):
            print(f"    [labeled] {len(records)} record(s)")
            _preview(records)
            return records

    records = _parse_free_text(text)
    if records:
        records = _drop_noise(records)
        records = _tag_with_subject(records, hint)
        if _looks_like_real_directory(records):
            print(f"    [regex] {len(records)} record(s)")
            _preview(records)
            return records
        print(f"    [regex] noisy ({len(records)} rows) → AI fallback")

    return _llm_extract(text, page_url)


_US_STATE_RE = re.compile(
    r"\b(AL|AK|AZ|AR|CA|CO|CT|DE|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|"
    r"MD|MA|MI|MN|MS|MO|MT|NE|NV|NH|NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|"
    r"SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY|DC)\b"
)
_ZIP_RE   = re.compile(r"\b(\d{5})(?:-\d{4})?\b")
_PHONE_RE = re.compile(r"\(?\d{3}\)?[\s.\-]\d{3}[\s.\-]\d{4}")
_STREET_RE = re.compile(
    r"\b(\d{2,5}\s+[A-Za-z][A-Za-z0-9\s,\.]+"
    r"(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Drive|Dr|"
    r"Lane|Ln|Court|Ct|Way|Place|Pl|Circle|Cir|Highway|Hwy|Route|Rt)\b[\w\s,]*)",
    re.IGNORECASE,
)

def _regex_school_info(html: str) -> dict:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup.find_all(["script", "style", "noscript", "iframe", "svg"]):
        tag.decompose()

    title_tag = soup.find("title")
    title     = title_tag.get_text(strip=True) if title_tag else ""

    blocks: list[str] = []
    for sel in ["header", "footer", '[class*="footer"]', '[class*="address"]',
                '[class*="contact"]', '[id*="footer"]', '[id*="address"]']:
        for el in soup.select(sel)[:2]:
            blocks.append(el.get_text(separator=" ", strip=True))
    full_text = " ".join(blocks) or soup.get_text(separator=" ", strip=True)
    full_text = re.sub(r"\s+", " ", full_text)

    street = ""
    m = _STREET_RE.search(full_text)
    if m:
        street = re.sub(r"\s+", " ", m.group(1)).strip()

    state, zip_code, city = "", "", ""
    sm = _US_STATE_RE.search(full_text)
    if sm:
        state    = sm.group(1)
        zm = _ZIP_RE.search(full_text[sm.start():])
        if zm:
            zip_code = zm.group(1)
        prefix = full_text[max(0, sm.start()-60):sm.start()].strip()
        city_m = re.search(r"([A-Z][A-Za-z]+(?:\s[A-Z][A-Za-z]+)?)\s*,?\s*$", prefix)
        if city_m:
            city = city_m.group(1)

    phone = ""
    pm = _PHONE_RE.search(full_text)
    if pm:
        phone = pm.group(0).strip()

    school_name = ""
    if title:
        parts = re.split(r"[|\-–—]", title)
        for p in parts:
            pn = p.strip()
            if re.search(r"school|academy|district|institute", pn, re.I):
                school_name = pn
                break
        if not school_name:
            school_name = parts[0].strip()

    return {
        "school_name": school_name,
        "address":     street,
        "city":        city,
        "state":       state,
        "zip":         zip_code,
        "phone":       phone,
    }


def extract_school_info(html: str) -> dict:
    info = _regex_school_info(html)
    if info.get("school_name") and info.get("state"):
        return info

    if not config.AI_API_KEY:
        return info

    soup = BeautifulSoup(html, "lxml")
    for tag in soup.find_all(["script", "style", "noscript", "iframe", "svg"]):
        tag.decompose()
    text = re.sub(r"\n{3,}", "\n\n",
                  soup.get_text(separator="\n", strip=True))
    half = config.HTML_CHUNK_SIZE // 2
    if len(text) > config.HTML_CHUNK_SIZE:
        text = text[:half] + "\n...\n" + text[-half:]

    extra: dict = {}
    if "qwen" in config.AI_MODEL.lower():
        extra["extra_body"] = {"chat_template_kwargs": {"thinking": False}}

    prompt = config.SCHOOL_ADDRESS_PROMPT + f"\n\nContent:\n{text}"
    try:
        resp = _ai().chat.completions.create(
            model=config.AI_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=400,
            **extra,
        )
        return _safe_json_object((resp.choices[0].message.content or "").strip())
    except Exception as exc:
        print(f"  [!] AI address error: {exc}")
        return info


extract_school_address = extract_school_info


def _preview(records: list[dict], n: int = 3) -> None:
    for r in records[:n]:
        print(f"       -> {r.get('name','?')} | {r.get('role','?')} | {r.get('email','?')}")
    if len(records) > n:
        print(f"       ... and {len(records)-n} more")
