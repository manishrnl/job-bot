"""LinkedIn Easy Apply, as a pipeline:

  discover (HTTP, no browser)  ->  filter (instant, no AI)  ->  fit check + tailor (N parallel AI workers)
      ->  apply (one logged-in browser, as soon as each resume is ready)

The browser never waits on the AI except when the queue is empty, and the anti-spam delay between
applications overlaps with resume generation instead of adding to it.
"""
import json
import random
import re
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

from .. import answers, ats, formfill, render, tailor, tracker
from ..browser import pause
from ..config import CFG, DATA
from ..pipeline import console, report_table
from . import linkedin_public

BASE = "https://www.linkedin.com"
P = "linkedin"
DEBUG = DATA / "debug"


# ---------- login (only when the saved session is missing/expired) ----------

def has_session(ctx):
    return any(c["name"] == "li_at" for c in ctx.cookies(BASE))


def ensure_login(page, force=False):
    if has_session(page.context) and not force:
        return
    page.goto(f"{BASE}/login", wait_until="domcontentloaded")
    console.print("[yellow]LinkedIn session missing/expired. Log in in the browser window; "
                  "I'll continue automatically (session is saved for next time).[/]")
    for _ in range(300):
        if "/feed" in page.url or ("/login" not in page.url and "checkpoint" not in page.url and has_session(page.context)):
            console.print("[green]Logged in.[/]")
            return
        time.sleep(1)
    raise SystemExit("Timed out waiting for LinkedIn login.")


# ---------- discover + cheap filters ----------

def discover(profile, keywords, location, want):
    s, a = CFG["search"], CFG["apply"]
    excl_words = [w.lower() for w in s.get("exclude_title_words") or []]
    excl_cos = [c.lower() for c in s.get("exclude_companies") or []]
    min_overlap = a.get("min_skill_overlap", 3)
    ids = set()

    def skip(jid):
        return jid in ids or tracker.seen(P, jid)

    for kw in keywords:
        console.rule(f"[bold]LinkedIn: {kw} / {location}")
        batch = []
        for job in linkedin_public.search(kw, location, want, skip=skip):
            ids.add(job["id"])
            t, c = job["title"].lower(), job["company"].lower()
            if any(w in t for w in excl_words) or any(x in c for x in excl_cos):
                console.print(f"[dim]  skip (excluded): {job['title']} @ {job['company']}[/]")
                tracker.record(P, job["id"], job["title"], job["company"], job["url"], "excluded")
                continue
            batch.append(job)
            if len(batch) >= 8:
                yield from _detail_filter(profile, batch, min_overlap)
                batch = []
        yield from _detail_filter(profile, batch, min_overlap)


def _detail_filter(profile, batch, min_overlap):
    for job in linkedin_public.details_many(batch):
        rec = (P, job["id"], job["title"], job["company"], job["url"])
        if job["easy_apply"] is False:
            console.print(f"[dim]  skip (external apply): {job['title']} @ {job['company']}[/]")
            tracker.record(*rec, "external")
            continue
        if len(job["jd"]) < 100:
            console.print(f"[dim]  skip (no description): {job['title']}[/]")
            continue
        overlap = ats.quick_match(profile, job["jd"])
        if len(overlap) < min_overlap:
            console.print(f"[dim]  skip ({len(overlap)} skills match): {job['title']} @ {job['company']}[/]")
            tracker.record(*rec, "low_match", note=f"skill overlap {len(overlap)}")
            continue
        yield job


# ---------- AI worker (runs in a thread) ----------

def prepare(profile, job):
    fit, reason = tailor.fit_check(profile, job["jd"], job["title"])
    job.update(fit=fit, fit_reason=reason)
    if fit < CFG["apply"].get("min_fit", 55):
        return job
    job["resume"], job["report"] = tailor.tailor(profile, job["jd"], job["title"], job["company"])
    return job


# ---------- browser: Easy Apply ----------

EASY_APPLY = ("button[aria-label*='Easy Apply' i]:visible, a[aria-label*='Easy Apply' i]:visible, "
              "button:has-text('Easy Apply'):visible, a:has-text('Easy Apply'):visible")
