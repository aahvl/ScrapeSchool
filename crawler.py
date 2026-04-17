from __future__ import annotations

import asyncio
import re
from collections import deque
from urllib.parse import urljoin, urlparse, urlunparse, parse_qsl, urlencode

from playwright.async_api import async_playwright, Browser, BrowserContext, Page

import config
import robots_guard
from contacts import collect_emails_from_html
from extractor import parse_staff_from_html, extract_school_info


async def start_browser():
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=True)
    return pw, browser


async def stop_browser(pw, browser: Browser) -> None:
    await browser.close()
    await pw.stop()


async def _new_context(browser: Browser) -> BrowserContext:
    return await browser.new_context(
        user_agent=robots_guard.UA,
        viewport={"width": 1280, "height": 900},
    )


async def open_page(browser: Browser) -> Page:
    ctx = await _new_context(browser)
    return await ctx.new_page()


class PagePool:
    def __init__(self, browser: Browser, size: int = 4):
        self._browser = browser
        self._sem = asyncio.Semaphore(size)
        self._pages: list[Page] = []
        self._lock = asyncio.Lock()

    async def _get(self) -> Page:
        async with self._lock:
            if self._pages:
                return self._pages.pop()
        ctx = await _new_context(self._browser)
        return await ctx.new_page()

    async def _put(self, page: Page) -> None:
        async with self._lock:
            self._pages.append(page)

    async def fetch(self, url: str, *, quiet: bool = True,
                    extra_wait: int | None = None) -> dict | None:
        async with self._sem:
            page = await self._get()
            try:
                result = await load_page(page, url, quiet=quiet,
                                         extra_wait=extra_wait)
                return result
            except Exception:
                return None
            finally:
                try:
                    await self._put(page)
                except Exception:
                    pass

    async def close_all(self) -> None:
        async with self._lock:
            for p in self._pages:
                try:
                    await p.context.close()
                except Exception:
                    pass
            self._pages.clear()


async def load_page(page: Page, url: str, *, quiet: bool = False,
                    extra_wait: int | None = None) -> dict | None:
    try:
        if not quiet:
            print(f"    [fetch] {url}")
        resp = await page.goto(url, wait_until="domcontentloaded",
                               timeout=config.PAGE_TIMEOUT)
        if not resp or resp.status >= 400:
            return None
        await page.wait_for_timeout(extra_wait or config.JS_WAIT)
        html = await page.content()
        text = await page.inner_text("body")
        return {"html": html, "text": text, "url": url}
    except Exception as exc:
        if not quiet:
            print(f"    [fetch] ERR {exc}")
        return None


_STRONG = [
    "staff directory", "faculty directory", "our staff", "our faculty",
    "staff list", "faculty & staff", "faculty and staff",
    "meet our staff", "meet our teachers",
]
_CONTROLS = [
    "search staff", "staff search", "first name", "last name",
    "all locations", "all departments", "filter by", "directory results",
]
_NEGATIVE = [
    "how to", "help guide", "teacher help", "acceptable use",
    "powerteacher", "powerschool", "schoolmessenger",
    "grading", "scoresheet", "technology support",
]


def _is_staff_page(text: str, url: str = "") -> bool:
    tl, ul = text.lower(), url.lower()
    has_strong     = any(s in tl for s in _STRONG)
    has_strong_url = any(k in ul for k in
                         ["staff", "faculty", "directory", "staffsearch",
                          "staff-search", "teacher", "contact-us",
                          "departments", "curriculum"])
    weak     = sum(1 for k in ["teacher", "staff", "faculty", "instructor",
                                "educator"] if k in tl)
    ctrl     = sum(1 for k in _CONTROLS if k in tl)
    neg      = sum(1 for k in _NEGATIVE if k in tl)
    email_ct = len(re.findall(config.EMAIL_REGEX, text))
    phone_ct = len(re.findall(r"[\(]?\d{3}[\)]?[\s\-\.]\d{3}[\s\-\.]\d{4}", text))
    name_ct  = len(re.findall(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z'\-]+){1,2}\b",
                              text[:120_000]))

    if has_strong and (email_ct >= 1 or phone_ct >= 2 or name_ct >= 8):
        return True
    if ctrl >= 2 and (name_ct >= 6 or email_ct >= 2):
        return True
    if has_strong_url and weak >= 1 and (
            email_ct >= 2 or phone_ct >= 2 or name_ct >= 10):
        return True
    if has_strong_url and (email_ct >= 3 or (email_ct >= 1 and phone_ct >= 2)):
        return True
    if neg >= 2 and not has_strong and ctrl == 0:
        return False
    return False


