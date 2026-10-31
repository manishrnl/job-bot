"""Answers application-form questions: contact fields -> config rules -> cache -> AI."""
import difflib
import json
import re

from . import ai
from .config import CFG, DATA

CACHE_PATH = DATA / "answers_cache.json"
_cache = json.loads(CACHE_PATH.read_text()) if CACHE_PATH.exists() else {}
_job = {"title": "", "company": "", "jd": ""}
_profile = {}

PLACEHOLDERS = {"", "select", "select an option", "please select", "choose", "--", "none selected", "-"}


def set_context(profile, title="", company="", jd=""):
    _profile.clear()
    _profile.update(profile)
    _job.update(title=title, company=company, jd=jd)


def pick_option(answer, options):
    opts = [o for o in options if o.strip().lower() not in PLACEHOLDERS]
    if not opts:
        return None
    a = answer.strip().lower()
    for o in opts:
        if o.strip().lower() == a:
            return o
    for o in opts:
        if a and (a in o.lower() or o.lower() in a):
            return o
    m = difflib.get_close_matches(answer, opts, n=1, cutoff=0.0)
    return m[0] if m else opts[0]


def _contact(q):
    c = _profile.get("contact") or {}
    name = (_profile.get("name") or "").split()
    links = c.get("links") or []
    link = lambda s: next((l for l in links if s in l.lower()), "")
    rules = [
        (("first name",), name[0] if name else ""),
        (("last name", "surname"), name[-1] if len(name) > 1 else ""),
        (("full name", "your name"), _profile.get("name", "")),
        (("email",), c.get("email", "")),
        (("mobile", "phone", "contact number"), re.sub(r"^\+?91[\s-]*", "", c.get("phone", ""))),
        (("linkedin",), link("linkedin")),
        (("github",), link("github")),
        (("portfolio", "website", "personal site"), next((l for l in links if "linkedin" not in l.lower()), "")),
        (("current city", "current location", "city", "location"), c.get("location", "")),
    ]
    for keys, val in rules:
        if val and any(k in q for k in keys):
            return val
    return None


NAV_JUNK = re.compile(r"my network|notifications|for business|messaging|skip to (main|search)", re.I)
META = re.compile(r"not a (form )?question|can.?t answer|cannot answer|unable to|please (share|provide|check)|"
                  r"as an ai|appears to be|i.?m sorry|no answer|scraped|navigation", re.I)
# Logistics/preference questions: the "general choice" that keeps the application moving.
AGREEABLE = re.compile(r"comfortable|willing|open to|relocat|commute|on-?site|office|shift|join within|"
                       r"available|agree|consent|okay with|ok with|fine with|budget|ctc range|background check", re.I)
EXPERIENCE_QUESTION = re.compile(
    r"\bexperience\b|\bhow many years\b|\bhow long have you\b|"
    r"\byears?\s+(?:of\s+(?:work|professional|industry)|working|worked|with|in|using)\b", re.I)
ZERO_EXPERIENCE_OPTION = re.compile(r"\b0(?:\.0)?\b|no experience|none|never|less than 1 year|under 1 year|fresher|entry level", re.I)


def _ctc_units(q, value):
    """CTC in config can be LPA ("7") or rupees ("700000"); answer in the unit the question asks for."""
    try:
        v = float(value.replace(",", "").lower().replace("lpa", "").strip())
    except ValueError:
        return value
    lpa = v / 100000 if v >= 1000 else v
    if re.search(r"rupees|inr|₹|in numbers|absolute|per annum \(in", q) and not re.search(r"lpa|lakh|lac", q):
        return str(int(lpa * 100000))
    return f"{lpa:g}"


def looks_like_question(label):
    return bool(label) and len(label) <= 300 and not NAV_JUNK.search(label)


def default_answer(question, options, numeric):
    """General, safe choice when the AI is unsure or returned junk."""
    if options:
        yes = next((o for o in options if o.strip().lower() in ("yes", "y", "true")), None)
        no = next((o for o in options if o.strip().lower() in ("no", "n", "false")), None)
        if yes and (AGREEABLE.search(question) or not no):
            return yes
        return yes or pick_option("", options) or options[0]
    return "0" if numeric else ""


def _fresher_experience_answer(options):
    """Return zero experience, choosing an equivalent option when the form restricts the choices."""
    if not options:
        return "0"
    zero = next((o for o in options if ZERO_EXPERIENCE_OPTION.search(o)), None)
    if zero:
        return zero
    # If the form only offers Yes/No, zero experience is represented by No.
    no = next((o for o in options if o.strip().lower() in ("no", "n", "false")), None)
    if no:
        return no
    numeric_options = []
    for option in options:
        nums = re.findall(r"\d+(?:\.\d+)?", option.replace(",", ""))
        if nums:
            numeric_options.append((min(float(n) for n in nums), option))
    if numeric_options:
        return min(numeric_options, key=lambda item: item[0])[1]
    return options[0]


