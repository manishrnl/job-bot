"""SQLite log of every job seen/applied (+ CSV export), so nothing is applied to twice and you get stats."""
import csv
import datetime
import sqlite3

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
FINAL = ("applied", "low_match", "low_fit", "external", "excluded")


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
    export_csv()


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
    applied_today = _db.execute("SELECT COUNT(*) FROM jobs WHERE status='applied' AND at >= ?", (today,)).fetchone()[0]
    avg = _db.execute("SELECT ROUND(AVG(score)) FROM jobs WHERE status='applied'").fetchone()[0]
    per_day = _db.execute("SELECT substr(at,1,10) d, COUNT(*) FROM jobs WHERE status='applied' "
                          "GROUP BY d ORDER BY d DESC LIMIT 14").fetchall()
    by_platform = dict(_db.execute("SELECT platform, COUNT(*) FROM jobs WHERE status='applied' GROUP BY platform").fetchall())
    return dict(by_status=by_status, applied_today=applied_today, avg_score=avg, per_day=per_day,
                by_platform=by_platform, total_applied=by_status.get("applied", 0))


def export_csv():
    with open(DATA / "applications.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(COLS)
        w.writerows(_db.execute(f"SELECT {','.join(COLS)} FROM jobs ORDER BY at DESC"))


def write_run_summary(platform, submitted=0, dry_run=False, limit=None, counts=None):
    """Write one timestamped CSV summary per run so you can measure real submissions."""
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    path = RUNS_DIR / f"{platform}_{stamp}_summary.csv"
    counts = counts or {}
    row = [
        "platform",
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
        platform,
        datetime.datetime.now().isoformat(timespec="seconds"),
        "dry_run" if dry_run else "live",
        str(limit or ""),
        str(submitted),
        str(counts.get("applied", 0)),
        str(counts.get("dry_run", 0)),
        str(counts.get("low_fit", 0)),
        str(counts.get("low_match", 0)),
        str(counts.get("error", 0)),
    ]
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(row)
        w.writerow(data)
    return path
