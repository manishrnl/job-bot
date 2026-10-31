# jobbot

**Turn your LinkedIn profile into a tailored, ATS-friendly resume for every job, and auto-apply on LinkedIn Easy Apply.**

You give it your LinkedIn profile PDF once. For each matching job it:

1. finds fresh postings (e.g. posted in the last hour) over LinkedIn's public job pages,
2. screens them in seconds, so it never wastes time on jobs that clearly don't fit,
3. writes a resume for that exact job description, reviewed the way a senior technical recruiter would,
4. renders a clean one-page PDF that ATS parsers read correctly,
5. opens Easy Apply in a real browser, uploads that PDF, answers the questions and submits,
6. logs every job with its link, ATS score and status so you can see your stats.

No API keys, and no paid API calls. The AI runs through an AI CLI you're already logged into (see below).

> **Read [Risks](#risks) before running it live.** Automating LinkedIn breaks its Terms of Service.

---

## Supported AI backends

jobbot calls an AI command-line tool you have already logged into. It needs at least one of these:

| Backend | Cost | Install | Log in once |
|---|---|---|---|
| **Claude Code** (recommended, best writing) | Uses your Claude Pro/Max plan | `npm install -g @anthropic-ai/claude-code` | run `claude` and follow the login |
| **Gemini CLI** | Free tier with a Google account | `npm install -g @google/gemini-cli` | run `gemini` and pick "Login with Google" |
| **Codex CLI** | Uses your ChatGPT plan | `npm install -g @openai/codex` | `codex login` |
| **Ollama** (fully offline, free) | Free, runs on your machine | [ollama.com/download](https://ollama.com/download), then `ollama pull llama3.1` | not needed |

With `backend: auto` in `config.yaml`, jobbot uses the first one it finds, in this order:
claude, gemini, codex, ollama. To force one, set `ai.backend: gemini` (or `claude`, `codex`, `ollama`).

With Claude, the long writing uses `ai.claude_model` (default `sonnet`) and quick tasks use
`ai.claude_fast_model` (default `haiku`). Small local Ollama models write noticeably weaker resumes.
Use `llama3.1:70b` or `qwen2.5:32b` if your machine can run them.

---

## Requirements

- Python 3.10+
- Node.js 18+ (only needed to install the Claude, Gemini or Codex CLI)
- Google Chrome (recommended; otherwise a bundled Chromium is used)

## Setup

### macOS / Linux

```bash
git clone https://github.com/manishrnl/job-bot.git && cd jobbot
./setup.sh                                  # venv + dependencies + headless Chromium for PDFs
```

### Windows (PowerShell)

```powershell
git clone https://github.com/manishrnl/job-bot.git; cd jobbot
powershell -ExecutionPolicy Bypass -File setup.ps1
```

On Windows, use `.\jb` (it runs `jb.cmd`) wherever this README says `./jb`.

### First run (all platforms)

```bash
# 1. LinkedIn > your profile > More > Save to PDF. Then:
.\jb init ~/Downloads/Profile.pdf          # add an old resume too: ./jb init Profile.pdf old_cv.pdf
                                           # it asks for anything the PDF lacks (phone, CTC, projects...)
# If Ollama times out during PDF extraction, use a smaller/faster model or switch to Claude/Gemini:
#   ollama pull llama3.1
#   # or edit config.yaml: ai.backend: claude   / ai.ollama_model: llama3.1

# 2. Check data/profile.json and config.yaml (CTC in LPA, notice period, job titles, location)

# 3. Build a master resume
.\jb build --role "Backend Engineer"
.\jb use-chrome --profile "Manish"   # copy logins from your Chrome (quit Chrome first)
.\jb login linkedin                  # or log in once in the bot's own browser
.\jb apply linkedin -n 1

# 5. Try it without submitting anything
# .\jb apply linkedin --dry-run -n 3

# -n = “maximum number of applications in this run.” So -n 5 means “do not exceed 5 applications during this round.”
```

---

## Daily use

```bash
.\jb                                             # interactive menu
.\jb apply linkedin -n 10                        # apply to 10 jobs (filters from config.yaml)
.\jb apply linkedin -t 1h -n 10                  # only jobs posted in the last hour
.\jb apply linkedin -k "Node.js Developer" "Backend Engineer" -l "Bengaluru" -t 24h
.\jb apply url https://boards.greenhouse.io/x/jobs/1   # any other site: pre-fills, you click submit
.\jb tailor --url https://www.linkedin.com/jobs/view/123/   # resume only, for one job
.\jb tailor --jd jd.txt --company Acme --title "SDE 2"
.\jb score my_resume.pdf --jd jd.txt             # ATS score for any resume
.\jb stats                                       # applied total / today / avg score / last 14 days
.\jb history --status applied                    # applied jobs with links
.\jb clean                                       # delete old generated resumes, debug files, answer cache
```

### Commands

| Command | What it does |
|---|---|
| `init <pdf...>` | Import your LinkedIn PDF (plus optional old resumes) into `data/profile.json`, then ask for missing details |
| `complete` | Ask again for details the PDF didn't have (phone, CTC, projects, education years, target roles) |
| `build [--role]` | Polished general resume with no job description |
| `tailor --jd/--url` | Resume tailored to one job, with an ATS report |
| `score <resume>` | ATS-score any PDF or TXT resume against a job description |
| `use-chrome [--profile]` | Copy a Chrome profile (with its logins) into the bot's browser |
| `login <site>` | Log in once in the bot's browser (linkedin / hirist / naukri / any URL) |
| `apply linkedin` | Full pipeline: discover, filter, tailor, Easy Apply |
| `apply hirist` | Hirist (beta, sequential) |
| `apply url <URL>` | Any job page: tailor, then pre-fill the form; you review and submit |
| `stats` / `history` | Totals, per-day chart, every job with link, status, ATS score and fit score |
| `clean [--history] [--logout] [--all]` | Delete generated data. By default it keeps history and your login |

Useful `apply` flags: `-n` limit, `-t` posted within (`30m`, `1h`, `6h`, `24h`, `3d`, `1w`),
`-k` keywords, `-l` location, `--dry-run`.

---

## How it works

```
LinkedIn public job pages (HTTP, no login, ~1s for 10 jobs)
   │  title/company exclusions, external-apply jobs, near-zero skill overlap   -> skipped instantly, no AI
   ▼
Fit check (small model, ~3s)        partial matches pass; only a clearly different stack is skipped
   ▼
Tailor (3 parallel workers)         recruiter-style rewrite + JD keywords + local ATS score
   ▼  queue
Easy Apply (one real browser)       upload PDF, answer questions, Next / Review / Submit
   ▼
data/jobs.db + data/applications.xlsx (formatted history with clickable job/resume links)
```

The browser applies to one job while the next resumes are being written. The pause between
submissions overlaps with AI work, so it costs almost nothing.

### The resume

- **Recruiter review**: the model is told to write as a senior technical recruiter. That means a
  7-second scan of headline, latest title, stack and numbers, then the most relevant work first.
- **ATS keywords**: required and nice-to-have terms from the job description, spelled exactly as the
  JD spells them, placed in the headline, summary, skills and bullets.
- **ATS score (0-100)**: computed locally, so it's repeatable. Keywords count for 60 points. The rest
  covers standard sections, contact info, numbers in bullets, bullet length, action verbs and
  AI-sounding words.
- **Human tone**: about 50 phrases that read as ChatGPT ("spearheaded", "leveraged",
  "results-driven", em dashes and so on) are banned, and the score checks for them.
- **Honest**: the resume only uses facts from your profile. JD requirements you don't have are listed
  as "gaps", not invented.
- **Layout**: one column, text-based PDF, standard headings. It auto-fits to one page (under 7 years
  of experience), and a section heading is never left alone at the bottom of a page.

### Form answers

Answers come from these sources, in order:

1. Contact fields, taken from your profile.
2. Your rules in `config.yaml > answers`, such as CTC (in LPA, converted when a form asks for rupees)
   and notice period.
3. The AI.

The AI answers skill questions generously. If you know Node.js, "experience with Kafka?" in the same
field gets *Yes / 1 year*. Only a clearly unrelated field (SAP, iOS, embedded) gets *No*. For
logistics questions (office days, relocation, joining time) it picks the answer that keeps the
application moving. AI answers are cached in `data/answers_cache.json`; review and edit it any time.

---

## Configuration (`config.yaml`)

| Key | Default | Meaning |
|---|---|---|
| `search.keywords` | | Job titles to search |
| `search.location` | `India` | Location filter |
| `search.posted_within` | `24h` | `30m`, `1h`, `6h`, `24h`, `3d`, `1w`. Fresher posts have fewer applicants |
| `search.exclude_title_words` | | Skip titles containing these (e.g. `.net`, `java developer`) |
| `apply.max_per_run` | `10` | Applications per run |
| `apply.parallel_resumes` | `3` | AI workers writing resumes in parallel |
| `apply.min_skill_overlap` | `2` | Instant skip only when fewer of your skills appear in the JD |
| `apply.min_fit` | `40` | Quick AI screen; only clearly different stacks fall below it |
| `apply.min_match_score` | `50` | Skip if even the tailored resume scores below this |
| `apply.delay_seconds` | `[20, 45]` | Minimum gap between submissions |
| `resume.pages` | `auto` | `auto` (1 page under 7 years of experience), `1`, or `2` |
| `resume.refine_passes` | `1` | Extra rewrite, run only when it can actually help |
| `answers` | | Your fixed answers: CTC in LPA, notice period, relocation... |

---

## Where your data lives

| Path | Contents | In git? |
|---|---|---|
| `config.yaml` | Your answers, CTC, preferences | ignored |
| `data/profile.json` | Your imported profile | ignored |
| `data/browser_profile/` | The bot's browser, **including your logins** | ignored. Never share it |
| `data/jobs.db`, `data/applications.xlsx` | Application history and stats | ignored |
| `output/` | Generated resumes (`.pdf`, `.txt`, `.html`, `.json`) | ignored |

Clear generated files with `./jb clean`, or start completely fresh with `./jb clean --all`.

---

## Risks

- **LinkedIn's Terms of Service forbid automation**, so your account can be restricted. The defaults
  keep the risk down: 10 applications per run, a gap between submissions, your real Chrome, and a
  manual login. Raising them a lot or running all day increases the risk. You use this at your own risk.
- `use-chrome` copies **all** logins from that Chrome profile into `data/browser_profile/`. A Chrome
  profile used only for job sites is safer.
- Site markup changes. When a step can't be completed, the bot saves a local recovery copy under
  `data/drafts/` and uses LinkedIn's save-draft action when available. It does not submit or discard
  an incomplete application. A screenshot and HTML are also saved to `data/debug/` for troubleshooting.

## Troubleshooting

| Problem | Fix |
|---|---|
| `No AI CLI found` | Install and log in to one backend (table above) |
| `Not logged in` / login page keeps appearing | `./jb login linkedin`. The session is saved in `data/browser_profile` |
| `use-chrome` copied the profile but you're still logged out | Pick the profile that's actually logged in to LinkedIn (`./jb use-chrome` lists them); on macOS allow the keychain prompt. Otherwise use `./jb login linkedin` |
| Status `stuck` / `error` | See `data/debug/<job id>.png`. Usually a new form field or a LinkedIn UI change |
| Too many jobs skipped | Lower `apply.min_fit` / `min_skill_overlap`, or remove words from `exclude_title_words` |
| Windows: `running scripts is disabled` | Use `powershell -ExecutionPolicy Bypass -File setup.ps1` |
| Windows: `python` not found | Install Python from python.org and tick "Add python.exe to PATH" |

## License

MIT
