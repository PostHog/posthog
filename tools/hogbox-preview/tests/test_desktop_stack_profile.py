from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from hogbox_preview.backend import ExecResult, PreviewBackend
from hogbox_preview.stack import PostHogPreviewStack


class DesktopProfileStack(unittest.TestCase):
    def test_desktop_profile_adds_oauth_seed_gateway_and_readiness(self) -> None:
        backend = MagicMock(spec=PreviewBackend)
        backend.web_port = 8000
        backend.web_url = "https://preview.example.com/"
        backend.run_long.return_value = ExecResult(0, "DESKTOP_SEED_OK", "")

        # The readiness script's stdout carries the token + project the gateway
        # probe reuses; the probe's curl returns its HTTP code as stdout.
        def exec_by_command(command: str, *args: object, **kwargs: object) -> ExecResult:
            if "count_tokens" in command:
                return ExecResult(0, "400", "")
            if "desktop-readiness" in command:
                return ExecResult(
                    0, "DESKTOP_READY_TOKEN=fake-preview-token\nDESKTOP_READY_PROJECT=7\nDESKTOP_READY_OK", ""
                )
            return ExecResult(0, "DEEP_HEALTH_OK", "")

        backend.exec.side_effect = exec_by_command
        stack = PostHogPreviewStack(
            backend,
            branch="1" * 40,
            seed_demo_data=False,
            desktop_pr_number=123,
        )
        url = stack.bring_up()
        files = {call.args[0]: call.args[1] for call in backend.write_file.call_args_list}
        override = files["/home/hog/posthog/docker-compose.preview.yml"]
        self.assertIn("DESKTOP_PREVIEW=1", override)
        self.assertIn("handle_path /llm-gateway/*", override)
        self.assertIn("header_up x-posthog-provider bedrock", override)
        self.assertIn("AWS_CONTAINER_CREDENTIALS_FULL_URI=http://127.0.0.1:8181/credentials", override)
        self.assertIn("- 8001:8000", override)
        self.assertEqual(override.count("network_mode: host"), 2)
        # One web key: a duplicate YAML mapping key makes Compose refuse the file.
        self.assertEqual(override.count("  web:"), 1)
        # The gateway reads only the LLM_GATEWAY_-prefixed env names.
        self.assertIn("LLM_GATEWAY_POSTHOG_API_BASE_URL=http://localhost:8001", override)
        self.assertNotIn("POSTHOG_API_BASE_URL=http", override.replace("LLM_GATEWAY_POSTHOG_API_BASE_URL", ""))
        # The seed pins the application UUID the gateway allowlist expects.
        seed_script = files["/home/hog/posthog/desktop-oauth-seed.py"]
        self.assertIn("019ebb47-c750-0000-e1ea-723a6ff112d3", seed_script)
        commands = [call.args[0] for call in backend.run_long.call_args_list]
        self.assertLess(
            commands.index(next(c for c in commands if "up -d --no-build web" in c)),
            commands.index(next(c for c in commands if "desktop-preview-proxy llm-gateway" in c)),
        )
        backend.wait_http_ok.assert_any_call("/llm-gateway/_liveness", expect=200, timeout=600)
        self.assertEqual(stack.desktop_gateway_url(url), "https://preview.example.com/llm-gateway")
        checkout = next(command for command in commands if "fetch --depth" in command)
        self.assertIn("origin " + "1" * 40, checkout)
        seed = next(command for command in commands if "manage.py shell" in command)
        self.assertIn("< /home/hog/posthog/desktop-oauth-seed.py", seed)

    def test_readiness_surfaces_guest_failures(self) -> None:
        backend = MagicMock(spec=PreviewBackend)
        backend.web_port = 8000
        backend.exec.return_value = ExecResult(1, "", "Desktop access denied")
        stack = PostHogPreviewStack(backend, desktop_pr_number=123)
        with self.assertRaisesRegex(RuntimeError, "Desktop access denied"):
            stack._run_desktop_readiness(123)


if __name__ == "__main__":
    unittest.main()