def answer(question, options=None, numeric=False, long=False):
    q = " ".join(question.lower().split())
    options = [o for o in (options or []) if o]

    # This rule runs before contact/config answers, cache lookup, and AI so a past
    # "Yes, 5 years" answer can never be reused for this fresher profile.
    if EXPERIENCE_QUESTION.search(q):
        return _fresher_experience_answer(options)

    ans = _contact(q) if not options else None

    # Other questions can still be tailored to the profile; experience questions return above.
    skill_specific = (re.search(r"\bexperience\b.*\b(with|in|using|on)\b", q)
                      and not re.search(r"\b(total|overall|industry|it industry|relevant)\b", q))
    if ans is None:
        for rule in CFG.get("answers") or []:
            if skill_specific and any("experience" in m.lower() for m in rule.get("match", [])):
                continue
            if any(m.lower() in q for m in rule.get("match", [])):
                ans = _ctc_units(q, str(rule.get("answer", ""))) if "ctc" in rule["match"][0] else str(rule.get("answer", ""))
                break

    key = q + ("|" + "|".join(options) if options else "")
    if ans is None and "cover letter" not in q and key in _cache:
        ans = _cache[key]

    if ans is None:
        ans = _ask_ai(question, options, numeric, long or "cover letter" in q)
        valid = ans and not META.search(ans) and (not options or _matches(ans, options))
        if not valid:
            ans = default_answer(q, options, numeric)
        elif "cover letter" not in q:
            _cache[key] = ans
            CACHE_PATH.write_text(json.dumps(_cache, indent=2, ensure_ascii=False))

    if numeric:
        m = re.search(r"\d+(\.\d+)?", ans.replace(",", ""))
        ans = m.group(0) if m else "0"
    if options:
        ans = pick_option(ans, options) or ans
    return ans


def _matches(ans, options):
    a = ans.strip().lower()
    return any(a == o.strip().lower() or (len(a) > 1 and (a in o.lower() or o.lower() in a)) for o in options)


def _brief():
    """Compact profile for form answers (~1/5 of the full JSON): stack + role timeline."""
    p = _profile
    exp = "; ".join(f"{e.get('title')} @ {e.get('company')} ({e.get('start')}-{e.get('end')})"
                    for e in p.get("experience") or [])
    edu = "; ".join(f"{e.get('degree')} {e.get('school')} {e.get('end', '')}" for e in p.get("education") or [])
    return (f"{p.get('name')} | {p.get('headline')} | {(p.get('contact') or {}).get('location', '')}\n"
            f"Skills: {', '.join(p.get('skills') or [])}\nExperience: {exp}\nEducation: {edu}")


def _ask_ai(question, options, numeric, long):
    facts = {r["match"][0]: r["answer"] for r in CFG.get("answers") or [] if r.get("match")}
    fmt = ("Reply with EXACTLY one of these options, copied verbatim: " + json.dumps(options)) if options else \
          ("Reply with a number only (digits, no units)." if numeric else
           ("Reply in 90-140 words, plain and specific, no cliches, no em dashes." if long else
            "Reply in one short line (max 20 words)."))
    prompt = f"""You are filling a job application form on behalf of this candidate. Answer truthfully from
the profile, but keep the application moving: never reject yourself.
Skills: if the profile shows X, answer Yes / its years from the profile dates. If X is not in the profile but
is in the same field (backend, APIs, databases, cloud, DevOps, web, JS/TS ecosystem, AI/LLM), answer Yes /
1 year: the candidate can work with it. Answer No / 0 only for a clearly different field (e.g. SAP, iOS,
embedded, mainframe).
For logistics/preferences (office days, location, relocation, shifts, joining time, budget range): Yes.
For self-ratings ("rate yourself out of 5"): a number, 3 or 4 based on the profile.
If unsure, give the most common reasonable answer. Never explain, never refuse, never ask for clarification.

Question: {question}
{fmt}

Job: {_job['title']} at {_job['company']}
Job (excerpt): {_job['jd'][:1200]}
Known answers: {json.dumps(facts, separators=(",", ":"))}
Candidate: {_brief()}"""
    try:
        out = ai.ask(prompt, fast=not long).strip()
    except RuntimeError:
        return options[0] if options else ("0" if numeric else "")
    if long or not out:
        return out
    return out.splitlines()[0].strip().strip('"')
