import json
import subprocess
import unittest
from pathlib import Path
from unittest import mock

from jobbot import ai
from jobbot import browser


class TestAiOllama(unittest.TestCase):
    def test_ollama_command_uses_prompt_as_argument(self):
        argv, stdin = ai._command("ollama", "hello world")
        self.assertEqual(argv, ["ollama", "run", ai.CFG["ai"].get("ollama_model", "llama3.1"), "hello world"])
        self.assertIsNone(stdin)

    def test_ask_uses_non_interactive_ollama_invocation(self):
        model = ai.CFG["ai"].get("ollama_model", "llama3.1")
        completed = subprocess.CompletedProcess(
            args=["ollama", "run", model, "hello world"],
            returncode=0,
            stdout="response",
            stderr="",
        )

        with mock.patch.object(ai, "backend", return_value="ollama"), \
             mock.patch.object(ai.shutil, "which", side_effect=lambda p: p), \
             mock.patch.object(ai.subprocess, "run", return_value=completed) as run_mock:
            self.assertEqual(ai.ask("hello world"), "response")

        run_mock.assert_called_once()
        argv = run_mock.call_args[0][0]
        self.assertEqual(argv, ["ollama", "run", model, "hello world"])
        self.assertIsNone(run_mock.call_args.kwargs["input"])

    def test_ask_fails_with_actionable_ollama_model_error(self):
        proc = subprocess.CompletedProcess(
            args=["ollama", "show", "qwen3.5:4b"],
            returncode=1,
            stdout="",
            stderr="model not found",
        )

        with mock.patch.object(ai, "backend", return_value="ollama"), \
             mock.patch.object(ai, "_command", return_value=(['ollama', 'run', 'qwen3.5:4b', 'hello world'], None)), \
             mock.patch.object(ai.shutil, "which", side_effect=lambda p: p), \
             mock.patch.object(ai.subprocess, "run", return_value=proc) as run_mock:
            with self.assertRaisesRegex(SystemExit, r"ollama pull|ai\.ollama_model|switch backends"):
                ai.ask("hello world")

        self.assertEqual(run_mock.call_count, 1)

    def test_ask_fails_with_actionable_ollama_timeout_error(self):
        with mock.patch.object(ai, "backend", return_value="ollama"), \
             mock.patch.object(ai, "_command", return_value=(['ollama', 'run', 'qwen3.5:4b', 'hello world'], None)), \
             mock.patch.object(ai.shutil, "which", side_effect=lambda p: p), \
             mock.patch.object(ai.subprocess, "run", side_effect=subprocess.TimeoutExpired(cmd=['ollama', 'run', 'qwen3.5:4b'], timeout=300)):
            with self.assertRaisesRegex(SystemExit, r"timed out|smaller/faster|claude|gemini|codex"):
                ai.ask("hello world")

    def test_ask_fails_with_actionable_claude_credit_error(self):
        proc = subprocess.CompletedProcess(
            args=['claude', '-p', 'hello world'],
            returncode=1,
            stdout='',
            stderr='Credit balance is too low',
        )

        with mock.patch.object(ai, "backend", return_value="claude"), \
             mock.patch.object(ai, "_command", return_value=(['claude', '-p', 'hello world'], 'hello world')), \
             mock.patch.object(ai.shutil, "which", side_effect=lambda p: p), \
             mock.patch.object(ai.subprocess, "run", return_value=proc):
            with self.assertRaisesRegex(SystemExit, r"Claude.*credits|ai\.backend|ollama|gemini|codex"):
                ai.ask("hello world")

    def test_ask_uses_openai_compatible_api_backend(self):
        response = {
            "choices": [{"message": {"content": "ok"}}]
        }
        fake = mock.Mock()
        fake.__enter__ = mock.Mock(return_value=fake)
        fake.__exit__ = mock.Mock(return_value=None)
        fake.read = mock.Mock(return_value=json.dumps(response).encode("utf-8"))

        with mock.patch.object(ai, "backend", return_value="api"), \
             mock.patch.object(ai, "_api_cfg", return_value={
                 "api_key": "test-key",
                 "api_base": "https://api.example.com/v1",
                 "api_model": "gemini-2.5-flash",
             }), \
             mock.patch.object(ai.urllib.request, "urlopen", return_value=fake) as urlopen:
            self.assertEqual(ai.ask("hello world"), "ok")

        urlopen.assert_called_once()


class TestBrowser(unittest.TestCase):
    def test_chrome_profiles_missing_profile_dir_returns_empty(self):
        with mock.patch.object(browser, "CHROME_DIR", Path("/definitely/missing/chrome")):
            self.assertEqual(browser.chrome_profiles(), [])


if __name__ == "__main__":
    unittest.main()
