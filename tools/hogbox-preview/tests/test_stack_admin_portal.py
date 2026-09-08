"""Unit tests for the opt-in Django admin flag in the preview stack.

Self-contained: no network, no live box. ``write_override`` only touches
``backend.write_file``, so a recording fake backend is enough to assert the
default omits the admin portal — a preview is served on a PUBLIC URL and its
seeded demo user is staff, so an always-on /admin would be world-reachable.

    cd tools/hogbox-preview && python -m unittest discover tests
"""

from __future__ import annotations

import unittest

# Importing the package pulls hogland_backend, which needs the posthog-hogland
# SDK (installed per-run via `uv run --with`, not a repo dependency). Guard the
# import so the monorepo's Django pytest collection can't hard-fail here.
try:
    from hogbox_preview.stack import PostHogPreviewStack

    HAVE_SDK = True
except ImportError:
    HAVE_SDK = False

_ENV_LINE = "- ADMIN_PORTAL_ENABLED=1"


class _RecordingBackend:
    """Duck-typed stand-in for a PreviewBackend: write_override only calls
    write_file, so that's all the stack needs from us here."""

    def __init__(self):
        self.files: dict[str, str] = {}

    def write_file(self, remote_path, content) -> None:
        self.files[remote_path] = content if isinstance(content, str) else content.decode()


def _override(stack, backend: _RecordingBackend) -> str:
    stack.write_override()
    return backend.files[f"{stack.repo_dir}/{stack.OVERRIDE}"]


@unittest.skipUnless(HAVE_SDK, "posthog-hogland SDK not installed")
class PreviewAdminPortalTest(unittest.TestCase):
    def test_default_override_has_no_admin_portal(self):
        backend = _RecordingBackend()
        self.assertNotIn(_ENV_LINE, _override(PostHogPreviewStack(backend), backend))

    def test_opt_in_puts_the_flag_in_the_web_env(self):
        backend = _RecordingBackend()
        self.assertIn(_ENV_LINE, _override(PostHogPreviewStack(backend, admin_portal=True), backend))


if __name__ == "__main__":
    unittest.main()
