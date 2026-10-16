"""Hirist (hirist.tech) automation. BETA: Hirist renders jobs client-side and changes markup;
locators rely on URLs (/j/...) and visible button text.

Hirist normally applies with the resume stored on your Hirist profile. If the apply flow shows a
file upload, the tailored PDF is uploaded; otherwise upload your `./jb build` resume to Hirist once.
"""
import random
import re
import time

from .. import answers, formfill, tracker
from ..browser import pause
from ..config import CFG
from ..pipeline import console, report_table, tailored_resume

BASE = "https://www.hirist.tech"
P = "hirist"


def logged_in(page):
    page.goto(BASE, wait_until="domcontentloaded")
    pause(2, 3)
    login = page.get_by_role("button", name=re.compile(r"^(login|log in|sign in)$", re.I))
    login_link = page.get_by_role("link", name=re.compile(r"^(login|log in|sign in)$", re.I))
    return not (login.count() and login.first.is_visible()) and not (login_link.count() and login_link.first.is_visible())


def collect_jobs(page, keyword, want):
    slug = re.sub(r"[^a-z0-9]+", "-", keyword.lower()).strip("-")
    page.goto(f"{BASE}/k/{slug}-jobs", wait_until="domcontentloaded")
    pause(3, 4)
    urls = []
    for _ in range(8):  # infinite scroll
        hrefs = page.eval_on_selector_all("a[href]", "els => els.map(e => e.href)")
        for h in hrefs:
            h = h.split("?")[0]
            if "/j/" in h and h not in urls and not tracker.seen(P, h):
                urls.append(h)
        if len(urls) >= want * 3:
            break
        page.mouse.wheel(0, 4000)
        pause(1.5, 2.5)
    return urls


def apply_one(page, pdf, dry_run, log):
    btn = page.get_by_role("button", name=re.compile(r"^\s*(easy\s*)?apply( now)?\s*$", re.I))
    if not (btn.count() and btn.first.is_visible()):
        return "external"
    if dry_run:
        return "dry_run"
    btn.first.click()
    pause(2, 3)
    for _ in range(5):  # optional questionnaire / upload dialog
        dialog = page.locator("[role='dialog']:visible, .modal:visible").first
        if not dialog.count():
            break
        formfill.fill(dialog, pdf, log=log)
        nxt = dialog.get_by_role("button", name=re.compile(r"^(submit|apply|next|continue|save)", re.I))
        if not (nxt.count() and nxt.first.is_visible()):
            break
        nxt.first.click()
        pause(2, 3)
    applied = page.get_by_text(re.compile(r"^\s*applied\s*$|application (sent|submitted)|successfully applied", re.I))
    return "applied" if applied.count() else "unknown"


def apply(pw, page, profile, keywords, location, limit, dry_run=False):
    if not logged_in(page):
        raise SystemExit("Not logged in to Hirist. Run: ./jb login hirist")
    a = CFG["apply"]
    excl = [w.lower() for w in CFG["search"].get("exclude_title_words") or []]
    done = 0
    for kw in keywords:
        if done >= limit:
            break
        console.rule(f"[bold]Hirist: {kw}")
        urls = collect_jobs(page, kw, limit - done)
        console.print(f"{len(urls)} new jobs found")
        for url in urls:
            if done >= limit:
                break
            page.goto(url, wait_until="domcontentloaded")
            pause(2.5, 4)
            title = (page.locator("h1").first.inner_text() if page.locator("h1").count() else "").strip()
            company = title.split(" - ")[0] if " - " in title else ""
            jd = page.locator("main").first.inner_text() if page.locator("main").count() else page.inner_text("body")
            console.print(f"\n[bold]{title}[/]  [dim]{url}[/]")
            if any(w in title.lower() for w in excl):
                console.print("  [dim]excluded by config[/]")
                continue
            if location and location.lower() not in ("india", "") and location.lower() not in jd.lower():
                console.print(f"  [dim]location '{location}' not mentioned, skipping[/]")
                continue
            pdf, rep = tailored_resume(profile, jd, title, company, pw=pw, quiet=True)
            report_table(rep, pdf)
            if rep["score"] < a.get("min_match_score", 65):
                tracker.record(P, url, title, company, url, "low_match", rep["score"], pdf)
                console.print("  [yellow]low match, skipping[/]")
                continue
            answers.set_context(profile, title, company, jd)
            status = apply_one(page, pdf, dry_run, console.print)
            tracker.record(P, url, title, company, url, status, rep["score"], pdf)
            console.print(f"  => [bold]{status}[/]")
            if status in ("applied", "dry_run", "unknown"):
                done += 1
            if status in ("applied", "unknown"):
                lo, hi = a.get("delay_seconds", [45, 120])
                time.sleep(random.uniform(lo, hi))
    return done
