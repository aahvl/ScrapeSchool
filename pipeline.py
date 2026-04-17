from __future__ import annotations

import re
import smtplib
import socket
import time

import config
from contacts import infer_address_pattern, build_address_from_pattern

try:
    import dns.resolver
    HAS_DNS = True
except ImportError:
    HAS_DNS = False
    print("[!] dnspython not installed — DNS email verification disabled")


_STEM_SUBJECTS = {
    "math", "mathematics", "algebra", "geometry", "calculus",
    "trigonometry", "statistics", "pre-calculus", "precalculus", "pre-algebra",
    "science", "biology", "chemistry", "physics",
    "earth science", "environmental science", "life science",
    "physical science", "anatomy", "physiology", "ecology",
    "geology", "astronomy", "marine biology", "forensic science",
    "zoology", "botany",
    "stem", "steam", "engineering", "computer science",
    "robotics", "coding", "programming", "information technology",
    "tech ed", "data science", "biomedical", "makerspace",
    "cyber", "digital learning", "design technology",
}
_STEM_PHRASES = [
    "ap calculus", "ap statistics", "ap biology", "ap chemistry",
    "ap physics", "ap computer", "ap environmental",
    "computer applications", "instructional technology",
    "technology education", "applied science", "applied math",
    "math specialist", "math coach", "math interventionist",
    "mathematics interventionist", "math and science",
    "science coach", "stem teacher", "stem coordinator",
    "5-8 math", "k-8 math", "k-12 math",
]

_HARD_BLOCK_ROLES = {
    "nurse", "school nurse",
    "counselor", "school counselor", "guidance counselor",
    "psychologist", "social worker",
    "secretary", "receptionist", "registrar", "accountant",
    "librarian", "custodian", "janitor", "bus driver",
    "food service", "cafeteria",
    "paraprofessional", "paraeducator",
    "speech", "speech-language", "speech language",
    "occupational therapist", "occupational therapy",
    "physical therapist", "physical therapy",
    "art teacher", "art instructor",
    "music teacher", "band teacher", "choir", "orchestra",
    "drama teacher", "theater teacher", "theatre teacher",
    "physical education", "pe teacher", "gym teacher",
    "english teacher", "language arts",
    "reading teacher", "literacy coach", "literacy teacher",
    "history teacher", "social studies", "world history",
    "civics", "economics teacher",
    "foreign language", "world language",
    "spanish teacher", "french teacher", "german teacher", "latin teacher",
    "wellness teacher", "wellness coach",
    "intervention teacher", "interventionist",
    "special educator", "special education",
    "multilingual", "ell teacher", "esl teacher",
    "superintendent", "assistant superintendent",
    "assistant principal", "principal",
    "administrative assistant", "office manager",
    "facs", "family and consumer",
    "nexus teacher",
    "literacy", "literacy coach", "literacy teacher", "literacy specialist",
    "reading specialist", "reading coach", "reading teacher",
    "instructional coach",
}

_SCHOOL_NAME_WORDS = {
    "school", "academy", "institute", "district", "union",
    "elementary", "middle", "high", "community", "central",
}


def _is_school_name(text: str) -> bool:
    words = set(text.lower().split())
    return bool(words & _SCHOOL_NAME_WORDS)


def _contains_stem(text: str) -> bool:
    tl = text.lower()
    for phrase in _STEM_PHRASES:
        if phrase in tl:
            return True
    if re.search(r"\d+[-–]\d+\s+math", tl):
        return True
    for subj in _STEM_SUBJECTS:
        if re.search(rf"(?<![a-z0-9]){re.escape(subj)}(?![a-z0-9])", tl):
            return True
    return False


def _is_blocked(text: str) -> bool:
    tl = text.lower()
    for term in _HARD_BLOCK_ROLES:
        if re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", tl):
            return True
    return False


