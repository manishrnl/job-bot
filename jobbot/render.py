"""Resume dict -> HTML -> PDF (text-based, single column, ATS-parseable) + a .txt copy.

Layout guarantees:
  - A section heading is never left alone at the bottom of a page (heading + first entry stay together).
  - Small sections (skills, education, certifications) never split across pages.
  - Auto-fit: if content overflows the page target by a little, font/spacing tighten step by step
    (never below 9pt) instead of spilling a few lines onto a new page.
"""
import datetime
import math
import re
from html import escape
from urllib.parse import quote, urlsplit, urlunsplit

from . import ats
from .config import CFG, OUT

# (font pt, line-height, section gap px, bullet gap px, name pt)
DENSITY = [
    (10.5, 1.34, 12, 1.8, 23),
    (10.2, 1.30, 10, 1.5, 22),
    (9.9, 1.27, 9, 1.2, 21),
    (9.6, 1.24, 8, 1.0, 20),
    (9.3, 1.21, 7, 0.8, 20),
    (9.0, 1.18, 6, 0.5, 19),
]
MARGIN_MM = (12, 14)  # top/bottom, left/right
PAGE_H_PX = (297 - 2 * MARGIN_MM[0]) * 96 / 25.4
PAGE_W_PX = (210 - 2 * MARGIN_MM[1]) * 96 / 25.4


def _css(accent, level):
    fs, lh, gap, li, name = DENSITY[level]
    return f"""
* {{ box-sizing: border-box; }}
body {{ font-family: Calibri, Carlito, "Segoe UI", Arial, Helvetica, sans-serif; color: #1a1a1a;
       font-size: {fs}pt; line-height: {lh}; margin: 0; }}
h1 {{ font-size: {name}pt; margin: 0; letter-spacing: .4px; color: #111; line-height: 1.1; }}
.headline {{ font-size: {fs + 1.1}pt; color: {accent}; font-weight: 600; margin-top: 2px; }}
.contact {{ font-size: {fs - 0.8}pt; color: #333; margin-top: 3px; }}
section {{ margin-top: {gap}px; }}
h2 {{ font-size: {fs + 0.6}pt; text-transform: uppercase; letter-spacing: 1.1px; color: {accent};
     border-bottom: 1.4px solid {accent}; padding-bottom: 1px; margin: 0 0 4px;
     break-after: avoid; page-break-after: avoid; }}
.keep {{ break-inside: avoid; page-break-inside: avoid; }}
.row {{ display: flex; justify-content: space-between; align-items: baseline; gap: 10px; }}
.role {{ font-weight: 700; }} .org {{ font-weight: 600; color: #333; }}
.dates {{ font-size: {fs - 0.8}pt; color: #444; white-space: nowrap; }}
ul {{ margin: 2px 0 {gap * 0.45:.1f}px 0; padding-left: 15px; }} li {{ margin: {li}px 0; }}
.item {{ break-inside: avoid; page-break-inside: avoid; }}
.skills div {{ margin: {li}px 0; }} .skills b {{ color: #222; }}
p {{ margin: 2px 0; }} .muted {{ color: #444; }}
a {{ color: {accent}; text-decoration: underline; }}
"""


def _e(s):
    return escape(str(s or ""))


def _url_href(url):
    """Use HTTPS and www for root domains; retain required service subdomains such as Netlify."""
    value = str(url or "").strip()
    if not value:
        return ""
    if re.match(r"^(?:mailto:|tel:)", value, re.I):
        return value
    if value.startswith("//"):
        value = "https:" + value
    elif not re.match(r"^https?://", value, re.I):
        value = "https://" + value.lstrip("/")
    parsed = urlsplit(value)
    host = parsed.hostname or ""
    # www is valid for apex domains. For actual subdomains (e.g. Netlify app URLs), adding
    # another www label changes the host and breaks the destination.
    if host and not host.lower().startswith("www.") and host.count(".") == 1:
        host = "www." + host
    netloc = host
    if parsed.port:
        netloc += f":{parsed.port}"
    return urlunsplit(("https", netloc, parsed.path, parsed.query, parsed.fragment))


def _link(url, label=None):
    href = _url_href(url)
    visible = str(label if label is not None else href or "")
    if not url:
        return _e(visible)
    if href.lower().startswith(("mailto:", "tel:")):
        return f"<a href='{_e(href)}'>{_e(visible)}</a>"
    return f"<a href='{_e(href)}' target='_blank' rel='noopener noreferrer'>{_e(visible)}</a>"


def _contact_link_label(url):
    host = (urlsplit(_url_href(url)).hostname or "").lower()
    if "linkedin.com" in host:
        return "LinkedIn"
    if "github.com" in host:
        return "GitHub"
    if "instagram.com" in host:
        return "Instagram"
    if host.endswith("manishrnl.in"):
        return "Portfolio"
    return host.removeprefix("www.") or str(url)


