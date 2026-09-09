"""Unit tests for the two keys the preview stack pins into the override.

Self-contained: no network, no live box. A recording fake backend is enough,
because the key paths only write the override and read it back.

``SECRET_KEY`` must be random per preview (not a shared, publicly derivable
constant) — previews are served on PUBLIC URLs, so a shared key would let anyone
forge sessions across every preview. ``OIDC_RSA_PRIVATE_KEY`` must exist at all,
because PostHog signs OAuth tokens with RS256 and refuses to save an OAuth
application without it, which kept OAuth clients (PostHog Desktop, for one) off
every preview.

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


_PEM = "-----BEGIN PRIVATE KEY-----\\nMIIB\\n-----END PRIVATE KEY-----\\n"


class _ExecResult:
    def __init__(self, stdout: str = ""):
        self.stdout = stdout
        self.stderr = ""
        self.exit_code = 0


class _RecordingBackend:
    """Duck-typed stand-in for a PreviewBackend: the key paths call write_file
    and exec, so that's all the stack needs from us here. ``stored_key`` stands
    for an override the box already carries; ``mints`` for whether openssl
    answers."""

    def __init__(self, stored_key: str = "", mints: bool = True):
        self.web_url = "https://pen-test.boxes.example.dev"
        self.files: dict[str, str] = {}
        self.stored_key = stored_key
        self.mints = mints
        self.commands: list[str] = []

    def write_file(self, remote_path, content) -> None:
        self.files[remote_path] = content if isinstance(content, str) else content.decode()

    def exec(self, command: str, *, timeout: int = 120) -> _ExecResult:
        self.commands.append(command)
        if "sed -n" in command:
            return _ExecResult(self.stored_key)
        return _ExecResult(_PEM if self.mints else "")


def _from_override(stack, backend: _RecordingBackend, name: str) -> str:
    stack.write_override()
    override = backend.files[f"{stack.repo_dir}/{stack.OVERRIDE}"]
    for line in override.splitlines():
        stripped = line.strip().lstrip("- ")
        if stripped.startswith(f"{name}="):
            return stripped.split("=", 1)[1]
    raise AssertionError(f"no {name} in override:\n{override}")


def _secret_key_from_override(stack, backend: _RecordingBackend) -> str:
    return _from_override(stack, backend, "SECRET_KEY")


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


@unittest.skipUnless(HAVE_SDK, "posthog-hogland SDK not installed")
class PreviewOidcKeyTest(unittest.TestCase):
    def test_the_box_gets_a_minted_key(self):
        backend = _RecordingBackend()
        stack = PostHogPreviewStack(backend)
        stack._ensure_oidc_private_key()
        self.assertEqual(_from_override(stack, backend, "OIDC_RSA_PRIVATE_KEY"), _PEM)

    def test_an_existing_key_survives_a_rewrite(self):
        # Minting a second key would invalidate every token the preview issued.
        backend = _RecordingBackend(stored_key="-----BEGIN PRIVATE KEY-----\\nold\\n")
        stack = PostHogPreviewStack(backend)
        stack._ensure_oidc_private_key()
        self.assertEqual(stack.oidc_private_key, backend.stored_key)
        self.assertNotIn("openssl", " ".join(backend.commands))

    def test_the_site_url_is_the_preview_url(self):
        # OAuth metadata builds its issuer and endpoints from SITE_URL, so a
        # placeholder sends a discovery client to its own machine.
        backend = _RecordingBackend()
        stack = PostHogPreviewStack(backend)
        self.assertEqual(_from_override(stack, backend, "SITE_URL"), backend.web_url)

    def test_a_box_that_cannot_mint_serves_without_a_key(self):
        backend = _RecordingBackend(mints=False)
        stack = PostHogPreviewStack(backend)
        stack._ensure_oidc_private_key()
        self.assertEqual(_from_override(stack, backend, "OIDC_RSA_PRIVATE_KEY"), "")


if __name__ == "__main__":
    unittest.main()
