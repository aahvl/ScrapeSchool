from __future__ import annotations

import csv
import os
import re
from datetime import datetime


FIELDS = [
    "name",
    "email",
    "email_status",
    "role",
    "department",
    "phone",
    "bio",
    "school_name",
    "school_address",
    "school_city",
    "school_state",
    "school_zip",
    "school_phone",
    "source_url",
]


def _last_name(teacher: dict) -> str:
    name = (teacher.get("name") or "").strip()
    parts = name.split()
    return parts[-1].lower() if parts else ""


_STEM_BROAD = {
    "stem", "steam", "engineering", "computer science", "robotics",
    "coding", "programming", "information technology", "tech ed",
    "data science", "biomedical", "makerspace", "cyber",
    "digital learning", "design technology", "technology",
}
_SCIENCE = {
    "science", "biology", "chemistry", "physics", "earth science",
    "environmental science", "life science", "physical science",
    "anatomy", "physiology", "ecology", "geology", "astronomy",
    "marine biology", "forensic science", "zoology", "botany",
}
_MATH = {
    "math", "mathematics", "algebra", "geometry", "calculus",
    "trigonometry", "statistics", "pre-calculus", "precalculus",
    "pre-algebra",
}


def _subject_rank(teacher: dict) -> int:
    role = (teacher.get("role") or "").lower()
    dept = (teacher.get("department") or "").lower()
    combined = f"{role} {dept}"

    def _hit(keywords):
        return any(
            re.search(rf"(?<![a-z0-9]){re.escape(k)}(?![a-z0-9])", combined)
            for k in keywords
        )

    if _hit(_STEM_BROAD):
        return 0
    if _hit(_SCIENCE):
        return 1
    if _hit(_MATH):
        return 2
    return 3


def _sort_key(teacher: dict) -> tuple:
    school = (teacher.get("school_name") or teacher.get("_school_name") or "").lower()
    return (school, _subject_rank(teacher), _last_name(teacher))


def organised(teachers: list[dict]) -> list[dict]:
    return sorted(teachers, key=_sort_key)


def export_csv(
    teachers: list[dict],
    school_info: dict,
    output_file: str,
    organise: bool = True,
) -> str:
    s = school_info

    rows = []
    for t in teachers:
        rows.append({
            "name":           t.get("name", ""),
            "email":          t.get("email", ""),
            "email_status":   t.get("email_status", "unknown"),
            "role":           t.get("role", ""),
            "department":     t.get("department", ""),
            "phone":          t.get("phone", ""),
            "bio":            t.get("bio", ""),
            "school_name":    t.get("_school_name") or s.get("school_name", ""),
            "school_address": t.get("_school_address") or s.get("address", ""),
            "school_city":    t.get("_school_city") or s.get("city", ""),
            "school_state":   t.get("_school_state") or s.get("state", ""),
            "school_zip":     t.get("_school_zip") or s.get("zip", ""),
            "school_phone":   t.get("_school_phone") or s.get("phone", ""),
            "source_url":     t.get("source_url", ""),
        })

    if organise:
        rows.sort(key=lambda r: (
            r.get("school_name", "").lower(),
            _subject_rank(r),
            r.get("name", "").split()[-1].lower() if r.get("name") else "",
        ))

    with open(output_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    return os.path.abspath(output_file)


def default_output_name(domain: str, prefix: str = "stem_teachers") -> str:
    ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe = domain.replace(".", "_").replace("/", "_")
    return f"{prefix}_{safe}_{ts}.csv"
