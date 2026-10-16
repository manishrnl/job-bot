"""Shared steps: tailor a resume for one job, render it, print the report."""
import json

from rich.console import Console
from rich.table import Table

from . import render, tailor

console = Console()


def report_table(rep, pdf=None):
    t = Table(show_header=False, box=None, padding=(0, 1))
    color = "green" if rep["score"] >= 85 else "yellow" if rep["score"] >= 70 else "red"
    t.add_row("ATS score", f"[bold {color}]{rep['score']}/100[/]  (keywords {rep['keyword_score']}/60)")
    t.add_row("Matched", ", ".join(rep["matched"][:20]) or "-")
    if rep["missing_must"]:
        t.add_row("Missing (must)", f"[red]{', '.join(rep['missing_must'])}[/]")
    if rep["missing_nice"]:
        t.add_row("Missing (nice)", f"[yellow]{', '.join(rep['missing_nice'])}[/]")
    t.add_row("Quantified bullets", f"{rep['quantified_pct']}% of {rep['bullets']}")
    t.add_row("AI-sounding words", f"[red]{', '.join(rep['ai_tells'])}[/]" if rep["ai_tells"] else "[green]none[/]")
    if rep.get("gaps"):
        t.add_row("Honest gaps", "; ".join(rep["gaps"])[:300])
    if pdf:
        t.add_row("Resume", str(pdf))
    console.print(t)


def tailored_resume(profile, jd, title="", company="", pw=None, quiet=False):
    with console.status(f"Tailoring resume for {title or 'job'} {('@ ' + company) if company else ''}..."):
        resume, rep = tailor.tailor(profile, jd, title, company)
        pdf = render.save(resume, render.slug(company, title), pw=pw)
        pdf.with_suffix(".json").write_text(json.dumps({"resume": resume, "report": rep}, indent=2, ensure_ascii=False))
    if not quiet:
        report_table(rep, pdf)
    return pdf, rep
