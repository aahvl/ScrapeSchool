from extractor import (
    parse_staff_from_html,
    extract_school_info,
    extract_school_info as extract_school_address,
    detect_page_subject as detect_subject_hint,
    strip_page_noise as clean_html,
    split_into_chunks as chunk_text,
)
__all__ = [
    "parse_staff_from_html",
    "extract_school_info",
    "extract_school_address",
    "detect_subject_hint",
    "clean_html",
    "chunk_text",
]
