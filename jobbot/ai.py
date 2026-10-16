"""AI calls through CLIs you already have logged in (Claude Code, Gemini CLI, Codex CLI, Ollama).

No API keys and no paid API: each call shells out to the CLI, which uses your own
subscription / free tier / local model.
"""
import json
import re
import shutil
import subprocess
import tempfile

from .config import CFG

ORDER = ["claude", "gemini", "codex", "ollama"]
_backend = None


def backend():
    global _backend
    if _backend:
        return _backend
    want = CFG["ai"].get("backend", "auto")
    candidates = ORDER if want == "auto" else [want]
    for name in candidates:
        if shutil.which(name):
            _backend = name
            return name
    raise SystemExit(
        f"No AI CLI found (tried: {', '.join(candidates)}).\n"
        "Install one: Claude Code (npm i -g @anthropic-ai/claude-code), "
        "Gemini CLI (npm i -g @google/gemini-cli), Codex (npm i -g @openai/codex) or Ollama."
    )


def _command(name, prompt, fast=False):
    """Return (argv, stdin) for a one-shot, non-interactive call."""
    ai = CFG["ai"]
    if name == "claude":
        # Skip MCP servers, skills and user settings: faster startup, plain text in/out.
        argv = ["claude", "-p", "--output-format", "text", "--strict-mcp-config",
                "--disable-slash-commands", "--setting-sources", ""]
        model = ai.get("claude_fast_model") if fast else ai.get("claude_model")
        if model:
            argv += ["--model", model]
        return argv, prompt
    if name == "gemini":
        return ["gemini", "-p", prompt], None
    if name == "codex":
        return ["codex", "exec", "--skip-git-repo-check", "-"], prompt
    if name == "ollama":
        return ["ollama", "run", ai.get("ollama_model", "llama3.1")], prompt
    raise SystemExit(f"Unknown AI backend: {name}")


def ask(prompt, fast=False):
    """fast=True uses the small model (form answers, keyword lists)."""
    name = backend()
    argv, stdin = _command(name, prompt, fast)
    argv[0] = shutil.which(argv[0]) or argv[0]  # Windows: npm installs claude.cmd / gemini.cmd
    # Run in an empty temp dir so the CLI doesn't pick up project files as context.
    with tempfile.TemporaryDirectory() as cwd:
        try:
            r = subprocess.run(argv, input=stdin, capture_output=True, text=True, encoding="utf-8", errors="replace",
                               timeout=CFG["ai"].get("timeout", 300), cwd=cwd)
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"{name} timed out")
    if r.returncode != 0:
        raise RuntimeError(f"{name} failed: {(r.stderr or r.stdout).strip()[:500]}")
    return r.stdout.strip()


def _parse_json(text):
    text = re.sub(r"```(?:json)?", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object in AI output")
    return json.loads(text[start:end + 1])


def ask_json(prompt, fast=False):
    out = ask(prompt + "\n\nReturn ONLY one valid JSON object. No markdown fences, no commentary.", fast)
    try:
        return _parse_json(out)
    except (ValueError, json.JSONDecodeError):
        fixed = ask("Convert the following into ONE valid JSON object. Output only the JSON.\n\n" + out, True)
        return _parse_json(fixed)
