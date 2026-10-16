"""Any job URL (Naukri, Instahyre, Wellfound, Greenhouse, Lever, Workable, company career pages...).

Reads the JD from the page, tailors the resume, pre-fills whatever form is on the page (including
iframes), then hands over to you to review and click Submit yourself.
"""
from .. import answers, formfill, tracker
from ..browser import pause
from ..pipeline import console, tailored_resume


def apply(pw, page, profile, url, jd_override=""):
    page.goto(url, wait_until="domcontentloaded")
    pause(3, 4)
    title = page.title()
    jd = jd_override or page.inner_text("body")
    for fr in page.frames[1:]:
        try:
            jd += "\n" + fr.locator("body").inner_text(timeout=2000)
        except Exception:
            pass
    pdf, rep = tailored_resume(profile, jd, title, "", pw=pw)
    answers.set_context(profile, title, "", jd)

    console.print("\nIf there's an Apply button that opens the form, click it in the browser now.")
    input("Press Enter when the application form is visible (or right away to fill this page)... ")
    n = 0
    for fr in page.frames:
        try:
            n += formfill.fill(fr, pdf, log=console.print)
        except Exception as e:
            console.print(f"[dim]frame skipped: {str(e)[:80]}[/]")
    console.print(f"\n[green]Pre-filled {n} fields.[/] Check everything, fix anything off, then submit in the browser.")
    ans = input("Did you submit? [y/N] ").strip().lower()
    status = "applied" if ans == "y" else "prefilled"
    tracker.record("web", url, title, "", url, status, rep["score"], pdf)
    return status