def _score_link(href: str, text: str) -> int:
    hl, tl = href.lower(), text.lower().strip()
    score = 0
    high = ["staff directory", "faculty directory", "our staff", "our faculty",
            "our team", "meet our", "staff list", "faculty & staff",
            "faculty and staff", "department contacts", "contact us"]
    for kw in high:
        if kw in tl:
            score += 15
    for kw in ["staff", "faculty", "directory", "teachers", "team"]:
        if kw == tl or kw in hl:
            score += 8
    for kw in config.STAFF_LINK_POSITIVE_HINTS:
        if kw in tl:
            score += 4
        if f"/{kw}" in hl:
            score += 4
    for kw in ["science", "math", "stem", "curriculum", "departments", "academics"]:
        if kw in tl or kw in hl:
            score += 5
    for p in config.STAFF_URL_PATTERNS:
        if p in hl:
            score += 8
    for kw in config.STAFF_LINK_NEGATIVE_HINTS:
        if kw in hl or kw in tl:
            score -= 15
    if len(tl.split()) >= 8:
        score -= 6
    if hl.endswith("/") and tl in {"home", "district home", ""}:
        score -= 20
    return score


def _norm(url: str) -> str:
    return (url or "").split("#")[0].strip().rstrip("/")


def _same_domain(url: str, domain: str) -> bool:
    try:
        lhs = urlparse(url).netloc.lower().removeprefix("www.")
        rhs = domain.lower().removeprefix("www.")
        return lhs == rhs
    except Exception:
        return False


def _staff_priority(url: str) -> int:
    lo = url.lower()
    s = 0
    if "staff-directory" in lo: s += 30
    if "/staff"          in lo: s += 25
    if "/faculty"        in lo: s += 20
    if "/directory"      in lo: s += 15
    if "staff-search" in lo or "staffsearch" in lo: s += 12
    if "/teacher"        in lo: s += 8
    if "/people"         in lo: s += 4
    return s


def _is_candidate(url: str) -> bool:
    lo = url.lower()
    bad = ["/documents/", "/doc/", "/files/", "/news/", "/events/",
           "/join-our-team", "/salary", "/employment", "/jobs",
           "/forms", "/handbook", "/policies", "/board", "/calendar"]
    if any(b in lo for b in bad):
        return False
    good = [
        "staff-directory", "staff-search", "staffsearch",
        "/directory", "/faculty", "/teachers", "/teacher",
        "/staff", "/people",
        "/departments", "/curriculum", "/academics",
        "/learning", "/contact-us", "/contacts",
        "/administration",
    ]
    return any(g in lo for g in good) or _staff_priority(url) >= 15


def _is_direct(url: str) -> bool:
    n = _norm(url)
    if not n:
        return False
    path = (urlparse(n).path or "").lower()
    return path not in ("", "/") and _staff_priority(n) >= 20 and _is_candidate(n)


def _is_hub(href: str, text: str) -> bool:
    combined = f"{href} {text}".lower()
    if any(b in combined for b in ["board", "calendar", "news", "jobs"]):
        return False
    return any(h in combined for h in
               ["about", "our schools", "schools", "academics",
                "departments", "staff", "faculty", "directory"])