_URL_IN_TEXT = re.compile(r"(?i)(?:https?://|www\.)[^\s<>]+|(?<![@\w])(?:[\w-]+\.)+(?:com|org|net|io|dev|app|edu|gov|in|me|co)(?:/[^\s<>]*)?")


def _linkify(text):
    """Make literal URLs in certificate/details text clickable without rewriting their labels."""
    value = str(text or "")
    out, pos = [], 0
    for match in _URL_IN_TEXT.finditer(value):
        raw = match.group(0).rstrip(".,;:!?)]]}")
        if not raw:
            continue
        end = match.start() + len(raw)
        out.append(_e(value[pos:match.start()]))
        out.append(_link(raw))
        pos = end
    out.append(_e(value[pos:]))
    return "".join(out)


def _dates(x):
    s, e = x.get("start", ""), x.get("end", "")
    return f"{_e(s)} – {_e(e)}" if s and e else _e(s or e)


def _section(title, items, keep_all=False):
    """Heading glued to the first entry; whole section unbreakable when small."""
    if not items:
        return ""
    if keep_all or len(items) == 1:
        return f"<section class='keep'><h2>{title}</h2>{''.join(items)}</section>"
    return (f"<section><div class='keep'><h2>{title}</h2>{items[0]}</div>{''.join(items[1:])}</section>")


def _entry(head, bullets):
    lis = "".join(f"<li>{_linkify(b)}</li>" for b in bullets or [] if b)
    return f"<div class='item'>{head}{'<ul>' + lis + '</ul>' if lis else ''}</div>"


def html(r, level=0):
    accent = CFG["resume"].get("accent_color", "#1F4E79")
    c = r.get("contact") or {}
    contact = [_e(c.get("location")) if c.get("location") else ""]
    phone = re.sub(r"[^0-9+]", "", str(c.get("phone") or ""))
    if phone:
        contact.append(_link("tel:" + phone, c.get("phone")))
    email = str(c.get("email") or "").strip()
    if email:
        contact.append(_link("mailto:" + quote(email, safe="@+.-_"), email))
    out = [f"<html><head><meta charset='utf-8'><title>{_e(r.get('name'))} Resume</title>"
           f"<style>{_css(accent, level)}</style></head><body>",
           f"<header class='keep'><h1>{_e(r.get('name'))}</h1>"]
    if r.get("headline"):
        out.append(f"<div class='headline'>{_e(r['headline'])}</div>")
    out.append("<div class='contact'>" + " &nbsp;|&nbsp; ".join(x for x in contact if x))
    out.extend(" &nbsp;|&nbsp; " + _link(url, _contact_link_label(url)) for url in c.get("links") or [] if url)
    out.append("</div></header>")

    if r.get("summary"):
        out.append(_section("Summary", [f"<p>{_linkify(r['summary'])}</p>"]))
    if r.get("skills"):
        rows = "".join(f"<div><b>{_e(g.get('category'))}:</b> {_e(', '.join(g.get('items') or []))}</div>"
                       for g in r["skills"])
        out.append(_section("Skills", [f"<div class='skills'>{rows}</div>"]))

    exp = []
    for x in r.get("experience") or []:
        loc = f" <span class='muted'>&middot; {_e(x['location'])}</span>" if x.get("location") else ""
        head = (f"<div class='row'><div><span class='role'>{_e(x.get('title'))}</span> &nbsp;|&nbsp; "
                f"<span class='org'>{_e(x.get('company'))}</span>{loc}</div><div class='dates'>{_dates(x)}</div></div>")
        exp.append(_entry(head, x.get("bullets")))
    out.append(_section("Experience", exp))

    proj = []
    for p in r.get("projects") or []:
        tech = f" <span class='muted'>({_e(', '.join(p['tech']))})</span>" if p.get("tech") else ""
        project_links = list(p.get("links") or [])
        if not project_links and p.get("link", "").lower().startswith(("http://", "https://", "www.")):
            project_links = [{"url": p["link"], "label": ""}]
        linked = " &nbsp;|&nbsp; ".join(
            _link(item.get("url", ""), item.get("label") or "Project link")
            for item in project_links if item.get("url")
        )
        if not linked and p.get("link"):
            linked = _linkify(p["link"])
        link = f"<div class='dates'>{linked}</div>" if linked else ""
        head = f"<div class='row'><div><span class='role'>{_e(p.get('name'))}</span>{tech}</div>{link}</div>"
        proj.append(_entry(head, p.get("bullets")))
    out.append(_section("Projects", proj))

    edu = []
    for ed in r.get("education") or []:
        det = f"<div class='muted'>{_linkify(ed['details'])}</div>" if ed.get("details") else ""
        edu.append(f"<div class='item'><div class='row'><div><span class='role'>{_e(ed.get('degree'))}</span>"
                   f" &nbsp;|&nbsp; <span class='org'>{_e(ed.get('school'))}</span></div>"
                   f"<div class='dates'>{_dates(ed)}</div></div>{det}</div>")
    out.append(_section("Education", edu, keep_all=True))

    for key, label in (("certifications", "Certifications"), ("achievements", "Achievements")):
        items = [i for i in r.get(key) or [] if i]
        if items:
            rows = []
            for i, item in enumerate(items):
                links = ([link for link in r.get("certification_links") or []
                          if link.get("certification") == item or len(items) == 1]
                         if key == "certifications" else [])
                urls = " &nbsp;|&nbsp; ".join(
                    _link(link.get("url", ""), link.get("label") or "Certificate")
                    for link in links if link.get("url")
                )
                rows.append(f"<li>{_linkify(item)}{' &nbsp;|&nbsp; ' + urls if urls else ''}</li>")
            out.append(_section(label, ["<ul>" + "".join(rows) + "</ul>"], keep_all=True))
    out.append("</body></html>")
    return "\n".join(out)


