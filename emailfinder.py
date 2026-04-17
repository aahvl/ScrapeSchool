from contacts import (
    collect_emails_from_html as extract_emails_from_html,
    collect_emails_from_text as extract_emails_from_text,
    infer_address_pattern as infer_email_pattern,
    build_address_from_pattern as generate_email_from_pattern,
)
__all__ = [
    "extract_emails_from_html",
    "extract_emails_from_text",
    "infer_email_pattern",
    "generate_email_from_pattern",
]
