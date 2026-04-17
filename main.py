from __future__ import annotations

import io
import sys

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import traceback
import urllib.parse
from pathlib import Path
from typing import Optional

import typer
from rich.align import Align
from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.rule import Rule
from rich.table import Table
from rich.text import Text
from rich.theme import Theme

import config
from crawler import crawl_and_extract
from exporter import default_output_name, export_csv
from pipeline import run_pipeline, deduplicate

THEME = Theme({
    "title":      "bold bright_cyan",
    "step":       "bold yellow",
    "step.done":  "bold green",
    "step.err":   "bold red",
    "info":       "dim white",
    "highlight":  "bold magenta",
    "url":        "underline bright_blue",
    "ok":         "bold green",
    "warn":       "bold yellow",
    "err":        "bold red",
    "count":      "bold bright_white",
})
console = Console(theme=THEME, highlight=False)
app = typer.Typer(add_completion=False, rich_markup_mode="rich")

BANNER = (
    " ___                           ___      _                    _\n"
    "/ __| __ _ _ __ _ _ __  ___  / __| ___| |_  ___  ___  _   | |\n"
    r"\__ \/ _| '_/ _` | '_ \/ -_) \__ \/ __| ' \/ _ \/ _ \| |  |_|" + "\n"
    r"|___/\__|_| \__,_| .__/\___| |___/\___|_||_\___/\___/|_|  (_)" + "\n"
    "                  |_|\n"
)


def _banner():
    console.print()
    console.print(Panel(
        Align.center(
            Text(BANNER, style="bold bright_cyan", justify="center")
            + Text(
                "\n  STEM Teacher Extractor  *  Hack Club AI  *  Playwright\n",
                style="dim cyan", justify="center",
            )
        ),
        border_style="bright_cyan", padding=(0, 4),
    ))
    console.print()


def _step(n, t, label):
    console.print(f"  [step]*[/step] [bold white]Step {n}/{t}[/bold white]  {label}")

def _done(msg):  console.print(f"       [step.done]v[/step.done]  {msg}")
def _warn(msg):  console.print(f"       [warn]![/warn]  {msg}")
def _err(msg):   console.print(f"       [step.err]x[/step.err]  {msg}")
def _info(msg):  console.print(f"         [info]{msg}[/info]")


STATUS_STYLE = {
    "found":           "[ok]found[/ok]",
    "matched":         "[ok]matched[/ok]",
    "verified":        "[ok]verified[/ok]",
    "valid_format":    "[ok]valid[/ok]",
    "inferred-high":   "[warn]inf-high[/warn]",
    "inferred-medium": "[warn]inf-med[/warn]",
    "inferred-low":    "[warn]inf-low[/warn]",
    "bad-domain":      "[err]bad-domain[/err]",
    "rejected":        "[err]rejected[/err]",
    "invalid_format":  "[err]invalid[/err]",
    "missing":         "[info]missing[/info]",
    "unknown":         "[info]unknown[/info]",
}


def _table(teachers, title="Results"):
    t = Table(
        title=f"[bold bright_cyan]{title}[/bold bright_cyan]",
        border_style="bright_cyan", header_style="bold magenta",
        show_lines=True, expand=True,
    )
    t.add_column("#",         style="dim",         width=3,   no_wrap=True)
    t.add_column("Name",      style="bold white",  min_width=20)
    t.add_column("Role/Dept", style="cyan",         min_width=22)
    t.add_column("Email",     style="bright_blue", min_width=28)
    t.add_column("Status",    style="dim",          width=13)
    t.add_column("School",    style="dim white",    min_width=18)

    for i, r in enumerate(teachers, 1):
        dept   = r.get("department", "")
        role   = r.get("role", "")
        rd     = " / ".join(filter(None, [role, dept])) or "-"
        email  = r.get("email") or "-"
        status = r.get("email_status", "unknown")
        school = r.get("_school_name") or "-"
        t.add_row(
            str(i),
            r.get("name", "-"),
            rd, email,
            STATUS_STYLE.get(status, f"[info]{status}[/info]"),
            school,
        )
    return t


def _stamp_school(teachers, school_info):
    for t in teachers:
        t["_school_name"]    = school_info.get("school_name", "")
        t["_school_address"] = school_info.get("address", "")
        t["_school_city"]    = school_info.get("city", "")
        t["_school_state"]   = school_info.get("state", "")
        t["_school_zip"]     = school_info.get("zip", "")
        t["_school_phone"]   = school_info.get("phone", "")
    return teachers


def _scrape(url, max_pages, timeout, all_roles, no_smtp, verbose, progress_cb=None):
    raw, school_info, page_emails = crawl_and_extract(
        start_url=url,
        max_pages=max_pages,
        page_timeout=timeout * 1000,
        verbose=verbose,
        progress_callback=progress_cb,
    )
    processed = run_pipeline(
        raw, school_info,
        page_emails=page_emails,
        all_roles=all_roles,
        run_smtp=not no_smtp,
    )
    _stamp_school(processed, school_info)
    return processed, school_info


