"""Profile + job description -> tailored, ATS-friendly, human-sounding resume (dict)."""
import json
import re

from . import ai, ats
from .config import CFG

RESUME_SCHEMA = """{
  "name": "", "headline": "target job title as written in the JD",
  "contact": {"email": "", "phone": "", "location": "", "links": []},
  "summary": "",
  "skills": [{"category": "", "items": [""]}],
  "experience": [{"title": "", "company": "", "location": "", "start": "", "end": "", "bullets": [""]}],
  "projects": [{"name": "", "tech": [""], "link": "", "bullets": [""]}],
  "education": [{"degree": "", "school": "", "location": "", "start": "", "end": "", "details": ""}],
  "certifications": [""],
  "achievements": [""]
}"""

WRITING_RULES = f"""TRUTH (non-negotiable):
- Use ONLY facts in the PROFILE. Never invent employers, titles, dates, degrees, certifications, tools or numbers.
- You may rephrase, reorder, merge, shorten or drop items, and name a skill that the described work clearly used.
- If the JD wants something the profile doesn't support, leave it out and list it under "gaps".

ATS:
- Mirror the JD's exact spelling of keywords ("Node.js" vs "NodeJS", "CI/CD", "PostgreSQL") wherever truthful.
- Put the most important JD keywords in the headline, summary, skills AND inside experience bullets (in context, not stuffed).
- Standard sections only. Plain text, no emojis, no symbols-as-bullets, no tables.

IMPACT:
- Every bullet: strong past-tense verb + what you did + how (tools) + result. Lead with the result when there is a number.
- Keep every metric from the profile. Prefer concrete scale (users, requests/sec, rows, % saved, time cut, team size).
- 3-5 bullets for recent roles, 1-3 for older ones; 12-28 words per bullet; most relevant bullets first.
- Summary: 2-3 sentences, no "I", states years of experience, core stack and one standout result.
  Compute years from full-time roles' dates and round DOWN ("3+ years"); internships don't count.
- Skills: 3-6 categories, JD-relevant first, max ~25 items total.
LENGTH BUDGET (hard limits; the PDF is A4 and must not spill a few lines onto an extra page):
- Target: {CFG['resume'].get('pages', 'auto')} page(s) (auto = exactly ONE page under 7 years of experience, else max 2).
- One page = at most ~430 words in total: summary <= 50 words, skills <= 5 lines,
  12-15 experience bullets in total (most recent role 4-5, older roles 2-3), projects max 2 with 2 bullets each,
  education 1 line per degree, certifications/achievements max 3 items on one line each.
- Every bullet <= 2 printed lines (<= 28 words). Prefer cutting a weak bullet over shortening every bullet.
- Leave out empty sections entirely (no heading with nothing under it).
- Locations short, max 3 words: "Noida, India", "Remote", "Los Angeles, USA". Title/company/location/dates
  must fit on one line.

SOUND HUMAN (must pass AI-text detectors and a skeptical recruiter):
- Plain, specific, slightly varied sentences, like an engineer wrote them. Vary verbs; never repeat a verb twice in a row.
- Never use these words/phrases: {", ".join(t for t in ats.AI_TELLS if t != chr(0x2014))}.
- No em dashes. No "not only X but also Y". No rule-of-three adjective lists. No buzzword summaries."""


RECRUITER = """You are a senior technical recruiter (10+ years hiring engineers in India and the US) who
also writes resumes. Review the profile the way you screen candidates: a 7-second scan of headline, latest
title, stack and numbers, then an ATS keyword check. Write the resume that would pass both: the strongest true
story for THIS job, most relevant work first, nothing a hiring manager would roll their eyes at."""

_BOILER = re.compile(r"\n[^\n]*(about (us|the company)|who we are|benefits|perks|what we offer|equal opportunity|"
                     r"eeo|diversity|privacy notice|how to apply)[^\n]*\n.*?(?=\n[^\n]*(responsibilit|requirement|"
                     r"qualification|you will|what you|skills|experience)[^\n]*\n|\Z)", re.I | re.S)


def compact_jd(jd, limit=6000):
    """Drop company blurb / benefits / EEO boilerplate and blank lines: same signal, ~40% fewer tokens."""
    jd = _BOILER.sub("\n", "\n" + jd)
    jd = re.sub(r"\n\s*\n+", "\n", jd).strip()
    return jd[:limit]


def _j(x):
    return json.dumps(x, ensure_ascii=False, separators=(",", ":"))


def tailor(profile, jd, title="", company=""):
    target = CFG["resume"].get("min_score", 85)
    jd = compact_jd(jd)
    prompt = f"""{RECRUITER}

{WRITING_RULES}

Return JSON:
{{"keywords": {{"must": ["required skills/tools/certifications, 1-3 words each, JD spelling, max 15"],
               "nice": ["nice-to-have skills/tools/domain terms, 1-3 words each, max 15"]}},
  "resume": {RESUME_SCHEMA},
  "gaps":["JD requirements the profile cannot honestly claim"]}}

JOB: {title} at {company}
JOB DESCRIPTION:
{jd}

PROFILE (the only source of truth):
{_j(profile)}"""
    res = ai.ask_json(prompt)
    must = res.get("keywords", {}).get("must", [])
    nice = res.get("keywords", {}).get("nice", [])
    resume = _fix_contact(res["resume"], profile)
    report = ats.score(resume, must, nice)

    # One refinement pass if needed: fold in missing keywords the profile supports, strip AI tells.
    for _ in range(CFG["resume"].get("refine_passes", 1)):
        # Only worth another AI call if there are AI tells, or missing keywords the profile actually has.
        fixable = [k for k in report["missing_must"] + report["missing_nice"] if ats.has_keyword(ats._norm(_j(profile)), k)]
        if (report["score"] >= target or not fixable) and not report["ai_tells"]:
            break
        report["fixable"] = fixable
        cand = _refine(resume, profile, jd, report)
        new = ats.score(cand, must, nice)
        if new["score"] < report["score"] and len(new["ai_tells"]) >= len(report["ai_tells"]):
            break  # refinement made it worse; keep the previous version
        resume, report = cand, new
    report["gaps"] = res.get("gaps", [])
    report["must"], report["nice"] = must, nice
    return resume, report