async def _get_links(page: Page) -> list[dict]:
    try:
        return await page.evaluate("""() => {
            return Array.from(document.querySelectorAll('a[href]')).map(a => ({
                href: a.href,
                text: (a.innerText || '').trim().substring(0, 200)
            }));
        }""")
    except Exception:
        return []


async def _scan_sitemap(pool: PagePool, start_url: str, domain: str) -> list[str]:
    parsed = urlparse(start_url)
    base   = f"{parsed.scheme}://{parsed.netloc}"
    seeds  = [f"{base}/sitemap.xml", f"{base}/sitemap_index.xml",
              f"{base}/wp-sitemap.xml"]
    pending: deque[str] = deque(seeds)
    fetched: set[str] = set()
    found:   set[str] = set()

    while pending and len(fetched) < config.MAX_SITEMAP_FETCHES:
        sm = _norm(pending.popleft())
        if not sm or sm in fetched:
            continue
        fetched.add(sm)
        result = await pool.fetch(sm)
        if not result:
            continue
        for loc in re.findall(r"<loc>\s*([^<\s]+)\s*</loc>",
                              result["html"], re.I):
            n = _norm(loc)
            if not n or not _same_domain(n, domain):
                continue
            if ".xml" in n.lower() and "sitemap" in n.lower():
                if n not in fetched:
                    pending.append(n)
                continue
            if _is_candidate(n):
                found.add(n)

    return sorted(found, key=_staff_priority, reverse=True)[
        : config.MAX_STAFF_LINK_CHECKS
    ]


async def _check_candidates_parallel(
    pool: PagePool,
    candidates: list[tuple[int, str, str]],
    limit: int,
) -> list[str]:
    top = candidates[:limit]

    async def check_one(score: int, url: str, label: str) -> str | None:
        print(f"  [P1] [{score}] {label[:40]!r} → {url}")
        result = await pool.fetch(url)
        if result and _is_staff_page(result["text"], url):
            print(f"  [P1] FOUND: {url}")
            return url
        return None

    results = await asyncio.gather(
        *[check_one(s, u, t) for s, u, t in top],
        return_exceptions=True,
    )
    return [r for r in results if isinstance(r, str)]


async def _probe_patterns_parallel(
    pool: PagePool,
    base_url: str,
    skip: set[str],
) -> list[str]:
    urls = []
    for path in config.STAFF_URL_PATTERNS:
        test = _norm(base_url + path)
        if test not in skip:
            urls.append(test)

    async def probe(url: str) -> str | None:
        try:
            result = await pool.fetch(url)
            if result and _is_staff_page(result["text"], url):
                print(f"  [P4] FOUND: {url}")
                return url
        except Exception:
            pass
        return None

    results = await asyncio.gather(
        *[probe(u) for u in urls],
        return_exceptions=True,
    )
    found = [r for r in results if isinstance(r, str)]
    return sorted(found, key=_staff_priority, reverse=True)


