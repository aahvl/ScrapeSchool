from pipeline import (
    is_stem_subject as is_stem_teacher,
    is_any_educator,
    role_filter,
    deduplicate as deduplicate_teachers,
    assign_emails as merge_emails_with_teachers,
    fill_missing_emails as enrich_emails,
    verify_addresses as verify_emails,
    run_pipeline,
    enrich_all,
)

def find_linkedin(name: str = "", school_name: str = "", delay: float = 1.5) -> str:
    return ""

__all__ = [
    "is_stem_teacher", "is_any_educator", "role_filter",
    "deduplicate_teachers", "merge_emails_with_teachers",
    "enrich_emails", "verify_emails", "find_linkedin",
    "run_pipeline", "enrich_all",
]
