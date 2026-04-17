# ScrapeSchool

Pull STEM teacher contacts from any school website and drop them into a CSV. Give it a URL, it figures out where the staff directory is, reads every page of it, and hands you names, emails, roles, and addresses.

Works on JavaScript-heavy sites (runs a real Chrome browser under the hood). Skips pages that the site's robots.txt says not to visit.

---

## Setup

You'll need Python 3.11+ and a free Hack Club AI key.

```bash
pip install -r requirements.txt
playwright install chromium
```

Copy `.env.example` to `.env` and drop your key in:

```
HACKCLUB_AI_KEY=your_key_here
```

Get a key at **https://ai.hackclub.com** — it's free.

---

## Basic usage

```bash
python main.py https://www.schoolwebsite.org
```

That's it. It'll find the staff directory, extract science/math/STEM teachers, and save a CSV next to `main.py`.

---

## Flags

```
python main.py [URL ...] [OPTIONS]
```

| Flag | What it does |
|---|---|
| `--output`, `-o` | Set the output CSV path (default: auto-named with timestamp) |
| `--allroles` | Grab every staff member, not just STEM teachers |
| `--no-organise` | Don't sort the CSV — keep records in crawl order |
| `--max-pages` | Cap on staff pages crawled per site (default: 30) |
| `--timeout` | Browser timeout per page in seconds (default: 15) |
| `--no-smtp` | Skip SMTP email verification (faster, slightly less accurate) |
| `--verbose`, `-v` | Show detailed crawl output |
| `--file`, `-f` | Text file with one URL per line (for bulk runs) |

### Examples

```bash
# Just STEM teachers, default everything
python main.py https://www.cvsdvt.org/

# All staff, skipping SMTP (fast)
python main.py https://www.cvsdvt.org/ --allroles --no-smtp

# Custom output path
python main.py https://www.cvsdvt.org/ -o cvsd_teachers.csv

# Give slow sites more time
python main.py https://www.bigdistrict.edu/ --timeout 60 --max-pages 50

# Scrape multiple schools at once from a file
python main.py --file schools.txt -o all_schools.csv

# Or pass multiple URLs directly
python main.py https://school1.edu https://school2.edu
```

---

## What you get in the CSV

| Column | Description |
|---|---|
| `name` | Full name |
| `email` | Email address |
| `email_status` | `found` / `matched` / `inferred-high` / `missing` / `bad-domain` etc. |
| `role` | Job title |
| `department` | Subject or department |
| `phone` | Direct phone number |
| `bio` | Short bio if found on the page |
| `school_name` | Name of the school |
| `school_address` | Street address |
| `school_city` | City |
| `school_state` | State abbreviation |
| `school_zip` | ZIP code |
| `school_phone` | Main school phone number |
| `source_url` | The page the record came from |

By default the CSV is sorted by school name, then alphabetically by last name within each school. Use `--no-organise` to turn this off.

---

## How it works

1. Loads the school's homepage in a real Chrome browser
2. Scores every link on the page to find staff directories
3. Falls back to scanning `sitemap.xml` and probing common paths like `/staff`, `/faculty`, `/directory`
4. Reads every page of a paginated directory (handles `?page=2` style and click-based pagination)
5. Extracts records using three strategies in order: labeled-row parsing, regex scanning, then AI (Hack Club's Qwen model)
6. Fills missing emails by inferring the school's address pattern from the ones it did find
7. Verifies emails against DNS and optionally SMTP

---

## Tips

- **No results?** Try `--verbose` to see what the crawler is doing, and `--timeout 60` if the site is slow.
- **Only got a few?** Add `--max-pages 50` to crawl deeper into the directory.
- **All staff needed?** Pass `--allroles` — this includes admin, counselors, librarians, etc.
- **Running many schools?** Put URLs in a text file and use `--file schools.txt`.

---

## Project files

```
main.py          CLI and UI
crawler.py       Discovers and visits staff pages
extractor.py     Pulls names, emails, roles from HTML
pipeline.py      Filters, deduplicates, enriches, and verifies records
contacts.py      Email extraction and pattern inference
exporter.py      CSV writer with sorting
robots_guard.py  robots.txt compliance
config.py        Settings and constants
```