async def discover_staff_pages(
    page: Page,
    browser: Browser,
    start_url: str,
) -> list[str]:
    pool = PagePool(browser, size=config.CONCURRENT_PAGES)
    parsed   = urlparse(start_url)
    domain   = parsed.netloc
    base_url = f"{parsed.scheme}://{parsed.netloc}"
    start_n  = _norm(start_url)

    found:     list[str] = []
    found_set: set[str]  = set()

    def add(url: str) -> None:
        n = _norm(url)
        if n and n not in found_set:
            found_set.add(n)
            found.append(n)

    try:
        print("  [P1] Scanning homepage links ...")
        content = await load_page(page, start_url, quiet=True)
        if content:
            if _is_staff_page(content["text"], start_url):
                add(start_url)
                if _is_direct(start_url):
                    return [start_n]

            links = await _get_links(page)
            scored: dict[str, tuple[int, str]] = {}
            for lk in links:
                href, text = lk.get("href", ""), lk.get("text", "")
                try:
                    if urlparse(href).netloc and not _same_domain(href, domain):
                        continue
                except Exception:
                    continue
                full = _norm(urljoin(start_url, href))
                if not full or full == start_n or not _is_candidate(full):
                    continue
                s = _score_link(href, text)
                if s >= config.MIN_LINK_SCORE:
                    if not scored.get(full) or s > scored[full][0]:
                        scored[full] = (s, text)

            top = sorted(
                [(s, u, t) for u, (s, t) in scored.items()],
                key=lambda x: x[0], reverse=True,
            )
            hits = await _check_candidates_parallel(
                pool, top, config.MAX_STAFF_LINK_CHECKS
            )
            for h in hits:
                add(h)
                if _is_direct(h):
                    return [_norm(h)]

        if not found:
            print("  [P2] BFS discovery ...")
            queue: deque[tuple[str, int]] = deque([(start_url, 0)])
            bfs_seen: set[str] = {start_n} | found_set
            visits = 0

            while queue and visits < config.MAX_DISCOVERY_VISITS:
                cur, depth = queue.popleft()
                cur = _norm(cur)
                if not cur or cur in found_set or not _same_domain(cur, domain):
                    continue

                visits += 1
                c = await load_page(page, cur, quiet=True)
                if not c:
                    continue

                if _is_staff_page(c["text"], cur) and _is_candidate(cur):
                    print(f"  [P2] FOUND: {cur}")
                    add(cur)

                if depth >= config.MAX_CRAWL_DEPTH:
                    continue

                for lk in await _get_links(page):
                    href, text = lk.get("href", ""), lk.get("text", "")
                    full = _norm(urljoin(cur, href))
                    if (not full or full in bfs_seen
                            or not _same_domain(full, domain)):
                        continue
                    s = _score_link(href, text)
                    if (s >= config.SECONDARY_LINK_SCORE and _is_candidate(full)) \
                            or (depth == 0 and _is_hub(href, text)):
                        bfs_seen.add(full)
                        queue.append((full, depth + 1))

        direct = sorted([u for u in found if _is_direct(u)],
                        key=_staff_priority, reverse=True)
        if direct:
            return [direct[0]]

        print("  [P3] Checking sitemaps ...")
        for u in await _scan_sitemap(pool, start_url, domain):
            add(u)

        print("  [P4] Probing common paths ...")
        for u in await _probe_patterns_parallel(pool, base_url, found_set):
            add(u)
            if _is_direct(u):
                return [u]

        if not found:
            print("  [P5] Fallback candidates ...")
            if content:
                fs: dict[str, int] = {}
                for lk in await _get_links(page):
                    href, text = lk.get("href", ""), lk.get("text", "")
                    full = _norm(urljoin(start_url, href))
                    if (full and _same_domain(full, domain)
                            and _is_candidate(full)):
                        s = _score_link(href, text)
                        if s >= config.MIN_LINK_SCORE:
                            fs[full] = max(s, fs.get(full, -999))
                for u, _ in sorted(fs.items(), key=lambda x: x[1],
                                   reverse=True)[:3]:
                    add(u)

    finally:
        await pool.close_all()

    return sorted(found, key=_staff_priority, reverse=True)[
        : config.MAX_STAFF_LINK_CHECKS
    ]


def _fp(text: str) -> tuple:
    n = re.sub(r"\s+", " ", text).strip().lower()
    return (len(n), hash(n))


def _page_url(base: str, param: str, n: int) -> str:
    p = urlparse(base)
    q = dict(parse_qsl(p.query, keep_blank_values=True))
    q[param] = str(n)
    return urlunparse((p.scheme, p.netloc, p.path, p.params,
                       urlencode(q), p.fragment))