def slug(*parts):
    s = "_".join(p for p in parts if p)
    return re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_")[:80] or "resume"


def target_pages(resume):
    want = str(CFG["resume"].get("pages", "auto"))
    if want in ("1", "2"):
        return int(want)
    years = ats_years(resume)
    return 1 if years < 7 else 2


def ats_years(resume):
    yrs = [int(y) for x in resume.get("experience") or [] for y in re.findall(r"(?:19|20)\d\d", f"{x.get('start')} {x.get('end')}")]
    if not yrs:
        return 0
    end = datetime.date.today().year if any("present" in str(x.get("end", "")).lower()
                                            for x in resume.get("experience") or []) else max(yrs)
    return end - min(yrs)


def save(resume, name_hint="", pw=None):
    """Write PDF + TXT + HTML directly under output/ using timestamped filenames."""
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    stem = slug(resume.get('name', '').split(' ')[0], name_hint)
    pdf = OUT / f"{stem}_{stamp}.pdf"
    txt = OUT / f"{stem}_{stamp}.txt"
    html_path = OUT / f"{stem}_{stamp}.html"
    txt.write_text(ats.resume_text(resume))
    if pw is None:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            doc = _pdf(p, resume, pdf)
    else:
        doc = _pdf(pw, resume, pdf)
    html_path.write_text(doc)
    return pdf


def save_cover_letter(text, name_hint="", pw=None):
    """Write a readable PDF copy of a generated cover letter under output/."""
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    stem = slug("cover_letter", name_hint)
    pdf = OUT / f"{stem}_{stamp}.pdf"
    paragraphs = "".join(f"<p>{_e(line)}</p>" for line in text.splitlines() if line.strip())
    doc = ("<html><head><meta charset='utf-8'><style>"
           "body{font-family:Calibri,'Segoe UI',Arial,sans-serif;color:#1a1a1a;font-size:11pt;"
           "line-height:1.5;margin:25mm 22mm}p{margin:0 0 12pt;white-space:pre-wrap}"
           "</style></head><body>" + paragraphs + "</body></html>")
    if pw is None:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            _document_pdf(p, doc, pdf)
    else:
        _document_pdf(pw, doc, pdf)
    pdf.with_suffix(".txt").write_text(text, encoding="utf-8")
    return pdf


_browsers = {}  # one headless browser per Playwright instance, reused across resumes


def _pages_at(page, doc):
    page.set_content(doc, wait_until="load")
    return page.evaluate("document.body.scrollHeight") / PAGE_H_PX


def _pdf(pw, resume, path):
    browser = _browsers.get(id(pw))
    if browser is None or not browser.is_connected():
        browser = _browsers[id(pw)] = pw.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": math.floor(PAGE_W_PX), "height": 1000})
    try:
        page.emulate_media(media="print")
        target = target_pages(resume)
        # Least dense level that fits the target; if nothing fits, the densest level that avoids a
        # near-empty last page; otherwise the roomiest layout on whole pages.
        chosen, doc = 0, html(resume, 0)
        for lvl in range(len(DENSITY)):
            d = html(resume, lvl)
            used = _pages_at(page, d)
            if used <= target * 0.985:
                chosen, doc = lvl, d
                break
            if math.ceil(used) > target and (used % 1) > 0.35:  # overflow is substantial: don't cram
                chosen, doc = 0, html(resume, 0)
                break
            chosen, doc = lvl, d
        page.set_content(doc, wait_until="load")
        page.pdf(path=str(path), format="A4", print_background=True, prefer_css_page_size=False,
                 margin={"top": f"{MARGIN_MM[0]}mm", "bottom": f"{MARGIN_MM[0]}mm",
                         "left": f"{MARGIN_MM[1]}mm", "right": f"{MARGIN_MM[1]}mm"})
        return doc
    finally:
        page.close()


def _document_pdf(pw, doc, path):
    browser = _browsers.get(id(pw))
    if browser is None or not browser.is_connected():
        browser = _browsers[id(pw)] = pw.chromium.launch(headless=True)
    page = browser.new_page()
    try:
        page.set_content(doc, wait_until="load")
        page.pdf(path=str(path), format="A4", print_background=True,
                 margin={"top": "18mm", "bottom": "18mm", "left": "20mm", "right": "20mm"})
    finally:
        page.close()
