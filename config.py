import os
import sys
from dotenv import load_dotenv

load_dotenv()

sys.stdout.reconfigure(line_buffering=True)

AI_BASE_URL = "https://ai.hackclub.com/proxy/v1"
AI_API_KEY = os.getenv("HACKCLUB_AI_KEY", "")
AI_MODEL = "qwen/qwen3-32b"

MAX_CRAWL_DEPTH = 2
MAX_PAGES = 30
PAGE_TIMEOUT = 12000
JS_WAIT = 600
PAGINATION_WAIT = 500
CRAWL_DELAY = 0.1
MIN_LINK_SCORE = 8
SECONDARY_LINK_SCORE = 6
MAX_STAFF_LINK_CHECKS = 8
MAX_DISCOVERY_VISITS = 10
MAX_SITEMAP_FETCHES = 4
CONCURRENT_PAGES = 2
GOOGLE_RENDER_WAIT = 800
GOOGLE_QUERY_DELAY = 0.5

STAFF_URL_PATTERNS = [
    "/staff", "/faculty", "/directory", "/teachers",
    "/our-staff", "/our-team", "/staff-directory",
    "/about/staff", "/about/faculty",
    "/faculty-staff", "/faculty-and-staff",
    "/staff-directory/home", "/staff-directory/search",
    "/staff-search", "/people", "/directory/staff",
    "/employees/staff-directory",
    "/about-us/staff", "/about-us/faculty", "/about-us/directory",
    "/about-us/contact-us", "/about-us/our-team",
    "/about/contact", "/about/contact-us",
    "/district/staff-directory", "/schools/staff-directory",
    "/administration/staff-directory",
    "/district/directory", "/district/staff",
    "/apps/pages/staff-directory",
    "/site/default.aspx?pagetype=2",
    "/site/default.aspx?pagetype=15",
    "/schools", "/our-schools",
    "/departments/science", "/departments/math", "/departments/stem",
    "/departments/technology", "/departments/mathematics",
    "/departments/computer-science", "/departments/engineering",
    "/academics/science", "/academics/math", "/academics/departments",
    "/curriculum/math", "/curriculum/science", "/curriculum/stem",
    "/learning/math", "/learning/science", "/learning/stem",
    "/learning/curriculum",
    "/contact", "/contact-us", "/contacts",
    "/administration", "/admin",
]

STAFF_LINK_POSITIVE_HINTS = [
    "staff", "faculty", "directory", "teacher", "teachers",
    "employee", "employees", "people", "contact",
]

STAFF_LINK_NEGATIVE_HINTS = [
    "calendar", "news", "event", "lunch", "menu", "bus",
    "parent", "student", "enrollment", "registration",
    "login", "donate", "careers", "jobs", "apply", "employment",
    "twitter", "facebook", "instagram", "youtube", "athletics",
    "board", "trustees", "policy", "procurement", "resources",
    ".pdf", ".doc", "mailto:", "tel:", "javascript:",
]

STEM_KEYWORDS = [
    "math", "mathematics", "algebra", "geometry", "calculus",
    "trigonometry", "statistics", "pre-calculus", "precalculus",
    "ap calculus", "ap statistics", "pre-algebra",
    "science", "biology", "chemistry", "physics",
    "earth science", "environmental science", "life science",
    "physical science", "ap biology", "ap chemistry", "ap physics",
    "anatomy", "physiology", "ecology", "geology", "astronomy",
    "marine biology", "forensic science", "zoology", "botany",
    "stem", "steam", "engineering", "computer science",
    "robotics", "technology", "coding", "programming",
    "information technology", "computer", "tech ed",
    "data science", "cyber", "biomedical", "digital learning",
    "instructional technology", "design technology", "makerspace",
]

EMAIL_REGEX = r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}'

EMAIL_DEOBFUSCATION = [
    (r'\s*\[\s*at\s*\]\s*', '@'),
    (r'\s*\(\s*at\s*\)\s*', '@'),
    (r'\s+at\s+', '@'),
    (r'\s*\[\s*dot\s*\]\s*', '.'),
    (r'\s*\(\s*dot\s*\)\s*', '.'),
    (r'\s+dot\s+', '.'),
]

HTML_CHUNK_SIZE = 10000

STAFF_EXTRACTION_PROMPT = """You are an expert at extracting structured data from school website content.
Extract ALL staff members, teachers, and faculty from the following content.

Return a JSON array where each element has these fields:
- "name": full name (string, required)
- "email": email address (string or null)
- "role": job title/position (string or null)
- "department": department or subject area (string or null)
- "phone": phone number (string or null)

Rules:
- Include EVERY person mentioned who appears to be staff/faculty/teacher
- Do NOT include students, parents, or non-staff
- If you see a department heading (like "Science Department"), apply that department to all people listed under it
- If you see subject area context (like a page about "Math"), tag people with that department
- Extract emails even if partially obfuscated
- Return ONLY valid JSON array, no markdown fences, no explanation, no extra text
- If no staff found, return: []"""

SCHOOL_ADDRESS_PROMPT = """Extract the school's name and mailing address from the following content.
This is a US school.

Return a JSON object with:
- "school_name": name of the school (string)
- "address": street address (string or null)
- "city": city (string or null)
- "state": US state abbreviation (string or null)
- "zip": zip code (string or null)
- "phone": main phone number (string or null)

Return ONLY valid JSON object, no markdown fences, no explanation, no extra text.
If you cannot find an address, still return the object with null values."""