async def _count_pages(page: Page) -> int:
    try:
        return await page.evaluate(
            "() => {"
            "  let m=1;"
            "  for(const a of document.querySelectorAll('a[href]')){"
            "    const h=a.href,t=(a.innerText||'').trim();"
            "    const mp=h.match(/[?&](?:page_no|const_page|page)=(\\d+)/);"
            "    if(mp){const n=parseInt(mp[1]);if(n>m)m=n;}"
            "    if(/^\\d+$/.test(t)){const n=parseInt(t);if(n>m&&n<200)m=n;}"
            "  } return m; }"
        )
    except Exception:
        return 1


async def _detect_param(page: Page) -> str | None:
    try:
        return await page.evaluate(
            "() => {"
            "  const c={const_page:0,page_no:0,page:0};"
            "  for(const a of document.querySelectorAll('a[href]')){"
            "    const h=a.getAttribute('href')||'';"
            "    for(const k of Object.keys(c)){"
            "      if(new RegExp(`[?&]${k}=\\\\d+`).test(h))c[k]++;}"
            "  }"
            "  const s=Object.entries(c).sort((a,b)=>b[1]-a[1]);"
            "  return s[0][1]>0?s[0][0]:null;}"
        )
    except Exception:
        return None


async def _click_page(page: Page, n: int) -> bool:
    for sel in [f'a[href*="const_page={n}&"]', f'a[href*="const_page={n}"]',
                f'a[href*="page_no={n}"]', f'a[href*="page={n}"]']:
        try:
            el = page.locator(sel).first
            if await el.is_visible(timeout=400):
                await el.click()
                return True
        except Exception:
            pass
    try:
        el = page.locator(f'a:text-is("{n}")').first
        if await el.is_visible(timeout=400):
            await el.click()
            return True
    except Exception:
        pass
    for sel in ['a:has-text("next page")', 'a:has-text("next")',
                'a:has-text(">")', 'a:has-text("›")', 'a:has-text("»")',
                'button:has-text("Next")', 'a.next',
                '[aria-label="Next"]', '[aria-label="Next page"]']:
        try:
            el = page.locator(sel).first
            if await el.is_visible(timeout=400):
                await el.click()
                return True
        except Exception:
            pass
    return False


async def _all_pages(page: Page, url: str) -> list[dict]:
    content = await load_page(page, url)
    if not content:
        return []
    pages = [content]
    seen  = {_fp(content["text"])}

    total = await _count_pages(page)
    param = await _detect_param(page)
    direct = bool(param and param != "const_page")

    if total > 1:
        print(f"    [pages] {total} page(s), param={param!r}")

    cap = min(total, 50)

    if cap > 1 and direct:
        repeated = 0
        for n in range(2, cap + 1):
            pu = _page_url(url, param, n)
            pc = await load_page(page, pu, quiet=True,
                                 extra_wait=config.PAGINATION_WAIT)
            if not pc:
                break
            fp = _fp(pc["text"])
            if fp in seen:
                repeated += 1
                if repeated >= 2:
                    break
                continue
            repeated = 0
            seen.add(fp)
            pages.append(pc)

    elif cap > 1:
        if param == "const_page" and await _click_page(page, 1):
            await page.wait_for_timeout(config.PAGINATION_WAIT)
            pages = [{"html": await page.content(),
                      "text": await page.inner_text("body"),
                      "url":  page.url}]
            seen = {_fp(pages[0]["text"])}

        repeated = 0
        for n in range(2, cap + 1):
            if not await _click_page(page, n):
                break
            await page.wait_for_timeout(config.PAGINATION_WAIT)
            text = await page.inner_text("body")
            fp   = _fp(text)
            if fp in seen:
                repeated += 1
                if repeated >= 3:
                    break
                continue
            repeated = 0
            seen.add(fp)
            pages.append({"html": await page.content(),
                           "text": text, "url": page.url})
    return pages


