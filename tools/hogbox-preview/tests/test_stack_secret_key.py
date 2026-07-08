"""Unit tests for the preview SECRET_KEY handling in the stack.

Self-contained: no network, no live box. The stack's ``write_override`` only
touches ``backend.write_file``, so a recording fake backend is enough to assert
the key is random per preview (not a shared, publicly derivable constant) —
previews are served on PUBLIC URLs, so a shared key would let anyone forge
sessions across every preview.

    cd tools/hogbox-preview && python -m unittest discover tests
"""

from __future__ import annotations

import hashlib

import unittest

# Importing the package pulls hogland_backend, which needs the posthog-hogland
# SDK (installed per-run via `uv run --with`, not a repo dependency). Guard the
# import so the monorepo's Django pytest collection can't hard-fail here — the
# key path itself is SDK-free, but the package __init__ isn't.
try:
    from hogbox_preview.stack import PostHogPreviewStack

    HAVE_SDK = True
except ImportError:
    HAVE_SDK = False

# The old, broken approach: a globally derivable constant shared by every box.
_OLD_DERIVABLE_KEY = hashlib.sha256(b"hogbox-preview-ephemeral-tailnet-only").hexdigest()


class _RecordingBackend:
    """Duck-typed stand-in for a PreviewBackend: write_override only calls
    write_file, so that's all the stack needs from us here."""

    def __init__(self):
        self.files: dict[str, str] = {}

    def write_file(self, remote_path, content) -> None:
        self.files[remote_path] = content if isinstance(content, str) else content.decode()


def _secret_key_from_override(stack, backend: _RecordingBackend) -> str:
    stack.write_override()
    override = backend.files[f"{stack.repo_dir}/{stack.OVERRIDE}"]
    for line in override.splitlines():
        stripped = line.strip().lstrip("- ")
        if stripped.startswith("SECRET_KEY="):
            return stripped.split("=", 1)[1]
    raise AssertionError(f"no SECRET_KEY in override:\n{override}")


@unittest.skipUnless(HAVE_SDK, "posthog-hogland SDK not installed")
class PreviewSecretKeyTest(unittest.TestCase):
    def test_key_is_random_hex_not_the_derivable_constant(self):
        backend = _RecordingBackend()
        stack = PostHogPreviewStack(backend)
        key = _secret_key_from_override(stack, backend)

        self.assertNotEqual(key, _OLD_DERIVABLE_KEY)
        # secrets.token_hex(32) -> 64 lowercase hex chars.
        self.assertEqual(len(key), 64)
        self.assertTrue(all(c in "0123456789abcdef" for c in key))

    def test_key_differs_across_previews(self):
        # Two independent previews (e.g. a re-provision) must not share a key.
        b1, b2 = _RecordingBackend(), _RecordingBackend()
        k1 = _secret_key_from_override(PostHogPreviewStack(b1), b1)
        k2 = _secret_key_from_override(PostHogPreviewStack(b2), b2)
        self.assertNotEqual(k1, k2)

    def test_key_is_stable_within_a_single_preview(self):
        # All of one preview's processes must agree: rewriting the override for
        # the same stack yields the same key.
        backend = _RecordingBackend()
        stack = PostHogPreviewStack(backend)
        self.assertEqual(
            _secret_key_from_override(stack, backend),
            _secret_key_from_override(stack, backend),
        )


if __name__ == "__main__":
    unittest.main()
