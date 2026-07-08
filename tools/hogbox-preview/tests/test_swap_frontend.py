"""Unit tests for the deferred frontend swap (parallel CI flow).

Self-contained: no network, no live box. Two seams are covered:

  - ``PostHogPreviewStack.swap_frontend_only`` — the stack half: attach to the
    already-up box, adopt its existing SECRET_KEY (don't rotate), rewrite the
    override WITH the frontend mounts, lay the dist in, recreate web, wait for
    health. A recording fake backend captures every call.
  - ``HoglandBackend.attach`` — the backend half: resolve the EXISTING box via
    the pen's pointer and NEVER call create()/restore.

Guarded on the SDK import (pulled per-run via ``uv run --with``), same as the
sibling tests.

    cd tools/hogbox-preview && python -m unittest discover tests
"""

from __future__ import annotations

import gzip
import pathlib
import tempfile

import unittest

try:
    from hogbox_preview.backend import ExecResult
    from hogbox_preview.stack import PostHogPreviewStack

    HAVE_SDK = True
except ImportError:
    HAVE_SDK = False


_EXISTING_KEY = "a" * 64  # the SECRET_KEY the box already runs with, from bring_up


class _RecordingBackend:
    """Duck-typed PreviewBackend for the swap path. Records the calls the stack
    makes so we can assert ordering, the override contents, and the dist upload —
    without a real box."""

    def __init__(self):
        self.files: dict[str, bytes | str] = {}
        self.long_runs: list[str] = []
        self.attached = False
        self.health_waited = False

    def attach(self) -> None:
        self.attached = True

    def exec(self, command, *, timeout: int = 120) -> ExecResult:
        # The only exec the swap path issues is reading the existing SECRET_KEY
        # out of the override — hand back the key the box already uses.
        if "SECRET_KEY=" in command:
            return ExecResult(0, _EXISTING_KEY + "\n", "")
        return ExecResult(0, "", "")

    def write_file(self, remote_path, content) -> None:
        self.files[remote_path] = content

    def run_long(self, script, *, name, timeout: int = 1800, interval: int = 3) -> ExecResult:
        self.long_runs.append(name)
        return ExecResult(0, "", "")

    def wait_http_ok(self, url_path, *, expect=200, timeout=600, interval=3) -> None:
        self.health_waited = True

    @property
    def web_url(self) -> str:
        return "https://pen-deadbeef.boxes.hogland.prod-us.posthog.dev"


@unittest.skipUnless(HAVE_SDK, "posthog-hogland SDK not installed")
class SwapFrontendOnlyTest(unittest.TestCase):
    def _dist_tar(self) -> str:
        # swap_frontend reads the tar off disk, so hand it a real (tiny) file.
        fd = tempfile.NamedTemporaryFile(suffix=".tgz", delete=False)
        fd.write(gzip.compress(b"not-a-real-tar-but-bytes-are-enough"))
        fd.close()
        self.addCleanup(lambda: pathlib.Path(fd.name).unlink(missing_ok=True))
        return fd.name

    def test_swap_attaches_reuses_key_and_serves_pr_frontend(self):
        backend = _RecordingBackend()
        stack = PostHogPreviewStack(backend, frontend_dist_tar=self._dist_tar())
        # The stack minted a fresh random key at construction; the swap must
        # DROP it in favour of the box's existing one.
        self.assertNotEqual(stack.secret_key, _EXISTING_KEY)

        url = stack.swap_frontend_only()

        # Attached to the live box, never provisioned a fresh one.
        self.assertTrue(backend.attached)
        # Adopted the box's existing SECRET_KEY rather than rotating it.
        self.assertEqual(stack.secret_key, _EXISTING_KEY)

        override = backend.files[f"{stack.repo_dir}/{stack.OVERRIDE}"]
        # The override now carries the frontend mounts (absent on the no-dist up).
        self.assertIn("./frontend/dist:/code/frontend/dist", override)
        self.assertIn("./staticfiles:/code/staticfiles", override)
        # ...and the reused key, so recreating web doesn't invalidate seeded data.
        self.assertIn(f"SECRET_KEY={_EXISTING_KEY}", override)

        # Ran the swap (collectstatic) then recreated web, then waited for health.
        self.assertEqual(backend.long_runs, ["frontend", "up-web"])
        self.assertTrue(backend.health_waited)
        self.assertEqual(url, backend.web_url)

    def test_swap_requires_a_dist(self):
        backend = _RecordingBackend()
        stack = PostHogPreviewStack(backend)  # no frontend_dist_tar
        with self.assertRaises(RuntimeError):
            stack.swap_frontend_only()
        self.assertFalse(backend.attached)


class _FakePen:
    def __init__(self, current_box_id):
        self.current_box_id = current_box_id
        self.id = "pen-deadbeef"


class _FakeBox:
    def __init__(self, box_id):
        self.id = box_id

    def exec(self, argv, *, timeout_seconds=20, env=None):
        class _R:
            exit_code = 0
            stdout = ""
            stderr = ""

        return _R()


class _NoCreateClient:
    """SDK stand-in whose create() blows up — attach must never restore."""

    def __init__(self, *, pen, box):
        self._pen = pen
        self._box = box

    def get_pen(self, name):
        return self._pen

    def get(self, box_id):
        return self._box

    def create(self, **kwargs):
        raise AssertionError("attach() must not restore a new box")

    def iter_boxes(self):
        return iter([])


@unittest.skipUnless(HAVE_SDK, "posthog-hogland SDK not installed")
class AttachResolvesExistingBoxTest(unittest.TestCase):
    def test_attach_binds_pen_pointer_without_restoring(self):
        from hogbox_preview.hogland_backend import HoglandBackend

        box = _FakeBox("box-live")
        client = _NoCreateClient(pen=_FakePen(current_box_id="box-live"), box=box)
        backend = HoglandBackend(host="https://example.invalid", name="preview-pr-42", token="test-token")
        backend._client = client

        backend.attach()

        self.assertIs(backend._box, box)
        self.assertEqual(backend._box_id, "box-live")
        self.assertIsNotNone(backend._pen)

    def test_attach_raises_when_no_box_is_live(self):
        from hogbox_preview.hogland_backend import HoglandBackend
        from hogland import NotFoundError

        class _EmptyClient:
            def get_pen(self, name):
                raise NotFoundError("no pen", status_code=404)

            def iter_boxes(self):
                return iter([])

        backend = HoglandBackend(host="https://example.invalid", name="preview-pr-42", token="test-token")
        backend._client = _EmptyClient()

        with self.assertRaises(RuntimeError):
            backend.attach()


if __name__ == "__main__":
    unittest.main()