def experience_gate(profile, jd):
    """Reject jobs that require more than 2 years of experience for a 0-year candidate."""
    text = compact_jd(jd, 4000).lower()
    if not text:
        return 100, "freshers/0-2y"

    fresher_like = re.search(r"\b(freshers?|entry level|graduate|0\s*years?|0\s*[-to]+\s*2\s*years?|up to\s*2\s*years?)\b", text)

    if re.search(r"\b(?:5|6|7|8|9|10|[1-9]\d+)\s*\+\s*years?\b|\b(?:5|6|7|8|9|10|[1-9]\d+)\s*years?\s*(?:minimum|required|and\s*above)\b|\b(?:minimum|min)\s*(?:5|6|7|8|9|10|[1-9]\d+)\s*years?\b", text):
        if fresher_like:
            return 100, "freshers/0-2y"
        return 0, "requires 5+ years"
    if re.search(r"\b(?:3|4)\s*\+\s*years?\b|\b(?:3|4)\s*years?\s*(?:minimum|required|and\s*above)\b|\b(?:minimum|min)\s*(?:3|4)\s*years?\b", text):
        if fresher_like:
            return 100, "freshers/0-2y"
        return 0, "requires 3+ years"
    if re.search(r"\b(?:2)\s*\+\s*years?\b|\b(?:2)\s*years?\s*(?:minimum|required)\b", text):
        if fresher_like:
            return 100, "freshers/0-2y"
        return 0, "requires 2+ years"
    if fresher_like:
        return 100, "freshers/0-2y"
    return 100, "freshers/0-2y"


def fit_check(profile, jd, title=""):
    """Fast small-model screen (~5s) so we don't spend a full tailoring run on a job you can't get."""
    gate = experience_gate(profile, jd)
    if gate[0] == 0:
        return gate

    brief = {k: profile.get(k) for k in ("headline", "skills")}
    brief["experience"] = [{k: e.get(k) for k in ("title", "company", "start", "end")} for e in profile.get("experience") or []]
    prompt = f"""Rate how well this candidate fits this job, 0-100, like a recruiter screening in 10 seconds.
Score the core stack/role overlap, not every listed tool. A backend developer can do most backend jobs:
matching 2-3 main skills with a few missing is a GOOD fit (60-80). Missing nice-to-haves, cloud tools,
or a year of experience barely matters. Below 40 ONLY when the primary language/stack is entirely different
(e.g. Java/Scala/.NET/Android-only job for a Node.js/PHP developer) or it needs 2x the candidate's years.
Return JSON: {{"fit": 0, "reason": "max 12 words"}}

JOB: {title}
{compact_jd(jd, 3500)}

CANDIDATE: {_j(brief)}"""
    try:
        r = ai.ask_json(prompt, fast=True)
        return int(r.get("fit", 0)), str(r.get("reason", ""))
    except Exception:
        return 100, "fit check failed, not filtering"


def build_base(profile, role=""):
    """A polished general resume when there's no specific JD."""
    role = role or CFG["resume"].get("target_role") or profile.get("headline", "")
    prompt = f"""{RECRUITER}

Write the strongest general resume
for this person targeting "{role}" roles, optimized for ATS keyword search on LinkedIn/Naukri/Hirist.

{WRITING_RULES}

Return JSON: {{"keywords": ["top 20 keywords recruiters search for this role that the profile supports"],
              "resume": {RESUME_SCHEMA}}}

PROFILE (the only source of truth):
{_j(profile)}"""
    res = ai.ask_json(prompt)
    resume = _fix_contact(res["resume"], profile)
    report = ats.score(resume, res.get("keywords", []))
    if report["ai_tells"]:
        resume = _refine(resume, profile, "", report)
        report = ats.score(resume, res.get("keywords", []))
    report["must"], report["nice"], report["gaps"] = res.get("keywords", []), [], []
    return resume, report


def _refine(resume, profile, jd, report):
    prompt = f"""Improve this resume JSON. Keep the same schema and return only the resume JSON.

{WRITING_RULES}

Fix these issues:
- Missing JD keywords that the PROFILE supports: {report.get('fixable', [])}.
  Work each one naturally into a bullet, the summary or skills.
- Banned AI-sounding words found: {report['ai_tells']}. Rewrite those sentences in plain language.
- Only {report['quantified_pct']}% of bullets have numbers. Surface any numbers the PROFILE has; never invent.

RESUME:
{_j(resume)}

PROFILE (only source of truth):
{_j(profile)}"""
    out = ai.ask_json(prompt)
    return _fix_contact(out.get("resume", out), profile)


def _fix_contact(resume, profile):
    """Contact details always come from the profile/config, never from the model."""
    resume["name"] = profile.get("name") or resume.get("name", "")
    resume["contact"] = {**(resume.get("contact") or {}), **{k: v for k, v in (profile.get("contact") or {}).items() if v}}
    return resume
