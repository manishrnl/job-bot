"""Generic form filler: works on LinkedIn Easy Apply modals, Hirist, Greenhouse, Lever, Workable, etc.

Scans a container for inputs/selects/radios, answers each unfilled one via answers.answer(),
and uploads the tailored resume into resume file inputs. Never clicks submit.
"""
import re

from playwright.sync_api import Locator

from . import answers

SCAN_JS = r"""
(root) => {
  const doc = root.ownerDocument || document;
  const vis = el => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  const clean = s => (s || '').replace(/\s+/g, ' ').trim();
  const CONTROLS = 'input:not([type=hidden]), select, textarea';
  // Text of the largest ancestor that still contains only this one control (or this one radio).
  const ownText = (el, sel) => {
    let t = '', p = el.parentElement;
    for (let i = 0; i < 6 && p && p !== root.parentElement; i++) {
      if (p.querySelectorAll(sel).length > 1) break;
      if (clean(p.innerText)) t = p.innerText;
      p = p.parentElement;
    }
    return clean(t);
  };
  const forLabel = el => el.id ? clean(doc.querySelector(`label[for="${CSS.escape(el.id)}"]`)?.innerText) : '';
  const labelOf = el => {
    let t = forLabel(el);
    if (!t && el.getAttribute('aria-labelledby')) {
      t = clean(el.getAttribute('aria-labelledby').split(' ').map(id => doc.getElementById(id)?.innerText || '').join(' '));
    }
    if (!t) t = clean(el.getAttribute('aria-label'));
    if (!t) t = clean(el.closest('label')?.innerText);
    if (!t) t = ownText(el, CONTROLS);
    if (!t) t = clean(el.getAttribute('placeholder') || el.name || '');
    return t.slice(0, 300);
  };
  const optionText = (el, question) => {
    let t = forLabel(el);
    if (!t) t = ownText(el, 'input[type=radio], input[type=checkbox]');
    const aria = clean(el.getAttribute('aria-label'));
    if (!t && aria && aria !== question) t = aria;
    return (t || el.value || '').slice(0, 200);
  };
  root.querySelectorAll('[data-jb]').forEach(e => e.removeAttribute('data-jb'));
  const out = []; let n = 0;
  const fileInputs = [...root.querySelectorAll('input[type="file"]')];
  root.querySelectorAll('input, textarea, select').forEach(el => {
    const type = (el.type || '').toLowerCase();
    if (['hidden', 'submit', 'button', 'search', 'radio', 'checkbox', 'image', 'reset'].includes(type)) return;
    const resumeHint = type === 'file' ? [labelOf(el), el.name || el.id || '', el.getAttribute('aria-label') || '', el.getAttribute('placeholder') || ''].join(' ') : '';
    const resumeLike = type === 'file' && (/resume|cv|curriculum/i.test(resumeHint) || fileInputs.length === 1);
    if (type !== 'file' && (!vis(el) || el.disabled || el.readOnly)) return;
    if (type === 'file' && !resumeLike && !vis(el)) return;
    const tag = el.tagName.toLowerCase();
    const key = String(++n); el.setAttribute('data-jb', key);
    out.push({ key, kind: tag === 'select' ? 'select' : type === 'file' ? 'file' : tag === 'textarea' ? 'textarea' : 'text',
      type, label: labelOf(el), name: el.name || el.id || '', maxlength: el.maxLength > 0 ? el.maxLength : 0,
      value: tag === 'select' ? clean(el.options[el.selectedIndex]?.text) : (el.value || ''),
      options: tag === 'select' ? [...el.options].map(o => clean(o.text)) : [],
      numeric: type === 'number' || /numeric/i.test(el.id || '') || el.inputMode === 'numeric',
      combobox: el.getAttribute('role') === 'combobox' || !!el.getAttribute('aria-autocomplete') });
  });
  const groups = {};
  root.querySelectorAll('input[type=radio]').forEach(el => {
    if (!vis(el) && !vis(el.parentElement)) return;
    const g = el.name || el.closest('fieldset')?.id || 'radio'; (groups[g] = groups[g] || []).push(el);
  });
  for (const els of Object.values(groups)) {
    const fs = els[0].closest('fieldset, [role=radiogroup]');
    // Question: <legend>; else a shared aria-label on every radio (new LinkedIn UI);
    // else the text right before the group.
    let q = clean(fs?.querySelector('legend')?.innerText);
    const arias = [...new Set(els.map(e => clean(e.getAttribute('aria-label'))))];
    if (!q && arias.length === 1 && arias[0]) q = arias[0];
    if (!q && fs) { let s = fs.previousElementSibling; while (s && !clean(s.innerText)) s = s.previousElementSibling;
                    q = clean(s?.innerText); }
    if (!q && fs) q = clean(fs.parentElement?.innerText).slice(0, 300);
    const opts = els.map(e => { const k = String(++n); e.setAttribute('data-jb', k); return { key: k, text: optionText(e, q) }; });
    out.push({ kind: 'radio', label: q.replace(/\*$/, '').slice(0, 300), options: opts, checked: els.some(e => e.checked) });
  }
  root.querySelectorAll('input[type=checkbox]').forEach(el => {
    if (el.checked) return;
    const req = el.required || el.getAttribute('aria-required') === 'true';
    const lab = optionText(el, '') || labelOf(el);
    if (req || /agree|terms|consent|acknowledge|confirm/i.test(lab)) {
      const k = String(++n); el.setAttribute('data-jb', k); out.push({ key: k, kind: 'checkbox', label: lab });
    }
  });
  return out;
}
"""

