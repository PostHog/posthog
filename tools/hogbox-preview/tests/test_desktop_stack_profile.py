"""Unit tests for the desktop preview profile on the stack.

Self-contained: no network, no live box. A recording fake backend captures the
scripts the stack ships into the guest, so the profile can be asserted without
provisioning anything: the OAuth seed runs through `compose run` (the guest's
Django), the metadata document lands in staticfiles/desktop-preview, and the
readiness gate greps the marker the script prints.

    cd tools/hogbox-preview && python -m unittest tests.test_desktop_stack_profile
"""

from __future__ import annotations

import json

import unittest

try:
    from hogbox_preview.backend import ExecResult
    from hogbox_preview.stack import DesktopProfileConfig, PostHogPreviewStack

    HAVE_SDK = True
except ImportError:
    HAVE_SDK = False


class _RecordingBackend:
    """Duck-typed PreviewBackend: records every write/exec the stack issues."""

    def __init__(self, responses: dict[str, str] | None = None):
        self.web_port = 8000
        self.files: dict[str, str] = {}
        self.commands: list[str] = []
        self._responses = responses or {}

    @property
    def web_url(self) -> str:
        return "https://pen-abc.boxes.hogland.prod-us.posthog.dev/"

    def provision(self) -> None:
        pass

    def exec(self, command: str, *, timeout: int = 120) -> ExecResult:
        self.commands.append(command)
        for needle, out in self._responses.items():
            if needle in command:
                return ExecResult(returncode=0, stdout=out, stderr="")
        return ExecResult(returncode=0, stdout="", stderr="")

    def write_file(self, remote_path: str, content: bytes | str) -> None:
        self.files[remote_path] = content if isinstance(content, str) else content.decode()

    def run_long(self, script, *, name, timeout=1800, interval=3) -> ExecResult:
        self.commands.append(script)
        return ExecResult(returncode=0, stdout='{"oauth_app": {"client_id": "x"}}', stderr="")

    def destroy(self) -> None:
        pass


@unittest.skipUnless(HAVE_SDK, "posthog-hogland SDK not installed")
class DesktopProfileStack(unittest.TestCase):
    def _stack(self, backend, **kwargs):
        return PostHogPreviewStack(
            backend,
            desktop_profile=DesktopProfileConfig(
                pr_number=123,
                commit_sha="1" * 40,
                **kwargs,
            ),
        )

    def test_profile_config_rejects_a_malformed_sha(self):
        with self.assertRaises(ValueError):
            DesktopProfileConfig(pr_number=123, commit_sha="abc123")
        with self.assertRaises(ValueError):
            DesktopProfileConfig(pr_number=0, commit_sha="1" * 40)

    def test_metadata_document_lands_in_staticfiles(self):
        backend = _RecordingBackend()
        # The serving probe (`cat /tmp/meta.json`) must return EXACTLY the
        # document the stack wrote. The fake backend captures the heredoc body
        # when the stack writes it and replays it for the probe; the equality
        # gate in the stack then verifies it served what it wrote.
        backend.heredoc_body = None
        backend._responses = {
            "-w '%{http_code}'": "200",
        }
        stack = self._stack(backend)

        def recording_exec(cmd, timeout=60):
            backend.commands.append(cmd)
            if "cat > staticfiles/desktop-preview/deployment.json" in cmd:
                backend.heredoc_body = cmd.split("<<'EOF'\n", 1)[1].split("\nEOF", 1)[0]
            if "cat /tmp/meta.json" in cmd:
                return ExecResult(returncode=0, stdout=backend.heredoc_body or "", stderr="")
            for needle, out in backend._responses.items():
                if needle in cmd:
                    return ExecResult(returncode=0, stdout=out, stderr="")
            return ExecResult(returncode=0, stdout="", stderr="")

        backend.exec = recording_exec
        stack._publish_deployment_metadata(stack.desktop_profile)
        self.assertIsNotNone(backend.heredoc_body, "deployment.json heredoc never issued")
        parsed = json.loads(backend.heredoc_body)
        self.assertEqual(parsed["prNumber"], 123)
        self.assertEqual(parsed["commitSha"], "1" * 40)
        self.assertEqual(parsed["schemaVersion"], 1)

    def test_readiness_gate_passes_on_ok_marker(self):
        backend = _RecordingBackend(responses={"desktop-readiness.sh": "DESKTOP_READY_OK"})
        stack = self._stack(backend)
        stack._run_desktop_readiness(stack.desktop_profile)
        # The script referenced the box's stable URL and the exact SHA.
        script = backend.files["/home/hog/posthog/desktop-readiness.sh"]
        self.assertIn("https://pen-abc.boxes.hogland.prod-us.posthog.dev/", script)
        self.assertIn("1" * 40, script)

    def test_readiness_gate_fails_closed_on_missing_marker(self):
        backend = _RecordingBackend(responses={"desktop-readiness.sh": "noise"})
        stack = self._stack(backend)
        with self.assertRaises(Exception):
            stack._run_desktop_readiness(stack.desktop_profile)

    def test_oauth_seed_ships_the_redirect_uri(self):
        backend = _RecordingBackend()
        stack = self._stack(backend)
        stack._run_desktop_oauth_seed(stack.desktop_profile)
        seed = backend.files["/home/hog/posthog/desktop-oauth-seed.py"]
        self.assertIn("posthog-code-preview-pr-123://callback", seed)
        self.assertIn("update_or_create", seed)


if __name__ == "__main__":
    unittest.main()