def _is_grade_level_teacher(role: str) -> bool:
    return bool(re.search(
        r"\b(k\s*[-–]?\s*\d|kindergarten|\d+\s*(st|nd|rd|th)\s*grade"
        r"|\d+/\d+\s*grade|grade\s*\d+)\b",
        role.lower()
    ))


def is_stem_subject(teacher: dict) -> bool:
    role = (teacher.get("role") or "").strip()
    dept = (teacher.get("department") or "").strip()
    role_l = role.lower()
    dept_l = dept.lower()

    _LITERACY_OVERRIDE = {"literacy", "reading specialist", "reading coach", "instructional coach"}
    role_has_literacy = any(t in role_l for t in _LITERACY_OVERRIDE)

    if not role_has_literacy:
        for phrase in _STEM_PHRASES:
            if phrase in role_l:
                return True
        if re.search(r"\d+[-–]\d+\s+math", role_l):
            return True

    if _is_blocked(role_l):
        return False

    if _is_grade_level_teacher(role_l):
        return False

    if not role_has_literacy:
        for subj in _STEM_SUBJECTS:
            if re.search(rf"(?<![a-z0-9]){re.escape(subj)}(?![a-z0-9])", role_l):
                return True

    dept_is_subject = dept and not _is_school_name(dept_l)
    if dept_is_subject and _contains_stem(dept_l):
        return True

    if re.search(r"^(teacher|educator|instructor|faculty|professor|staff)$", role_l.strip()):
        return False

    return False


def is_any_educator(teacher: dict) -> bool:
    role = (teacher.get("role") or "").lower()
    dept = (teacher.get("department") or "").lower()
    bio  = (teacher.get("bio") or "").lower()
    combined = f"{role} {dept} {bio}"

    educator_terms = [
        "teacher", "educator", "faculty", "instructor", "professor",
        "specialist", "coach", "counselor", "administrator", "librarian",
        "nurse", "aide", "paraprofessional", "secretary", "principal",
        "superintendent", "coordinator", "director",
    ]
    if any(t in combined for t in educator_terms):
        return True
    if teacher.get("email") or teacher.get("phone"):
        return True
    src = (teacher.get("source_url") or "").lower()
    if any(k in src for k in ["staff", "faculty", "directory", "teacher"]):
        return True
    return False


def role_filter(teachers: list[dict], all_roles: bool = False) -> list[dict]:
    if all_roles:
        return [t for t in teachers if is_any_educator(t)]
    return [t for t in teachers if is_stem_subject(t)]


def deduplicate(teachers: list[dict]) -> list[dict]:
    seen: dict[str, dict] = {}
    for t in teachers:
        name = (t.get("name") or "").strip()
        if not name:
            continue
        key = re.sub(r"[^a-z ]", "", name.lower()).strip()
        if not key:
            continue
        if key in seen:
            existing = seen[key]
            for field in ["email", "role", "department", "phone",
                           "linkedin_url", "bio", "source_url",
                           "page_subject_hint"]:
                if not existing.get(field) and t.get(field):
                    existing[field] = t[field]
        else:
            seen[key] = dict(t)
    return list(seen.values())


deduplicate_teachers = deduplicate


def assign_emails(
    teachers: list[dict],
    page_emails: dict[str, list[str]],
) -> list[dict]:
    all_e: set[str] = set()
    for lst in page_emails.values():
        all_e.update(e.lower() for e in lst)

    taken  = {t["email"].lower() for t in teachers if t.get("email")}
    pool   = all_e - taken

    if not pool:
        return teachers

    for t in teachers:
        if t.get("email"):
            continue
        name  = (t.get("name") or "").lower()
        parts = name.split()
        if len(parts) < 2:
            continue
        first = re.sub(r"[^a-z]", "", parts[0])
        last  = re.sub(r"[^a-z]", "", parts[-1])
        if not first or not last:
            continue
        for email in list(pool):
            local = email.split("@")[0]
            if (
                (first in local and last in local) or
                f"{first[0]}{last}" == local or
                f"{first}.{last}" == local or
                f"{first}{last}" == local or
                f"{first}_{last}" == local or
                f"{first[0]}.{last}" == local
            ):
                t["email"]        = email
                t["email_status"] = "matched"
                pool.discard(email)
                break

    return teachers


