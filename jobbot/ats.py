"""Local, deterministic ATS-style scoring. No AI involved, so the number is repeatable.

Score (100):
  60  keyword coverage (must-have keywords count double)
  10  standard sections present (summary, skills, experience, education)
   5  contact info (email + phone)
  10  quantified bullets (share of bullets containing a number)
   5  bullet length in the 8-32 word sweet spot
   5  bullets open with an action verb (not "Responsible for", "Worked on")
   5  no AI-sounding cliches
"""
import re

ALIASES = {
    "javascript": ["js"], "typescript": ["ts"], "node.js": ["nodejs", "node"], "react": ["react.js", "reactjs"],
    "next.js": ["nextjs"], "vue": ["vue.js", "vuejs"], "postgresql": ["postgres"], "kubernetes": ["k8s"],
    "machine learning": ["ml"], "artificial intelligence": ["ai"], "amazon web services": ["aws"],
    "google cloud": ["gcp"], "ci/cd": ["cicd", "continuous integration"], "rest api": ["rest apis", "restful"],
    "microservices": ["microservice"], "mongodb": ["mongo"], "c++": ["cpp"], "c#": ["csharp", ".net"],
    "large language models": ["llm", "llms"], "natural language processing": ["nlp"],
}

# Words/phrases recruiters and AI detectors associate with ChatGPT-style writing.
AI_TELLS = [
    "spearheaded", "leveraged", "leveraging", "synergy", "synergies", "results-driven", "results driven",
    "passionate", "dynamic", "cutting-edge", "cutting edge", "seamless", "seamlessly", "delve", "utilize",
    "utilized", "utilizing", "fast-paced", "go-getter", "team player", "detail-oriented", "proven track record",
    "in today's", "orchestrated", "pivotal", "meticulous", "meticulously", "tapestry", "testament", "showcasing",
    "harnessed", "harnessing", "elevate", "elevated", "revolutionized", "best-in-class", "thought leader",
    "self-starter", "hardworking", "hard-working", "innovative solutions", "transformative", "game-changer",
    "robust and scalable", "drive impactful", "highly motivated", "—",
]

WEAK_OPENERS = ("responsible for", "worked on", "helped", "assisted", "involved in", "tasked with", "duties included")


def _norm(s):
    return " " + re.sub(r"[^a-z0-9+#./ ]+", " ", s.lower()).replace("  ", " ") + " "


def has_keyword(text_norm, kw):
    for v in [kw.lower()] + ALIASES.get(kw.lower(), []):
        v = _norm(v).strip()
        if v and re.search(r"(?<![a-z0-9])" + re.escape(v) + r"(?![a-z0-9])", text_norm):
            return True
    return False


def resume_text(r):
    parts = [r.get("name", ""), r.get("headline", ""), r.get("summary", "")]
    c = r.get("contact") or {}
    parts += [c.get("email", ""), c.get("phone", ""), c.get("location", "")] + list(c.get("links") or [])
    for g in r.get("skills") or []:
        parts.append(g.get("category", "") + ": " + ", ".join(g.get("items") or []))
    for e in r.get("experience") or []:
        parts += [e.get("title", ""), e.get("company", "")] + list(e.get("bullets") or [])
    for p in r.get("projects") or []:
        parts += [p.get("name", ""), ", ".join(p.get("tech") or [])] + list(p.get("bullets") or [])
    for ed in r.get("education") or []:
        parts += [ed.get("degree", ""), ed.get("school", ""), ed.get("details", "")]
    parts += list(r.get("certifications") or []) + list(r.get("achievements") or [])
    return "\n".join(p for p in parts if p)


def bullets_of(r):
    out = []
    for e in r.get("experience") or []:
        out += e.get("bullets") or []
    for p in r.get("projects") or []:
        out += p.get("bullets") or []
    return out


def find_tells(text):
    low = text.lower()
    return sorted({t for t in AI_TELLS if t in low})


def quick_match(profile, jd):
    """Profile skills that appear in the JD. Instant pre-filter before spending an AI call on a job."""
    tn = _norm(jd)
    skills = [s for s in profile.get("skills") or [] if len(s.split()) <= 3]
    return [s for s in skills if has_keyword(tn, s)]


def score(resume, must=(), nice=()):
    """resume: resume dict (or plain text). Returns dict with score and diagnostics."""
    is_text = isinstance(resume, str)
    text = resume if is_text else resume_text(resume)
    tn = _norm(text)
    must = [k for k in dict.fromkeys(must) if k]
    nice = [k for k in dict.fromkeys(nice) if k and k not in must]

    hit_must = [k for k in must if has_keyword(tn, k)]
    hit_nice = [k for k in nice if has_keyword(tn, k)]
    total_w = 2 * len(must) + len(nice)
    kw = 60 * (2 * len(hit_must) + len(hit_nice)) / total_w if total_w else 60

    low = text.lower()
    if is_text:
        sections = sum(1 for s in ("summary", "skills", "experience", "education") if s in low)
        bullets = [l.strip(" •-*\t") for l in text.splitlines() if len(l.split()) >= 6]
    else:
        sections = sum(1 for k in ("summary", "skills", "experience", "education") if resume.get(k))
        bullets = bullets_of(resume)
    sec = 10 * sections / 4
    contact = (2.5 if re.search(r"[\w.+-]+@[\w-]+\.\w+", text) else 0) + \
              (2.5 if re.search(r"\+?\d[\d\s-]{8,}\d", text) else 0)

    n = len(bullets) or 1
    quant = sum(1 for b in bullets if re.search(r"\d", b)) / n
    quant_pts = 10 * min(1.0, quant / 0.6)
    length_ok = sum(1 for b in bullets if 8 <= len(b.split()) <= 32) / n
    verb_ok = sum(1 for b in bullets if b and not b.lower().startswith(WEAK_OPENERS)) / n
    tells = find_tells(text)
    tell_pts = max(0, 5 - 2 * len(tells))

    total = kw + sec + contact + quant_pts + 5 * length_ok + 5 * verb_ok + tell_pts
    return {
        "score": round(total),
        "keyword_score": round(kw),
        "missing_must": [k for k in must if k not in hit_must],
        "missing_nice": [k for k in nice if k not in hit_nice],
        "matched": hit_must + hit_nice,
        "quantified_pct": round(100 * quant),
        "ai_tells": tells,
        "bullets": len(bullets),
    }