async def _profile_links(page: Page, domain: str) -> list[str]:
    links = await _get_links(page)
    out: list[str] = []
    seen: set[str] = set()
    for lk in links:
        href, text = lk.get("href", ""), lk.get("text", "")
        if not href or not _same_domain(href, domain):
            continue
        hl = href.lower()
        if (any(p in hl for p in ["/staff/", "/faculty/", "/teacher/",
                                    "/profile/", "/bio/", "/people/",
                                    "/user/", "/cms/one"])
                or bool(re.match(
                    r"^[A-Z][a-z]+\s+[A-Z][a-z]+(?:\s+[A-Z]\.?)?$",
                    text.strip()))
                or any(k in text.lower() for k in
                       ["view profile", "read more", "bio", "full bio"])):
            if href not in seen:
                seen.add(href)
                out.append(href)
    return out


async def harvest_staff_page(
    page: Page,
    url: str,
    domain: str,
    all_page_emails: dict[str, list[str]],
) -> list[dict]:
    sub_pages = await _all_pages(page, url)
    records: list[dict] = []
    page_emails: list[str] = []

    for pc in sub_pages:
        page_emails.extend(collect_emails_from_html(pc["html"]))
        for r in parse_staff_from_html(pc["html"], pc["url"]):
            r.setdefault("source_url", pc["url"])
            r.setdefault("bio", "")
            r.setdefault("linkedin_url", "")
            records.append(r)

    all_page_emails[url] = page_emails

    for prof_url in (await _profile_links(page, domain))[:6]:
        prof = await load_page(page, prof_url, quiet=True)
        if not prof:
            continue
        page_emails.extend(collect_emails_from_html(prof["html"]))
        for r in parse_staff_from_html(prof["html"], prof_url):
            r.setdefault("source_url", prof_url)
            r.setdefault("bio", "")
            r.setdefault("linkedin_url", "")
            records.append(r)

    return records


async def _run(
    start_url: str,
    max_pages: int | None,
    page_timeout: int | None,
    verbose: bool,
    progress_cb,
) -> tuple[list[dict], dict, dict[str, list[str]]]:

    if page_timeout:
        config.PAGE_TIMEOUT = page_timeout

    if not start_url.startswith(("http://", "https://")):
        start_url = "https://" + start_url

    domain = urlparse(start_url).netloc
    cap    = max_pages or config.MAX_PAGES

    pw, browser = await start_browser()
    page        = await open_page(browser)

    all_records: list[dict]           = []
    all_emails:  dict[str, list[str]] = {}
    school_info: dict                 = {"domain": domain}

    try:
        print(f"  [info] {start_url}")
        homepage = await load_page(page, start_url, quiet=True)
        if homepage:
            print("  [info] Extracting school info ...")
            school_info.update(extract_school_info(homepage["html"]))

        print("  [info] Discovering staff pages ...")
        staff_urls = await discover_staff_pages(page, browser, start_url)
        if not staff_urls:
            staff_urls = [start_url]
        staff_urls = staff_urls[:cap]
        print(f"  [info] {len(staff_urls)} page(s) to harvest")

        delay = robots_guard.get_crawl_delay(start_url) or config.CRAWL_DELAY
        for idx, url in enumerate(staff_urls):
            print(f"\n  [harvest] ({idx+1}/{len(staff_urls)}) {url}")
            records = await harvest_staff_page(page, url, domain, all_emails)
            print(f"  [harvest] {len(records)} raw records")
            all_records.extend(records)

            if progress_cb:
                progress_cb(idx + 1, len(staff_urls))

            if idx < len(staff_urls) - 1:
                await asyncio.sleep(delay)

    finally:
        await stop_browser(pw, browser)

    return all_records, school_info, all_emails


def crawl_and_extract(
    start_url: str,
    max_pages: int | None = None,
    page_timeout: int | None = None,
    verbose: bool = False,
    progress_callback=None,
) -> tuple[list[dict], dict, dict[str, list[str]]]:
    return asyncio.run(_run(
        start_url, max_pages, page_timeout, verbose, progress_callback
    ))