@app.command()
def main(
    urls: list[str] = typer.Argument(
        default=None, help="School website URLs to scrape.",
    ),
    file: Optional[Path] = typer.Option(
        None, "--file", "-f", help="Text file with one URL per line.",
    ),
    output: Optional[str] = typer.Option(
        None, "--output", "-o", help="Output CSV path (default: auto-named).",
    ),
    allroles: bool = typer.Option(
        False, "--allroles",
        help="Export every staff member, not just science/math/STEM teachers.",
    ),
    no_organise: bool = typer.Option(
        False, "--no-organise",
        help="Skip alphabetical sorting by school and name.",
    ),
    max_pages: int = typer.Option(
        config.MAX_PAGES, "--max-pages",
        help="Max staff pages to crawl per URL.",
    ),
    timeout: int = typer.Option(
        config.PAGE_TIMEOUT // 1000, "--timeout",
        help="Per-page browser timeout in seconds.",
    ),
    no_smtp: bool = typer.Option(
        False, "--no-smtp", help="Skip SMTP email verification.",
    ),
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="Show detailed crawl output.",
    ),
) -> None:
    """
    [bold bright_cyan]ScrapeSchool[/bold bright_cyan] —
    Pull STEM teacher contacts from any school website.

    Finds science, math, and STEM teachers by default.
    Use [bold]--allroles[/bold] to grab every staff member instead.
    Results are sorted by school then alphabetically — use [bold]--no-organise[/bold] to skip.
    """
    _banner()

    target_urls = list(urls or [])
    if file:
        try:
            target_urls += [
                l.strip() for l in file.read_text().splitlines()
                if l.strip() and not l.startswith("#")
            ]
        except Exception as exc:
            _err(f"Can't read {file}: {exc}")
            raise typer.Exit(1)

    if not target_urls:
        _err("No URLs given. Pass at least one URL, or use --file.")
        raise typer.Exit(1)

    target_urls = [
        u if u.startswith(("http://", "https://")) else f"https://{u}"
        for u in target_urls
    ]

    if not config.AI_API_KEY or config.AI_API_KEY in ("", "your_api_key_here"):
        _warn("HACKCLUB_AI_KEY not set — AI extraction will be limited.")
        _info("Add it to .env: HACKCLUB_AI_KEY=your_key_here")
        console.print()

    mode = "all staff" if allroles else "STEM only"
    sort = "unsorted" if no_organise else "sorted by school + name"
    _info(f"Mode: [bold]{mode}[/bold] · {sort}")
    console.print()

    all_teachers: list[dict] = []
    combined_school: dict    = {}

    for idx, url in enumerate(target_urls):
        domain = urllib.parse.urlparse(url).netloc or url

        console.print(Rule(
            f"[bold bright_cyan]({idx+1}/{len(target_urls)}) {domain}[/bold bright_cyan]"
        ))
        console.print(f"  [info]URL  :[/info] [url]{url}[/url]")
        console.print(f"  [info]Model:[/info] [highlight]{config.AI_MODEL}[/highlight]")
        console.print()

        _step(1, 2, ("Crawling + extracting" + (" (all roles)" if allroles else " (STEM only)")) + " ...")

        processed: list[dict] = []
        school_info: dict     = {}

        with Progress(
            SpinnerColumn(spinner_name="dots2", style="bright_cyan"),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(bar_width=24, style="bright_cyan", complete_style="green"),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            console=console, expand=True,
        ) as prog:
            task = prog.add_task("Crawling ...", total=max_pages)

            def cb(done, total):
                prog.update(task, completed=done, total=total,
                            description=f"Crawling {done}/{total} ...")

            try:
                processed, school_info = _scrape(
                    url, max_pages, timeout, allroles,
                    no_smtp, verbose, cb,
                )
            except Exception as exc:
                _err(f"Failed: {exc}")
                if verbose:
                    traceback.print_exc()
                continue

        school_name  = school_info.get("school_name") or domain
        result_label = "staff" if allroles else "STEM teacher(s)"
        _done(
            f"School : [highlight]{school_name}[/highlight]  "
            f"([count]{len(processed)}[/count] {result_label} found)"
        )
        if school_info.get("address"):
            _info(
                f"Address: {school_info.get('address')}, "
                f"{school_info.get('city')}, "
                f"{school_info.get('state')} "
                f"{school_info.get('zip', '')}".strip()
            )

        if not processed:
            _warn(f"No {result_label} found for this URL.")
            _info("Try: --max-pages 20  --timeout 60  --verbose  --no-smtp")
            console.print()
            continue

        all_teachers.extend(processed)
        if not combined_school:
            combined_school = school_info

        console.print()

    if not all_teachers:
        _warn("Nothing to export.")
        raise typer.Exit(0)

    _step(2, 2, "Saving CSV ...")
    domain_tag = urllib.parse.urlparse(target_urls[0]).netloc
    prefix     = "staff" if allroles else "stem_teachers"
    out_file   = output or default_output_name(domain_tag, prefix=prefix)

    abs_path = export_csv(
        all_teachers, combined_school, out_file,
        organise=not no_organise,
    )
    _done(f"Saved to [url]{abs_path}[/url]")

    title = "All Staff" if allroles else "STEM Teachers"
    console.print()
    console.print(Rule("[bold green]Results[/bold green]"))
    console.print()
    console.print(_table(all_teachers, title))

    record_label = "staff record(s)" if allroles else "STEM teacher(s)"
    console.print()
    console.print(Panel(
        f"[ok]Done! Exported [count]{len(all_teachers)}[/count] {record_label}[/ok]\n"
        f"[info]   File: [url]{abs_path}[/url][/info]",
        border_style="green", title="[bold green]Done[/bold green]",
        padding=(1, 4),
    ))
    console.print()


if __name__ == "__main__":
    app()
