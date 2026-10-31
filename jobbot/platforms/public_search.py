"""Public search helpers for job discovery without logging into a site.

This mirrors the LinkedIn job-search pattern so additional sources like Hirist and
company career portals can be added with the same interface:

    jobs = list(search(keywords, location, want, skip=...))

Each yielded item is a dict shaped like:
    {"id": ..., "title": ..., "company": ..., "location": ..., "url": ...}
"""

import html
import re
import urllib.parse
import urllib.request

from .linkedin_public import search as linkedin_search


def _get(url, tries=3):
    last_err = None
    for i in range(tries):
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/125.0.0.0 Safari/537.36"
                    ),
                    "Accept-Language": "en-US,en;q=0.9",
                },
            )
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as exc:  # pragma: no cover - used at runtime only
            last_err = exc
    raise RuntimeError(f"HTTP fetch failed for {url}: {last_err}")


def slugify(text):
    text = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return text or "jobs"


def _clean_text(s):
    s = html.unescape(re.sub(r"<[^>]+>", " ", s or ""))
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def hirist_search(keywords, location, want, skip=lambda job_id: False):
    """Search Hirist public pages by keyword.

    This is intentionally simple and mirrors the LinkedIn API style. It focuses on
    the public `/k/<keyword>-jobs` pages and yields a consistent job dict.
    """
    seen = set()
    count = 0
    for keyword in keywords:
        if count >= want:
            break
        slug = slugify(keyword)
        url = f"https://www.hirist.tech/k/{slug}-jobs"
        params = {}
        if location:
            params["location"] = location
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"
        try:
            page = _get(url)
        except Exception:
            continue
        for match in re.finditer(r"https://www\.hirist\.tech/j/[A-Za-z0-9-]+", page):
            jid = match.group(0)
            if jid in seen or skip(jid):
                continue
            seen.add(jid)
            count += 1
            yield {
                "id": jid,
                "title": keyword,
                "company": "Hirist",
                "location": location or "India",
                "url": jid,
            }
            if count >= want:
                return


def company_search(company, keywords, location, want, skip=lambda job_id: False):
    """Generic company-career search adapter.

    This is a template for public job pages such as TCS, Infosys, Wipro, Capgemini,
    Cognizant or LTIMindtree. Most company portals use site-specific URLs and HTML,
    so this is intentionally a thin adapter around an actual company parser.
    """
    company = (company or "").strip()
    if not company:
        return []

    if company.lower() == "hirist":
        yield from hirist_search(keywords, location, want, skip)
        return

    # For large Indian IT companies, the usual path is a custom company-specific
    # parser. Keep the interface consistent, but do not guess unsupported URLs.
    raise NotImplementedError(
        f"No public search parser is wired for '{company}' yet. "
        "Add a site-specific search function before using it."
    )


def search(source, keywords, location, want, skip=lambda job_id: False):
    """Dispatcher for supported public search sources."""
    source = (source or "linkedin").lower()
    if source == "linkedin":
        yield from linkedin_search(keywords, location, want, skip)
        return
    if source == "hirist":
        yield from hirist_search(keywords, location, want, skip)
        return
    if source in {"tcs", "infosys", "wipro", "capgemini", "cognizant", "ltimindtree", "hcltech"}:
        yield from company_search(source, keywords, location, want, skip)
        return
    raise ValueError(f"Unsupported public search source: {source}")
