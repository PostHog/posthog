"""Unit tests for the personhog override parity + the authed deep-health gate.

Self-contained: no network, no live box. Two seams are covered:

  - ``write_override`` must mirror hogland's scripts/posthog-preview-setup.sh —
    the PERSONHOG_ADDR web env plus the personhog-replica/router services. When
    those drifted, previews 500'd fleet-wide with "personhog client not
    configured" (2026-07-06 -> 07-10).
  - ``deep_health`` — after /_health, log into the seeded demo user and hit the
    endpoints that actually broke. Passes on 200s, raises with the failing
    step's body + a docker-logs tail on a 500, and is skipped on --no-seed.

Guarded on the SDK import (pulled per-run via ``uv run --with``), same as the
sibling tests.

    cd tools/hogbox-preview && python -m unittest discover tests
"""

from __future__ import annotations

import unittest

try:
    from hogbox_preview.backend import ExecResult
    from hogbox_preview.stack import PostHogPreviewStack

    HAVE_SDK = True
except ImportError:
    HAVE_SDK = False


class _RecordingBackend:
    """Duck-typed PreviewBackend. ``exec`` returns a scripted result keyed off
    the command so we can drive the probe down a pass or a fail path without a
    real box."""

    def __init__(self, *, probe_result: ExecResult | None = None):
        self.web_port = 8000
        self.files: dict[str, str] = {}
        self.execs: list[str] = []
        self._probe_result = probe_result

    def write_file(self, remote_path, content) -> None:
        self.files[remote_path] = content if isinstance(content, str) else content.decode()

    def exec(self, command, *, timeout: int = 120) -> ExecResult:
        self.execs.append(command)
        # The authed probe script is the one that logs in + hits /api endpoints.
        if "DEEP_HEALTH_OK" in command:
            return self._probe_result or ExecResult(0, "", "")
        # The failure path also greps docker logs; hand back a fake traceback.
        if "docker logs" in command:
            return ExecResult(
                0, "Traceback (most recent call last):\n  RuntimeError: personhog client not configured", ""
            )
        return ExecResult(0, "", "")


@unittest.skipUnless(HAVE_SDK, "posthog-hogland SDK not installed")
class OverridePersonhogParityTest(unittest.TestCase):
    def _override(self, **kwargs) -> str:
        backend = _RecordingBackend()
        stack = PostHogPreviewStack(backend, **kwargs)
        stack.write_override()
        return backend.files[f"{stack.repo_dir}/{stack.OVERRIDE}"]

    def test_web_env_has_personhog_addr(self):
        self.assertIn("PERSONHOG_ADDR=personhog-router:50052", self._override())

    def test_personhog_services_defined(self):
        override = self._override()
        self.assertIn("personhog-replica:", override)
        self.assertIn("personhog-router:", override)
        # extends the shared base compose (HOBBY-style), not a standalone def.
        self.assertIn("file: docker-compose.base.yml", override)
        # replica points at the MAIN posthog DB (persons live there single-node).
        self.assertIn("PRIMARY_DATABASE_URL: postgres://posthog:posthog@db:5432/posthog", override)

    def test_image_tag_flows_into_personhog_images(self):
        # The personhog tag is the part of self.image after the last ':'.
        override = self._override(image="ghcr.io/posthog/posthog:abc123")
        self.assertIn("ghcr.io/posthog/posthog/personhog-replica:abc123", override)
        self.assertIn("ghcr.io/posthog/posthog/personhog-router:abc123", override)


@unittest.skipUnless(HAVE_SDK, "posthog-hogland SDK not installed")
class DeepHealthTest(unittest.TestCase):
    def test_passes_when_probe_reports_ok(self):
        backend = _RecordingBackend(probe_result=ExecResult(0, "STEP projects 200\nDEEP_HEALTH_OK\n", ""))
        PostHogPreviewStack(backend).deep_health()
        # Ran the probe; didn't need to dump logs.
        self.assertTrue(any("DEEP_HEALTH_OK" in c for c in backend.execs))
        self.assertFalse(any("docker logs" in c for c in backend.execs))

    def test_probe_script_hits_the_endpoints_that_broke(self):
        backend = _RecordingBackend(probe_result=ExecResult(0, "DEEP_HEALTH_OK\n", ""))
        PostHogPreviewStack(backend).deep_health()
        script = next(c for c in backend.execs if "DEEP_HEALTH_OK" in c)
        self.assertIn("/login", script)
        self.assertIn("/api/login/", script)
        self.assertIn("/api/projects/@current/", script)
        self.assertIn("/api/environments/@current/query/", script)
        self.assertIn("HogQLQuery", script)
        self.assertIn("test@posthog.com", script)

    def test_raises_with_body_and_logs_on_500(self):
        # Probe fails at the projects step with a 500 + body.
        failing = ExecResult(
            0,
            "STEP login 200\nSTEP api_login 200\nSTEP projects 500\nBODY_START\npersonhog client not configured\nBODY_END\n",
            "",
        )
        backend = _RecordingBackend(probe_result=failing)
        with self.assertRaises(RuntimeError) as ctx:
            PostHogPreviewStack(backend).deep_health()
        msg = str(ctx.exception)
        # The failing step + body are surfaced...
        self.assertIn("STEP projects 500", msg)
        self.assertIn("personhog client not configured", msg)
        # ...and so is the web-log tail (the traceback that cost hours).
        self.assertIn("docker logs --tail 40 posthog-web-1", msg)
        self.assertIn("Traceback", msg)
        # It actually fetched the logs.
        self.assertTrue(any("docker logs" in c for c in backend.execs))

    def test_skipped_when_no_seed(self):
        backend = _RecordingBackend()
        PostHogPreviewStack(backend, seed_demo_data=False).deep_health()
        # No probe ran at all — nothing to authenticate as.
        self.assertFalse(any("DEEP_HEALTH_OK" in c for c in backend.execs))


if __name__ == "__main__":
    unittest.main()