NUMERIC_HINT = re.compile(r"how many|years|number of|ctc|salary|notice period|in days|in months|lpa|percentage|cgpa|gpa"
                          r"|rate yourself|out of (5|10)|on a scale", re.I)
RESUME_HINT = re.compile(r"resume|cv|curriculum", re.I)


def _resume_file_rank(f, files):
    """Return a score for whether this file input is the actual resume uploader.

    The order matters: a lone upload field should still be treated as the résumé even if its label is
    generic or misleading. For multi-file forms, we prefer explicit resume labels, then a first-file
    fallback only when nothing clearer is available.
    """
    if len(files) == 1:
        return 10
    hint = " ".join([
        f.get("label", ""),
        f.get("name", ""),
        f.get("type", ""),
    ])
    if re.search(r"cover|letter", hint, re.I):
        return -100
    if re.search(r"photo|image|portfolio|video|audio", hint, re.I):
        return -50
    if RESUME_HINT.search(hint):
        return 100
    return 1 if f is files[0] else 0


def fill(scope, resume_pdf, log=print):
    """scope: a Playwright Locator (e.g. a modal) or a Page/Frame. Returns number of fields touched."""
    container = scope if isinstance(scope, Locator) else scope.locator("body")
    fields = container.evaluate(SCAN_JS)
    touched = 0
    files = [f for f in fields if f["kind"] == "file"]
    for f in fields:
        try:
            touched += _fill_one(scope, f, files, resume_pdf, log)
        except Exception as e:  # one stubborn field shouldn't kill the whole application
            log(f"  [dim]could not fill '{f.get('label', '')[:50]}': {str(e).splitlines()[0][:80]}[/dim]")
    return touched


def _el(scope, key):
    return scope.locator(f"[data-jb='{key}']").first


def _fill_one(scope, f, files, resume_pdf, log):
    kind, label = f["kind"], f.get("label", "")
    if kind == "file":
        if _resume_file_rank(f, files) <= 0:
            return 0
        el = _el(scope, f["key"])
        log(f"  [yellow]uploading generated resume: {resume_pdf}[/]")
        before = el.evaluate("(node) => ({ name: node.name, files: node.files ? Array.from(node.files).map(f => f.name) : [], value: node.value || '' })")
        log(f"  [dim]resume input before: {before}[/]")
        try:
            el.evaluate("""
            (node) => {
              try { node.value = ''; } catch (e) {}
              try { node.files = []; } catch (e) {}
              try { const dt = new DataTransfer(); node.files = dt.files; } catch (e) {}
            }
            """)
            el.set_input_files(str(resume_pdf))
            el.evaluate("(node) => node.dispatchEvent(new Event('change', { bubbles: true }))")
        except Exception:
            try:
                el.evaluate("(node) => node.setAttribute('value', '')")
                el.set_input_files(str(resume_pdf))
                el.evaluate("(node) => node.dispatchEvent(new Event('change', { bubbles: true }))")
            except Exception:
                el.evaluate(f"(node) => node.files = ['{str(resume_pdf).replace('\\', '\\\\')}']")
                el.evaluate("(node) => node.dispatchEvent(new Event('change', { bubbles: true }))")
        after = el.evaluate("(node) => ({ name: node.name, files: node.files ? Array.from(node.files).map(f => f.name) : [], value: node.value || '' })")
        log(f"  [dim]resume input after: {after}[/]")
        log(f"  uploaded resume -> {label[:40] or 'file input'}")
        return 1
    if kind in ("text", "textarea"):
        if f["value"].strip():
            return 0
        if not answers.looks_like_question(label):
            log(f"  [dim]skipped field with unclear label: {label[:50]!r}[/dim]")
            return 0
        el = _el(scope, f["key"])
        if el.input_value().strip():  # filled meanwhile (e.g. autofill by the site)
            return 0
        numeric = f["numeric"] or bool(NUMERIC_HINT.search(label)) and kind == "text" and len(label) < 200
        ans = answers.answer(label, numeric=numeric, long=kind == "textarea")
        if f.get("maxlength") and len(ans) > f["maxlength"]:
            m = re.search(r"\d+(\.\d+)?", ans)
            ans = m.group(0) if (m and kind == "text") else ans[: f["maxlength"]]
        if not ans:
            return 0
        el.fill(ans)
        if f["combobox"]:
            el.page.wait_for_timeout(1200)
            el.press("ArrowDown")
            el.press("Enter")
        log(f"  {label[:60]!r} -> {ans[:60]!r}")
        return 1
    if kind == "select":
        if f["value"].strip().lower() not in answers.PLACEHOLDERS:
            return 0
        ans = answers.answer(label, options=f["options"])
        choice = answers.pick_option(ans, f["options"])
        if choice:
            _el(scope, f["key"]).select_option(label=choice)
            log(f"  {label[:60]!r} -> {choice!r}")
            return 1
        return 0
    if kind == "radio":
        if f["checked"]:
            return 0
        texts = [o["text"] for o in f["options"]]
        choice = answers.pick_option(answers.answer(label, options=texts), texts)
        opt = next(o for o in f["options"] if o["text"] == choice)
        el = _el(scope, opt["key"])
        try:
            el.check(force=True, timeout=3000)
        except Exception:
            el.evaluate("e => e.click()")
        log(f"  {label[:60]!r} -> {choice!r}")
        return 1
    if kind == "checkbox":
        el = _el(scope, f["key"])
        try:
            el.check(force=True, timeout=3000)
        except Exception:
            el.evaluate("e => e.click()")
        return 1
    return 0
