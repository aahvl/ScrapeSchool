from __future__ import annotations

import base64
import re

import config


def collect_emails_from_html(html: str) -> list[str]:
    found: set[str] = set()

    found.update(re.findall(
        r'mailto:([a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})',
        html, re.IGNORECASE,
    ))

    for encoded in re.findall(r'data-cfemail="([a-fA-F0-9]+)"', html):
        decoded = _cf_decode(encoded)
        if decoded:
            found.add(decoded)

    deobf = html
    for pattern, replacement in config.EMAIL_DEOBFUSCATION:
        deobf = re.sub(pattern, replacement, deobf, flags=re.IGNORECASE)
    found.update(re.findall(config.EMAIL_REGEX, deobf))

    for b64 in re.findall(
        r'(?:atob|decode)\s*\(\s*["\']([A-Za-z0-9+/=]+)["\']\s*\)',
        html,
    ):
        try:
            raw = base64.b64decode(b64).decode("utf-8", errors="ignore")
            found.update(re.findall(config.EMAIL_REGEX, raw))
        except Exception:
            pass

    return _clean(found)


def collect_emails_from_text(text: str) -> list[str]:
    for pattern, replacement in config.EMAIL_DEOBFUSCATION:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return _clean(set(re.findall(config.EMAIL_REGEX, text)))


def _cf_decode(encoded: str) -> str | None:
    try:
        key = int(encoded[:2], 16)
        result = "".join(
            chr(int(encoded[i: i + 2], 16) ^ key)
            for i in range(2, len(encoded), 2)
        )
        return result.lower() if re.match(config.EMAIL_REGEX, result) else None
    except Exception:
        return None


_BAD_SUFFIXES = (
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".css",
    ".js", ".pdf", ".doc", ".ico", ".webp",
)


def _clean(emails: set[str]) -> list[str]:
    out: set[str] = set()
    for e in emails:
        e = e.lower().strip().rstrip(".")
        if not e.endswith(_BAD_SUFFIXES):
            out.add(e)
    return sorted(out)


def infer_address_pattern(known_emails: list[str]) -> dict | None:
    if not known_emails:
        return None

    by_domain: dict[str, list[str]] = {}
    for email in known_emails:
        parts = email.split("@")
        if len(parts) == 2:
            by_domain.setdefault(parts[1], []).append(parts[0])

    if not by_domain:
        return None

    domain = max(by_domain, key=lambda d: len(by_domain[d]))
    locals_ = by_domain[domain]

    if len(locals_) < 2:
        return {"pattern": "unknown", "domain": domain, "confidence": "low"}

    has_dot = sum(1 for l in locals_ if "." in l)
    has_underscore = sum(1 for l in locals_ if "_" in l)
    avg_len = sum(len(l) for l in locals_) / len(locals_)

    if has_dot > len(locals_) * 0.5:
        pattern, confidence = "first.last", "high"
    elif has_underscore > len(locals_) * 0.5:
        pattern, confidence = "first_last", "high"
    elif avg_len < 8:
        pattern, confidence = "flast", "medium"
    else:
        pattern, confidence = "firstlast", "medium"

    return {"pattern": pattern, "domain": domain, "confidence": confidence}


infer_email_pattern = infer_address_pattern


def build_address_from_pattern(name: str, pattern_info: dict) -> str | None:
    if not name or not pattern_info:
        return None

    parts = name.strip().split()
    if len(parts) < 2:
        return None

    first = re.sub(r"[^a-z]", "", parts[0].lower())
    last  = re.sub(r"[^a-z]", "", parts[-1].lower())
    domain  = pattern_info["domain"]
    pattern = pattern_info["pattern"]

    if not first or not last:
        return None

    mapping = {
        "first.last":  f"{first}.{last}@{domain}",
        "first_last":  f"{first}_{last}@{domain}",
        "flast":       f"{first[0]}{last}@{domain}",
        "firstlast":   f"{first}{last}@{domain}",
        "first.l":     f"{first}.{last[0]}@{domain}",
        "f.last":      f"{first[0]}.{last}@{domain}",
    }
    return mapping.get(pattern, f"{first}.{last}@{domain}")


generate_email_from_pattern = build_address_from_pattern