STEP_BTN = re.compile(r"(continue to next step|review your application|submit application|^next$|^review$)", re.I)


def _click(loc):
    try:
        if loc.count() and loc.first.is_visible():
            loc.first.click(timeout=5000)
            return True
    except Exception:
        pass
    return False


def find_apply_scope(page, timeout=15):
    """The Easy Apply form: a dialog (old UI) or a full-page / iframe flow (new UI)."""
    end = time.time() + timeout
    while time.time() < end:
        for fr in page.frames:
            try:
                for sel in ("dialog[open]", "[data-testid='dialog']", ".jobs-easy-apply-modal",
                            "[data-test-modal][role='dialog']", "div[role='dialog']", "[aria-modal='true']"):
                    d = fr.locator(sel).filter(has=fr.get_by_role("button", name=STEP_BTN))
                    if d.count() and d.first.is_visible():
                        return d.first
                # Never fall back to the whole page: the header search box etc. would be "filled" too.
                b = fr.get_by_role("button", name=STEP_BTN)
                if b.count() and b.first.is_visible():
                    form = fr.locator("form").filter(has=b)
                    if form.count():
                        return form.first
            except Exception:
                continue
        time.sleep(0.5)
    return None


def discard(page):
    _click(page.locator("dialog[open] button[aria-label='Dismiss'], button[aria-label='Dismiss'], "
                        "button[aria-label*='dismiss' i]"))
    pause(0.6, 1)
    _click(page.get_by_role("button", name=re.compile(r"^discard$", re.I)))
    _click(page.locator("button[data-control-name='discard_application_confirm_btn']"))


def dump(page, jid, why):
    DEBUG.mkdir(exist_ok=True)
    try:
        page.screenshot(path=str(DEBUG / f"{jid}.png"))
        (DEBUG / f"{jid}.html").write_text(page.content())
    except Exception:
        pass
    console.print(f"  [dim]debug saved: data/debug/{jid}.png ({why})[/]")


def run_easy_apply(page, m, resume_pdf, dry_run, log):
    stuck, last_sig = 0, None
    for _ in range(15):
        pause(0.6, 1.2)
        formfill.fill(m, resume_pdf, log=log)
        if not CFG["apply"].get("follow_companies"):
            cb = m.locator("#follow-company-checkbox")
            if cb.count() and cb.is_checked():
                m.locator("label[for='follow-company-checkbox']").click()

        submit = m.get_by_role("button", name=re.compile(r"submit application", re.I))
        if submit.count() and submit.first.is_visible():
            if dry_run:
                log("  [cyan]dry run: reached Submit, discarding[/]")
                discard(page)
                return "dry_run"
            submit.first.click()
            pause(2, 3)
            for _ in range(2):  # post-submit "application sent" dialog
                _click(page.locator("button[aria-label='Dismiss']"))
                _click(page.get_by_role("button", name=re.compile(r"^done$", re.I)))
            return "applied"

        nxt = m.get_by_role("button", name=re.compile(r"(continue to next step|review your application|^next$|^review$)", re.I))
        if not _click(nxt):
            log("  [red]no Next/Review/Submit button found[/]")
            return "stuck"
        pause(0.8, 1.4)
        errors = m.locator(".artdeco-inline-feedback--error:visible, [role='alert']:visible")
        sig = m.inner_text()[:400] if m.count() else ""
        if errors.count() and sig == last_sig:
            stuck += 1
            if stuck >= 2:
                log("  [red]form keeps rejecting an answer:[/] " + errors.first.inner_text()[:120])
                return "stuck"
        last_sig = sig
    return "stuck"


