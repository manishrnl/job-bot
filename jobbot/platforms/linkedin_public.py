"""LinkedIn's public (logged-out) job endpoints: search and job details over plain HTTP.

No browser and no account involved, so this part is fast and puts no load on your LinkedIn session.
Only the actual Easy Apply step needs the logged-in browser.
"""
import html
import re
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from ..config import CFG

GUEST = "https://www.linkedin.com/jobs-guest/jobs/api"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/155.0 Safari/537.36")


def _get(url, tries=4):
    for i in range(tries):
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code in (429, 999) or e.code >= 500:  # rate limited: back off
                time.sleep(3 * (i + 1))
                continue
            if e.code == 400:
                return ""
            raise
        except urllib.error.URLError:
            time.sleep(2 * (i + 1))
    return ""


def _text(fragment):
    s = re.sub(r"<\s*(br|/p|/li|/h\d|/div)[^>]*>", "\n", fragment, flags=re.I)
    s = re.sub(r"<li[^>]*>", "• ", s, flags=re.I)
    s = html.unescape(re.sub(r"<[^>]+>", "", s))
    return re.sub(r"\n\s*\n+", "\n\n", re.sub(r"[ \t]+", " ", s)).strip()


def _first(pattern, s):
    m = re.search(pattern, s, re.S)
    return _text(m.group(1)) if m else ""


def posted_seconds(spec):
    """'30m', '1h', '6h', '24h', '3d', '1w' -> seconds (LinkedIn's f_TPR filter). '' -> no filter."""
    m = re.fullmatch(r"\s*(\d+)\s*([mhdw]?)\s*", str(spec or "").lower())
    if not m:
        return 0
    n, unit = int(m.group(1)), m.group(2) or "d"
    return n * {"m": 60, "h": 3600, "d": 86400, "w": 604800}[unit]


def search(keywords, location, want, skip=lambda job_id: False):
    """Yield dicts {id, title, company, location, url} newest first, Easy Apply filter on."""
    s = CFG["search"]
    q = {"keywords": keywords, "location": location, "f_AL": "true", "sortBy": "DD"}
    secs = posted_seconds(s.get("posted_within") or (f"{s['posted_within_days']}d" if s.get("posted_within_days") else ""))
    if secs:
        q["f_TPR"] = f"r{secs}"
    if s.get("remote_only"):
        q["f_WT"] = "2"
    if s.get("experience_levels"):
        q["f_E"] = ",".join(str(x) for x in s["experience_levels"])
    seen, start, found = set(), 0, 0
    while found < want and start < 1000:
        page = _get(f"{GUEST}/seeMoreJobPostings/search?{urllib.parse.urlencode({**q, 'start': start})}")
        cards = page.split('data-entity-urn="urn:li:jobPosting:')[1:]
        if not cards:
            return
        for c in cards:
            jid = c.split('"', 1)[0]
            start += 1
            if jid in seen or skip(jid):
                continue
            seen.add(jid)
            found += 1
            yield {"id": jid, "url": f"https://www.linkedin.com/jobs/view/{jid}/",
                   "title": _first(r'base-search-card__title[^>]*>(.*?)</h3>', c),
                   "company": _first(r'base-search-card__subtitle[^>]*>(.*?)</h4>', c),
                   "location": _first(r'job-search-card__location[^>]*>(.*?)</span>', c)}
            if found >= want:
                return
        time.sleep(0.5)


def details(job):
    """Adds jd, seniority, easy_apply (True/False/None) to a job dict."""
    page = _get(f"{GUEST}/jobPosting/{job['id']}")
    job["jd"] = _first(r'show-more-less-html__markup[^>]*>(.*?)</div>', page)
    job["title"] = job.get("title") or _first(r'top-card-layout__title[^>]*>(.*?)</h2>', page)
    job["company"] = job.get("company") or _first(r'topcard__org-name-link[^>]*>(.*?)</a>', page)
    crit = re.findall(r'description__job-criteria-text[^>]*>(.*?)</span>', page, re.S)
    job["seniority"] = _text(crit[0]) if crit else ""
    m = re.search(r'public_jobs_apply-link-([a-z_]+)', page)
    job["easy_apply"] = None if not m else "offsite" not in m.group(1)
    return job


def details_many(jobs, workers=4):
    with ThreadPoolExecutor(workers) as ex:
        yield from ex.map(details, jobs)
