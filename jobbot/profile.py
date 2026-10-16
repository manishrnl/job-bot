"""LinkedIn profile PDF (and/or an old resume PDF) -> structured data/profile.json."""
import json

from pypdf import PdfReader

from . import ai
from .config import CFG, PROFILE_PATH

SCHEMA = """{
  "name": "", "headline": "",
  "contact": {"email": "", "phone": "", "location": "", "links": ["..."]},
  "summary": "",
  "skills": ["every skill/tool/technology mentioned anywhere"],
  "experience": [{"title": "", "company": "", "location": "", "start": "Mon YYYY", "end": "Mon YYYY or Present",
                  "details": ["every responsibility, achievement, tool and number, one item per fact"]}],
  "projects": [{"name": "", "tech": ["..."], "link": "", "details": ["..."]}],
  "education": [{"degree": "", "school": "", "location": "", "start": "", "end": "", "details": ""}],
  "certifications": ["..."],
  "achievements": ["awards, rankings, publications, open-source, hackathons"],
  "languages": ["..."]
}"""


def pdf_text(path):
    reader = PdfReader(str(path))
    return "\n".join((p.extract_text() or "") for p in reader.pages)


def build(paths):
    text = "\n\n----- NEXT DOCUMENT -----\n\n".join(pdf_text(p) for p in paths)
    prompt = f"""Extract this person's career data into JSON with exactly this schema:
{SCHEMA}

Rules:
- The input is a LinkedIn "Save to PDF" export and/or an existing resume. Merge duplicates.
- Copy facts faithfully. Do NOT invent, embellish or drop anything: keep every number, tool, scope and outcome.
- Ignore page headers/footers like "Page 1 of 3".
- Unknown fields stay "" or [].

DOCUMENT TEXT:
{text}"""
    profile = ai.ask_json(prompt)
    apply_overrides(profile)
    PROFILE_PATH.write_text(json.dumps(profile, indent=2, ensure_ascii=False))
    return profile


def apply_overrides(profile):
    c = CFG.get("contact") or {}
    if c.get("name"):
        profile["name"] = c["name"]
    contact = profile.setdefault("contact", {})
    for k in ("email", "phone", "location"):
        if c.get(k):
            contact[k] = c[k]
    if c.get("links"):
        contact["links"] = c["links"]
    return profile


def load():
    if not PROFILE_PATH.exists():
        raise SystemExit("No profile yet. Run: ./jb init /path/to/linkedin_profile.pdf")
    return apply_overrides(json.loads(PROFILE_PATH.read_text()))
