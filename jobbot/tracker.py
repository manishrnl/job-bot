"""SQLite job history with a formatted Excel export, so applications are trackable and readable."""
import csv
import datetime
import sqlite3

from pathlib import Path

from .config import DATA

COLS = ["platform", "job_id", "title", "company", "url", "status", "score", "fit", "resume", "note", "at"]
RUNS_DIR = DATA / "runs"
RUNS_DIR.mkdir(exist_ok=True)
_db = sqlite3.connect(DATA / "jobs.db")
_db.execute("""CREATE TABLE IF NOT EXISTS jobs (
  platform TEXT, job_id TEXT, title TEXT, company TEXT, url TEXT, status TEXT,
  score INTEGER, resume TEXT, note TEXT, at TEXT, PRIMARY KEY (platform, job_id))""")
if "fit" not in [r[1] for r in _db.execute("PRAGMA table_info(jobs)")]:
    _db.execute("ALTER TABLE jobs ADD COLUMN fit INTEGER")

# Statuses that mean "don't look at this job again". Errors/stuck are retried on the next run.
FINAL = ("Applied", "Low-Match", "Low-Fit", "External", "Excluded", "Draft-Saved", "Draft-Local")


def seen(platform, job_id, statuses=FINAL):
    q = f"SELECT 1 FROM jobs WHERE platform=? AND job_id=? AND status IN ({','.join('?' * len(statuses))})"
    return _db.execute(q, (platform, job_id, *statuses)).fetchone() is not None


def record(platform, job_id, title="", company="", url="", status="", score=None, resume="", note="", fit=None):
    row = dict(platform=platform, job_id=job_id, title=title, company=company, url=url, status=status,
               score=score, fit=fit, resume=str(resume or ""), note=note,
               at=datetime.datetime.now().isoformat(timespec="seconds"))
    _db.execute(f"INSERT OR REPLACE INTO jobs ({','.join(COLS)}) VALUES ({','.join('?' * len(COLS))})",
                [row[c] for c in COLS])
    _db.commit()
    export_excel()


def rows(limit=50, status=None):
    q = "SELECT at, platform, status, score, fit, title, company, url FROM jobs"
    args = []
    if status:
        q += " WHERE status=?"
        args.append(status)
    return _db.execute(q + " ORDER BY at DESC LIMIT ?", (*args, limit)).fetchall()


def stats():
    today = datetime.date.today().isoformat()
    by_status = dict(_db.execute("SELECT status, COUNT(*) FROM jobs GROUP BY status").fetchall())
    applied_today = _db.execute("SELECT COUNT(*) FROM jobs WHERE status='Applied' AND at >= ?", (today,)).fetchone()[0]
    avg = _db.execute("SELECT ROUND(AVG(score)) FROM jobs WHERE status='Applied'").fetchone()[0]
    per_day = _db.execute("SELECT substr(at,1,10) d, COUNT(*) FROM jobs WHERE status='Applied' "
                          "GROUP BY d ORDER BY d DESC LIMIT 14").fetchall()
    by_platform = dict(_db.execute("SELECT platform, COUNT(*) FROM jobs WHERE status='Applied' GROUP BY platform").fetchall())
    return dict(by_status=by_status, applied_today=applied_today, avg_score=avg, per_day=per_day,
                by_platform=by_platform, total_applied=by_status.get("Applied", 0))


