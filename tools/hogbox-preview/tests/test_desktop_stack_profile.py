from __future__ import annotations

import json

import unittest
from unittest.mock import MagicMock

from hogbox_preview.backend import ExecResult, PreviewBackend
from hogbox_preview.stack import DesktopProfileConfig, PostHogPreviewStack


class DesktopProfileStack(unittest.TestCase):
    def test_desktop_profile_publishes_the_checked_out_revision_before_web_starts(self) -> None:
        backend = MagicMock(spec=PreviewBackend)
        backend.web_port = 8000
        backend.web_url = "https://preview.example.com/"
        backend.run_long.return_value = ExecResult(0, "DESKTOP_SEED_OK", "")
        backend.exec.return_value = ExecResult(0, "DEEP_HEALTH_OK\nDESKTOP_READY_OK", "")
        stack = PostHogPreviewStack(
            backend,
            branch="pull/123/head",
            seed_demo_data=False,
            desktop_profile=DesktopProfileConfig(pr_number=123, commit_sha="1" * 40),
        )
        stack.bring_up()
        files = {call.args[0]: call.args[1] for call in backend.write_file.call_args_list}
        override = files["/home/hog/posthog/docker-compose.preview.yml"]
        self.assertIn("./desktop-preview:/code/staticfiles/desktop-preview", override)
        self.assertIn("DESKTOP_PREVIEW=1", override)
        metadata = json.loads(files["/home/hog/posthog/desktop-preview/deployment.json"])
        self.assertEqual(metadata["commitSha"], "1" * 40)
        commands = [call.args[0] for call in backend.run_long.call_args_list]
        checkout = next(command for command in commands if "fetch --depth" in command)
        self.assertIn("origin " + "1" * 40, checkout)
        self.assertNotIn("pull/123/head", checkout)
        seed = next(command for command in commands if "manage.py shell" in command)
        self.assertIn("< /home/hog/posthog/desktop-oauth-seed.py", seed)
        calls = backend.method_calls
        metadata_write = next(
            i for i, call in enumerate(calls) if call[0] == "write_file" and call.args[0].endswith("deployment.json")
        )
        web_start = next(
            i for i, call in enumerate(calls) if call[0] == "run_long" and "up -d --no-build web" in call.args[0]
        )
        self.assertLess(metadata_write, web_start)

    def test_readiness_surfaces_guest_failures(self) -> None:
        backend = MagicMock(spec=PreviewBackend)
        backend.web_port = 8000
        backend.exec.return_value = ExecResult(1, "", "Desktop access denied")
        cfg = DesktopProfileConfig(pr_number=123, commit_sha="1" * 40)
        stack = PostHogPreviewStack(backend, desktop_profile=cfg)
        with self.assertRaisesRegex(RuntimeError, "Desktop access denied"):
            stack._run_desktop_readiness(cfg)


if __name__ == "__main__":
    unittest.main()