merge_emails_with_teachers = assign_emails


def fill_missing_emails(
    teachers: list[dict],
    extra_emails: list[str] | None = None,
) -> list[dict]:
    known = list({
        *(t["email"] for t in teachers if t.get("email")),
        *(extra_emails or []),
    })
    info = infer_address_pattern(known)
    if not info:
        return teachers

    print(
        f"  [pipeline] Pattern: {info['pattern']}@{info['domain']}"
        f" ({info['confidence']})"
    )
    for t in teachers:
        if not t.get("email") and t.get("name"):
            addr = build_address_from_pattern(t["name"], info)
            if addr:
                t["email"]        = addr
                t["email_status"] = f"inferred-{info['confidence']}"

    return teachers


enrich_emails = fill_missing_emails


def _has_mx(domain: str) -> bool:
    if not HAS_DNS:
        return True
    try:
        return len(dns.resolver.resolve(domain, "MX")) > 0
    except Exception:
        return False


def _smtp_check(email: str, domain: str) -> str:
    if not HAS_DNS:
        return "unknown"
    try:
        mx = dns.resolver.resolve(domain, "MX")
        host = str(sorted(mx, key=lambda x: x.preference)[0].exchange).rstrip(".")
    except Exception:
        return "unknown"
    try:
        smtp = smtplib.SMTP(timeout=5)
        smtp.connect(host, 25)
        smtp.helo("verify.local")
        smtp.mail("verify@verify.local")
        code, _ = smtp.rcpt(email)
        smtp.quit()
        return "valid" if code == 250 else ("invalid" if code in (550, 552, 553) else "unknown")
    except (smtplib.SMTPException, socket.error, OSError):
        return "unknown"


def verify_addresses(teachers: list[dict]) -> list[dict]:
    mx_cache: dict[str, bool] = {}
    for t in teachers:
        email = t.get("email")
        if not email:
            t.setdefault("email_status", "missing")
            continue
        t.setdefault("email_status", "found")
        domain = email.split("@")[1] if "@" in email else ""
        if not domain:
            continue
        if domain not in mx_cache:
            mx_cache[domain] = _has_mx(domain)
        if not mx_cache[domain]:
            t["email_status"] = "bad-domain"
            continue
        if t["email_status"] == "inferred-high":
            r = _smtp_check(email, domain)
            if r == "valid":
                t["email_status"] = "verified"
            elif r == "invalid":
                t["email_status"] = "rejected"
    return teachers


verify_emails = verify_addresses


def run_pipeline(
    teachers: list[dict],
    school_info: dict,
    page_emails: dict[str, list[str]] | None = None,
    all_roles: bool = False,
    run_smtp: bool = True,
    progress_callback=None,
) -> list[dict]:
    filtered = role_filter(teachers, all_roles=all_roles)
    filtered = deduplicate(filtered)
    if page_emails:
        filtered = assign_emails(filtered, page_emails)
    extra = [e for lst in (page_emails or {}).values() for e in lst]
    filtered = fill_missing_emails(filtered, extra)
    if run_smtp:
        filtered = verify_addresses(filtered)
    else:
        for t in filtered:
            if t.get("email") and not t.get("email_status"):
                t["email_status"] = "found"
            elif not t.get("email"):
                t.setdefault("email_status", "missing")
    if progress_callback:
        progress_callback(len(filtered), len(filtered))
    return filtered


def enrich_all(
    teachers, school_info, page_emails=None,
    run_smtp=True, progress_callback=None,
):
    return run_pipeline(
        teachers, school_info,
        page_emails=page_emails,
        all_roles=False,
        run_smtp=run_smtp,
        progress_callback=progress_callback,
    )