def export_excel():
    """Rebuild the readable application workbook from SQLite history."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.formatting.rule import CellIsRule, FormulaRule

    path = DATA / "applications.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "Applications"
    headers = ["Date", "Status", "ATS score", "Fit", "Job title", "Company",
               "LinkedIn job", "Resume PDF", "Note"]
    ws.append(headers)
    header_fill = PatternFill("solid", fgColor="17365D")
    for cell in ws[1]:
        cell.fill = header_fill
        cell.font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
        cell.alignment = Alignment(vertical="center")

    rows = _db.execute(f"SELECT {','.join(COLS)} FROM jobs ORDER BY at DESC").fetchall()
    for row in rows:
        record = dict(zip(COLS, row))
        ws.append([record["at"], record["status"], record["score"] or "-", record["fit"] or "-",
                   record["title"], record["company"], record["url"] or "N/A",
                   record["resume"] or "N/A", record["note"] or "N/A"])
        n = ws.max_row
        try:
            from datetime import datetime
            ws.cell(n, 1).value = datetime.fromisoformat(record["at"])
            ws.cell(n, 1).number_format = "yyyy-mm-dd hh:mm"
        except (TypeError, ValueError):
            pass
        title_cell = ws.cell(n, 5)
        title_cell.font = Font(name="Calibri", size=11, bold=True, color="C00000")
        title_cell.alignment = Alignment(vertical="top", wrap_text=True)

        job_cell = ws.cell(n, 7)
        if record["url"]:
            target = str(record["url"]).strip()
            if target.startswith("www."):
                target = "https://" + target
            if not target.lower().startswith(("https://", "http://")):
                target = "https://" + target
            job_cell.value = target
            link_target = f"microsoft-edge:{target}" if "linkedin.com/" in target.lower() else target
            job_cell.hyperlink = link_target
            job_cell.font = Font(name="Calibri", size=11, color="0563C1", underline="single")

        resume_cell = ws.cell(n, 8)
        resume_path = Path(record["resume"]) if record["resume"] else None
        if resume_path:
            resume_cell.hyperlink = resume_path.resolve().as_uri()
            resume_cell.font = Font(name="Calibri", size=11, color="008000", underline="single")

        for col in (2, 3, 4, 6, 7, 8):
            ws.cell(n, col).alignment = Alignment(vertical="top", wrap_text=col in (7, 8))
        ws.cell(n, 9).alignment = Alignment(vertical="top", wrap_text=True)
        ws.row_dimensions[n].height = 24

    last_row = ws.max_row
    if last_row >= 2:
        # ATS score bands: strong (>70), moderate (50–70), weak (<50).
        ws.conditional_formatting.add(
            f"C2:C{last_row}",
            CellIsRule(operator="greaterThan", formula=["70"],
                       fill=PatternFill("solid", fgColor="E2F0D9"),
                       font=Font(color="006100")),
        )
        ws.conditional_formatting.add(
            f"C2:C{last_row}",
            CellIsRule(operator="between", formula=["50", "70"],
                       fill=PatternFill("solid", fgColor="FFF2CC"),
                       font=Font(color="9C6500")),
        )
        ws.conditional_formatting.add(
            f"C2:C{last_row}",
            CellIsRule(operator="lessThan", formula=["50"],
                       fill=PatternFill("solid", fgColor="FCE4D6"),
                       font=Font(color="9C0006")),
        )

        # Color by status so the state is easy to scan down the sheet.
        status_styles = {
            "Applied": ("E2F0D9", "006100"),
            "Error": ("FCE4D6", "9C0006"),
            "Stuck": ("FCE4D6", "9C0006"),
            "Draft-Saved": ("DDEBF7", "1F4E78"),
            "Draft-Local": ("DDEBF7", "1F4E78"),
            "Low-Fit": ("FFF2CC", "9C6500"),
            "Low-Match": ("FFF2CC", "9C6500"),
            "Excluded": ("E7E6E6", "666666"),
            "External": ("DDEBF7", "1F4E78"),
        }
        for status, (fill_color, font_color) in status_styles.items():
            ws.conditional_formatting.add(
                f"B2:B{last_row}",
                FormulaRule(
                    formula=[f'$B2="{status}"'],
                    fill=PatternFill("solid", fgColor=fill_color),
                    font=Font(color=font_color, bold=True),
                ),
            )

    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    ws.sheet_view.showGridLines = False
    ws.row_dimensions[1].height = 26
    for column, width in {"A": 19, "B": 16, "C": 11, "D": 10, "E": 34,
                          "F": 26, "G": 44, "H": 16, "I": 42}.items():
        ws.column_dimensions[column].width = width
    try:
        wb.save(path)
    except PermissionError:
        # Excel locks the workbook while it is open. Keep the tracker run
        # working and provide a refreshed copy the user can open immediately.
        path = DATA / "applications_updated.xlsx"
        wb.save(path)
    return path


def write_run_summary(platform, submitted=0, dry_run=False, limit=None, counts=None):
    """Write one timestamped CSV summary per run so you can measure real submissions."""
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    path = RUNS_DIR / f"{platform}_{stamp}_summary.csv"
    counts = counts or {}
    row = [
        "run_at",
        "mode",
        "limit",
        "submitted",
        "applied",
        "dry_run",
        "low_fit",
        "low_match",
        "error",
    ]
    data = [
        datetime.datetime.now().isoformat(timespec="seconds"),
        "Dry-Run" if dry_run else "live",
        str(limit or ""),
        str(submitted),
        str(counts.get("Applied", 0)),
        str(counts.get("Dry-Run", 0)),
        str(counts.get("Low-Fit", 0)),
        str(counts.get("Low-Match", 0)),
        str(counts.get("Error", 0)),
    ]
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(row)
        w.writerow(data)
    return path
