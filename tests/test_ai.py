import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from jobbot import ai
from jobbot import browser
from jobbot import render
from jobbot import tailor
from jobbot import tracker


class TestAiOllama(unittest.TestCase):
    model = "test-local-model"

    def setUp(self):
        self.ai_settings = mock.patch.dict(ai.CFG["ai"], {"ollama_model": self.model})
        self.ai_settings.start()
        self.addCleanup(self.ai_settings.stop)

    def test_ollama_command_uses_prompt_as_argument(self):
        argv, stdin = ai._command("ollama", "hello world")
        self.assertEqual(argv, ["ollama", "run", self.model, "hello world"])
        self.assertIsNone(stdin)

    def test_ask_uses_non_interactive_ollama_invocation(self):
        model = self.model
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
            args=["ollama", "show", self.model],
            returncode=1,
            stdout="",
            stderr="model not found",
        )

        with mock.patch.object(ai, "backend", return_value="ollama"), \
             mock.patch.object(ai, "_command", return_value=(['ollama', 'run', self.model, 'hello world'], None)), \
             mock.patch.object(ai.shutil, "which", side_effect=lambda p: p), \
             mock.patch.object(ai.subprocess, "run", return_value=proc) as run_mock:
            with self.assertRaisesRegex(SystemExit, r"ollama pull|ai\.ollama_model|switch backends"):
                ai.ask("hello world")

        self.assertEqual(run_mock.call_count, 1)

    def test_ask_fails_with_actionable_ollama_timeout_error(self):
        with mock.patch.object(ai, "backend", return_value="ollama"), \
             mock.patch.object(ai, "_command", return_value=(['ollama', 'run', self.model, 'hello world'], None)), \
             mock.patch.object(ai.shutil, "which", side_effect=lambda p: p), \
             mock.patch.object(ai.subprocess, "run", side_effect=subprocess.TimeoutExpired(cmd=['ollama', 'run', self.model], timeout=300)):
            with self.assertRaisesRegex(SystemExit, r"timed out|local model|switch backends"):
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
                 "api_model": "configured-test-model",
             }), \
             mock.patch.object(ai.urllib.request, "urlopen", return_value=fake) as urlopen:
            self.assertEqual(ai.ask("hello world"), "ok")

        urlopen.assert_called_once()


class TestBrowser(unittest.TestCase):
    def test_chrome_profiles_missing_profile_dir_returns_empty(self):
        with mock.patch.object(browser, "CHROME_DIR", Path("/definitely/missing/chrome")):
            self.assertEqual(browser.chrome_profiles(), [])

    def test_session_reports_locked_profile_actionably(self):
        class FakeSyncPlaywright:
            def __enter__(self):
                return self
            def __exit__(self, exc_type, exc, tb):
                return False
            class chromium:
                @staticmethod
                def launch_persistent_context(*args, **kwargs):
                    raise RuntimeError("Opening in existing browser session. This usually means that the profile is already in use by another instance of Chromium.")

        with mock.patch.object(browser, "CFG", {"apply": {"headless": False}}), \
             mock.patch.object(browser, "sync_playwright", return_value=FakeSyncPlaywright()):
            with self.assertRaisesRegex(SystemExit, r"Close all Chrome|Chromium|browser session|kill"):
                with browser.session():
                    pass


class TestExperienceGate(unittest.TestCase):
    def test_rejects_jobs_needing_more_than_two_years_for_fresher(self):
        profile = {"headline": "Java Backend Developer", "experience": [], "skills": ["Java", "Spring Boot"]}
        jd = "We need a Java Developer with 5+ years of experience in Spring Boot and Kafka."
        self.assertEqual(tailor.experience_gate(profile, jd), (0, "requires 5+ years"))

    def test_allows_fresher_jobs_up_to_two_years(self):
        profile = {"headline": "Java Backend Developer", "experience": [], "skills": ["Java", "Spring Boot"]}
        jd = "Freshers or candidates with up to 2 years of experience in Java and Spring Boot."
        self.assertEqual(tailor.experience_gate(profile, jd), (100, "freshers/0-2y"))


class TestRunArtifacts(unittest.TestCase):
    def test_render_save_creates_timestamped_run_directory(self):
        resume = {"name": "Manish Kumar", "experience": []}

        def fake_pdf(_pw, _resume, path):
            path.write_bytes(b"fake pdf")
            return "<html>ok</html>"

        with mock.patch.object(render, "_pdf", side_effect=fake_pdf), \
             mock.patch.object(render.ats, "resume_text", return_value="resume text"):
            pdf_path = render.save(resume, "master", pw=mock.Mock())
        self.assertTrue(pdf_path.exists())
        self.assertIn("Manish_master_", pdf_path.name)
        self.assertEqual(pdf_path.parent, render.OUT)

    def test_tracker_write_run_summary_creates_timestamped_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            with mock.patch.object(tracker, "DATA", tmp_path), \
                 mock.patch.object(tracker, "RUNS_DIR", tmp_path / "runs"):
                tracker.RUNS_DIR.mkdir(exist_ok=True)
                tracker.write_run_summary("linkedin", submitted=2, dry_run=True, limit=3)
                runs = list((tmp_path / "runs").glob("linkedin_*_summary.csv"))
            self.assertEqual(len(runs), 1)
            self.assertTrue(runs[0].exists())
            self.assertIn("linkedin_", runs[0].name)


class TestFormfillResumeUpload(unittest.TestCase):
    def test_chooses_resume_file_input_over_cover_letter(self):
        files = [
            {"label": "Cover letter", "name": "cover_letter", "type": "file"},
            {"label": "Upload resume", "name": "resume", "type": "file"},
        ]
        self.assertLess(formfill._resume_file_rank(files[0], files), 0)
        self.assertGreater(formfill._resume_file_rank(files[1], files), 0)

    def test_uses_single_file_input_as_fallback(self):
        files = [{"label": "Portfolio", "name": "portfolio", "type": "file"}]
        self.assertGreater(formfill._resume_file_rank(files[0], files), 0)

    def test_uses_first_file_when_no_resume_hint_exists(self):
        files = [
            {"label": "Attachment 1", "name": "upload_1", "type": "file"},
            {"label": "Attachment 2", "name": "upload_2", "type": "file"},
        ]
        self.assertEqual(formfill._resume_file_rank(files[0], files), 1)
        self.assertEqual(formfill._resume_file_rank(files[1], files), 0)


from jobbot import formfill


if __name__ == "__main__":
    unittest.main()
