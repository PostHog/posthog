"""Unit tests for the Django admin flag in the preview stack env.

Self-contained: no network, no live box. ``write_override`` only touches
``backend.write_file``, so a recording fake backend is enough to assert the
generated compose override turns the admin portal on — without it, ee/urls.py
registers no /admin route and the SPA rewrites /admin to /project/1/admin.

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


class _RecordingBackend:
    """Duck-typed stand-in for a PreviewBackend: write_override only calls
    write_file, so that's all the stack needs from us here."""

    def __init__(self):
        self.files: dict[str, str] = {}

    def write_file(self, remote_path, content) -> None:
        self.files[remote_path] = content if isinstance(content, str) else content.decode()


@unittest.skipUnless(HAVE_SDK, "posthog-hogland SDK not installed")
class PreviewAdminPortalTest(unittest.TestCase):
    def test_override_enables_the_admin_portal(self):
        backend = _RecordingBackend()
        stack = PostHogPreviewStack(backend)
        stack.write_override()
        override = backend.files[f"{stack.repo_dir}/{stack.OVERRIDE}"]
        self.assertIn("- ADMIN_PORTAL_ENABLED=1", override)


if __name__ == "__main__":
    unittest.main()
