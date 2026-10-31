"""LinkedIn profile PDF (and/or an old resume PDF) -> structured data/profile.json."""
import json
import re
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import urlparse

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
    enrich_project_links(profile, paths)
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
    profile = apply_overrides(json.loads(PROFILE_PATH.read_text()))
    # Older profile.json files contain link labels but omit the clickable URLs in the source PDFs.
    enrich_project_links(profile, list(Path(__file__).resolve().parent.parent.glob("*.pdf")))
    return profile


def enrich_project_links(profile, paths):
    """Recover each project's real hyperlink annotations from source PDFs without inventing URLs."""
    projects = profile.get("projects") or []
    if not projects:
        return profile
    for path in paths:
        try:
            reader = PdfReader(str(path))
        except Exception:
            continue
        anchors, headings, cert_headings = [], [], []
        for page_no, page in enumerate(reader.pages):
            fragments = []
            try:
                page.extract_text(visitor_text=lambda text, cm, tm, font, size:
                                  fragments.append((float(tm[4]), float(tm[5]), text.strip())) if text.strip() else None)
            except Exception:
                fragments = []
            for annotation_ref in page.get("/Annots", []):
                try:
                    annotation = annotation_ref.get_object()
                    action = annotation.get("/A")
                    action = action.get_object() if action else None
                    uri = str(action.get("/URI") or "").strip() if action else ""
                    rect = [float(v) for v in annotation.get("/Rect", [])]
                    if not uri or len(rect) != 4 or not re.match(r"^https?://", uri, re.I):
                        continue
                    x0, y0, x1, y1 = rect
                    matching = [f for f in fragments if y0 - 2 <= f[1] <= y1 + 2 and x0 - 3 <= f[0] <= x1 + 3]
                    label = max(matching, key=lambda f: len(f[2]))[2].strip(" |") if matching else ""
                    anchors.append({"page": page_no, "y": (y0 + y1) / 2, "uri": uri, "label": label})
                except Exception:
                    continue

            # Project headings are identifiable from the saved profile, even when the source PDF
            # wraps or decorates the heading across several text fragments.
            for project in projects:
                name = _norm_project(project.get("name"))
                if not name:
                    continue
                candidates = [(SequenceMatcher(None, name, _norm_project(fragment)).ratio(), y)
                              for x, y, fragment in fragments if _norm_project(fragment)]
                candidates = [c for c in candidates if c[0] >= 0.82]
                if candidates:
                    _, heading_y = max(candidates)
                    headings.append((page_no, heading_y, project))
            for x, y, fragment in fragments:
                if "certification" in fragment.lower():
                    cert_headings.append((page_no, y))

        # Associate an annotation with the nearest project heading above it on the same page.
        for anchor in anchors:
            applicable = [(heading_y - anchor["y"], project) for page_no, heading_y, project in headings
                          if page_no == anchor["page"] and 0 <= heading_y - anchor["y"] <= 100]
            if not applicable:
                cert_context = [heading_y - anchor["y"] for page_no, heading_y in cert_headings
                                if page_no == anchor["page"] and 0 <= heading_y - anchor["y"] <= 100]
                host = (urlparse(anchor["uri"]).hostname or "").lower()
                label = anchor["label"].lower()
                if cert_context and profile.get("certifications") and (
                    "cert" in label or "codingshuttle.com" in host or "drive.google.com" in host
                ):
                    entry = {"certification": profile["certifications"][0],
                             "label": "Certificate" if "drive.google.com" in host else "Course",
                             "url": anchor["uri"]}
                    cert_links = profile.setdefault("certification_links", [])
                    if not any(link.get("url") == anchor["uri"] for link in cert_links):
                        cert_links.append(entry)
                continue
            _, project = min(applicable, key=lambda item: item[0])
            host = (urlparse(anchor["uri"]).hostname or "").lower()
            label = anchor["label"]
            if "github.com" in host or "github" in label.lower():
                label = "GitHub"
            elif "demo" in label.lower() or any(h in host for h in ("netlify.app", "vercel.app", "pages.dev")):
                label = "Live Demo"
            elif not label:
                label = "Website"
            links = project.setdefault("links", [])
            if not any(link.get("url") == anchor["uri"] for link in links):
                links.append({"label": label, "url": anchor["uri"]})
    return profile


def _norm_project(value):
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()