def apply_job(pw, page, profile, job, dry_run):
    resume, rep = job["resume"], job["report"]
    pdf = render.save(resume, render.slug(job["company"], job["title"]), pw=pw)
    pdf.with_suffix(".json").write_text(json.dumps({"job": {k: v for k, v in job.items() if k not in ("resume", "report")},
                                                    "resume": resume, "report": rep}, indent=2, ensure_ascii=False))
    job["pdf"] = pdf
    answers.set_context(profile, job["title"], job["company"], job["jd"])

    page.goto(job["url"], wait_until="domcontentloaded")
    if "/login" in page.url or "authwall" in page.url:
        ensure_login(page, force=True)
        page.goto(job["url"], wait_until="domcontentloaded")
    btn = page.locator(EASY_APPLY).first
    try:
        btn.wait_for(timeout=8000)
    except Exception:
        body = page.locator("main").first.inner_text() if page.locator("main").count() else ""
        if re.search(r"\bapplied\b.{0,20}\bago\b|application submitted", body, re.I):
            return "applied", "applied earlier"
        dump(page, job["id"], "no Easy Apply button")
        return "error", "no Easy Apply button"
    btn.click()
    m = find_apply_scope(page)
    if m is None:  # new UI sometimes needs the direct apply URL
        page.goto(job["url"] + "apply/?openSDUIApplyFlow=true", wait_until="domcontentloaded")
        m = find_apply_scope(page)
    if m is None:
        dump(page, job["id"], "apply form not found")
        return "error", "apply form not found"
    status = run_easy_apply(page, m, pdf, dry_run, console.print)
    if status == "stuck":
        dump(page, job["id"], "stuck")
        discard(page)
    return status, ""


# ---------- orchestration ----------

def apply(pw, page, profile, keywords, location, limit, dry_run=False):
    ensure_login(page)
    a = CFG["apply"]
    workers = int(a.get("parallel_resumes", 3))
    lo, hi = a.get("delay_seconds", [20, 45])
    jobs = discover(profile, keywords, location, want=max(limit * 4, 20))
    pool = ThreadPoolExecutor(workers)
    pending, done, next_ok = set(), 0, 0.0
    tally = {}

    def refill():
        while len(pending) < workers * 2:
            job = next(jobs, None)
            if job is None:
                return
            console.print(f"[dim]  queued: {job['title']} @ {job['company']}[/]")
            pending.add(pool.submit(prepare, profile, job))

    t0 = time.time()
    refill()
    try:
        while pending and done < limit:
            finished, _ = wait(pending, return_when=FIRST_COMPLETED)
            for fut in finished:
                pending.discard(fut)
                try:
                    job = fut.result()
                except Exception as e:
                    console.print(f"[red]  AI error: {str(e)[:120]}[/]")
                    continue
                rec = (P, job["id"], job["title"], job["company"], job["url"])
                console.print(f"\n[bold]{job['title']}[/] @ {job['company']}  [dim]{job['url']}[/]")
                if "resume" not in job:
                    console.print(f"  [yellow]fit {job['fit']}: {job['fit_reason']} -> skip[/]")
                    tracker.record(*rec, "low_fit", note=job["fit_reason"], fit=job["fit"])
                    tally["low_fit"] = tally.get("low_fit", 0) + 1
                    continue
                rep = job["report"]
                if rep["score"] < a.get("min_match_score", 65):
                    console.print(f"  [yellow]ATS {rep['score']} < min_match_score -> skip[/]")
                    tracker.record(*rec, "low_match", rep["score"], fit=job["fit"])
                    tally["low_match"] = tally.get("low_match", 0) + 1
                    continue
                if done >= limit:
                    continue
                if not dry_run and time.time() < next_ok:  # anti-spam gap, mostly already spent on AI work
                    time.sleep(next_ok - time.time())
                try:
                    status, note = apply_job(pw, page, profile, job, dry_run)
                except Exception as e:
                    status, note = "error", str(e).splitlines()[0][:150]
                    dump(page, job["id"], note)
                report_table(rep, job.get("pdf"))
                tracker.record(*rec, status, rep["score"], job.get("pdf", ""), note, fit=job["fit"])
                tally[status] = tally.get(status, 0) + 1
                color = {"applied": "green", "dry_run": "cyan"}.get(status, "red")
                console.print(f"  => [bold {color}]{status}[/] {note}")
                if status in ("applied", "dry_run"):
                    done += 1
                    next_ok = time.time() + random.uniform(lo, hi)
                    console.print(f"  [dim]{done}/{limit} done[/]")
            refill()
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    mins = (time.time() - t0) / 60
    console.print(f"\n[bold]Run summary[/] ({mins:.1f} min): " + ", ".join(f"{k}: {v}" for k, v in tally.items()))
    return done
