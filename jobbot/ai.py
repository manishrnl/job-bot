"""AI calls through the configured API or a configured CLI backend.

API requests always use the single model named by ``ai.api_model`` in config.yaml.
"""
import json
import os
import re
import shutil
import subprocess
import tempfile
import urllib.request

from .config import CFG

ORDER = ["claude", "gemini", "codex", "ollama"]
_backend = None


def _api_cfg():
    ai = CFG["ai"]
    api_key = ai.get("api_key") or os.getenv("AI_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None
    api_model = str(ai.get("api_model") or "").strip()
    if not api_model:
        raise SystemExit("Set ai.api_model in config.yaml; API requests do not choose a model automatically.")
    return {
        "api_key": api_key,
        "api_base": (ai.get("api_base") or os.getenv("AI_API_BASE") or "https://api.openai.com/v1").rstrip("/"),
        "api_model": api_model,
    }


def backend():
    global _backend
    if _backend:
        return _backend
    want = CFG["ai"].get("backend", "auto")
    if want in {"api", "openai", "openai_compatible", "third_party"}:
        if _api_cfg() is None:
            raise SystemExit(
                "AI backend is set to an API key flow, but no ai.api_key was found. "
                "Set ai.api_key and ai.api_base in config.yaml or export AI_API_KEY."
            )
        _backend = "api"
        return "api"
    candidates = ORDER if want == "auto" else [want]
    for name in candidates:
        if shutil.which(name):
            _backend = name
            return name
    if _api_cfg() is not None:
        _backend = "api"
        return "api"
    raise SystemExit(
        f"No AI CLI found (tried: {', '.join(candidates)}).\n"
        "Install one: Claude Code (npm i -g @anthropic-ai/claude-code), "
        "Gemini CLI (npm i -g @google/gemini-cli), Codex (npm i -g @openai/codex) or Ollama. "
        "Or set ai.backend: api with ai.api_key and ai.api_base for an OpenAI-compatible provider."
    )


def _command(name, prompt, fast=False):
    """Return (argv, stdin) for a one-shot, non-interactive call."""
    ai = CFG["ai"]
    if name == "api":
        return None, None
    if name == "claude":
        # Skip MCP servers, skills and user settings: faster startup, plain text in/out.
        argv = ["claude", "-p", "--output-format", "text", "--strict-mcp-config",
                "--disable-slash-commands", "--setting-sources", ""]
        model = ai.get("claude_fast_model") if fast else ai.get("claude_model")
        if not model:
            raise SystemExit("Set the Claude model in config.yaml before selecting the Claude CLI backend.")
        argv += ["--model", model]
        return argv, prompt
    if name == "gemini":
        return ["gemini", "-p", prompt], None
    if name == "codex":
        return ["codex", "exec", "--skip-git-repo-check", "-"], prompt
    if name == "ollama":
        # Ollama's non-interactive CLI expects the prompt as a positional argument,
        # not as stdin. Passing it via stdin triggers the interactive TUI and the
        # spinner output seen in the traceback.
        model = ai.get("ollama_model")
        if not model:
            raise SystemExit("Set ai.ollama_model in config.yaml before selecting the Ollama backend.")
        return ["ollama", "run", model, prompt], None
    raise SystemExit(f"Unknown AI backend: {name}")


def _ask_api(prompt):
    cfg = _api_cfg()
    if cfg is None:
        raise SystemExit("No API credentials found. Set ai.api_key and ai.api_base in config.yaml (or AI_API_KEY / AI_API_BASE).")
    api_base = cfg["api_base"]
    endpoint = api_base if api_base.endswith("/chat/completions") else api_base + "/chat/completions"
    payload = {
        "model": cfg["api_model"],
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
    }
    req = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {cfg['api_key']}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=CFG["ai"].get("timeout", 300)) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:  # pragma: no cover - exercised via unit test with mocked urlopen
        raise RuntimeError(f"api failed: {exc}") from exc
    try:
        return body["choices"][0]["message"]["content"].strip()
    except Exception:
        raise RuntimeError(f"api failed: unexpected response {body!r}")


def ask(prompt, fast=False):
    """Send a prompt; the API backend uses ai.api_model for every call."""
    name = backend()
    if name == "api":
        return _ask_api(prompt)
    argv, stdin = _command(name, prompt, fast)
    argv[0] = shutil.which(argv[0]) or argv[0]  # Windows: npm installs claude.cmd / gemini.cmd
    model = argv[2] if name == "ollama" and len(argv) > 2 else None
    # Run in an empty temp dir so the CLI doesn't pick up project files as context.
    with tempfile.TemporaryDirectory() as cwd:
        try:
            r = subprocess.run(argv, input=stdin, capture_output=True, text=True, encoding="utf-8", errors="replace",
                               timeout=CFG["ai"].get("timeout", 300), cwd=cwd)
        except subprocess.TimeoutExpired:
            if name == "ollama":
                model_name = model or CFG["ai"].get("ollama_model", "configured local model")
                raise SystemExit(
                    f"Ollama timed out while running '{model_name}'. This is common on Windows with large models. "
                    "Install a local model and set ai.ollama_model, or switch backends. "
                    "or set ai.backend to 'claude', 'gemini', or 'codex' in config.yaml."
                )
            raise RuntimeError(f"{name} timed out")
    out = (r.stderr or r.stdout or "").strip()
    if r.returncode != 0:
        msg = out[:500]
        lower = msg.lower()
        if name == "claude" and any(k in lower for k in ["credit balance is too low", "insufficient credits", "quota exceeded", "billing", "payment required"]):
            raise SystemExit(
                "Claude is out of credits or billing is blocked. Switch ai.backend to 'ollama', 'gemini', or 'codex' "
                "in config.yaml, or top up your Claude plan before retrying."
            )
        if name == "ollama" and model:
            if "not found" in lower or "manifest" in lower or "no such host" in lower or "lookup" in lower:
                raise SystemExit(
                    f"Ollama model '{model}' is unavailable on this machine. Run 'ollama pull {model}' "
                    "(or set ai.ollama_model in config.yaml to a local model). If DNS/internet is blocked, "
                    "switch ai.backend to claude / gemini / codex or install a different local model."
                )
        raise RuntimeError(f"{name} failed: {msg}")
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
