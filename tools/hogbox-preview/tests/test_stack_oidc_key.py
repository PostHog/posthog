"""Unit tests for the preview OAuth signing key.

Self-contained: no network, no live box. PostHog signs OAuth tokens with RS256
and refuses to save an OAuth application without OIDC_RSA_PRIVATE_KEY, so a
preview could not host an OAuth client (PostHog Desktop, for one) until the
stack gave the box a key.

    cd tools/hogbox-preview && python -m unittest discover tests
"""

from __future__ import annotations

import unittest

try:
    from hogbox_preview.stack import PostHogPreviewStack

    HAVE_SDK = True
except ImportError:
    HAVE_SDK = False

_PEM = "-----BEGIN PRIVATE KEY-----\\nMIIB\\n-----END PRIVATE KEY-----\\n"


class _ExecResult:
    def __init__(self, stdout: str = "", exit_code: int = 0):
        self.stdout = stdout
        self.stderr = ""
        self.exit_code = exit_code


class _RecordingBackend:
    """Duck-typed stand-in for a PreviewBackend. Answers the two commands the
    key path runs: read the override, and mint a key."""

    def __init__(self, stored_key: str = ""):
        self.files: dict[str, str] = {}
        self.stored_key = stored_key
        self.commands: list[str] = []

    def write_file(self, remote_path, content) -> None:
        self.files[remote_path] = content if isinstance(content, str) else content.decode()

    def exec(self, command: str, *, timeout: int = 120) -> _ExecResult:
        self.commands.append(command)
        if "sed -n" in command:
            return _ExecResult(self.stored_key)
        return _ExecResult(_PEM)


def _web_environment(override: str) -> list[str]:
    lines = []
    for line in override.splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            lines.append(stripped[2:])
    return lines


@unittest.skipUnless(HAVE_SDK, "posthog-hogland SDK not installed")
class PreviewOidcKeyTest(unittest.TestCase):
    def test_the_box_gets_a_minted_key(self):
        backend = _RecordingBackend()
        stack = PostHogPreviewStack(backend)
        stack._ensure_oidc_private_key()
        stack.write_override()
        override = backend.files[f"{stack.repo_dir}/{stack.OVERRIDE}"]
        self.assertIn(f"OIDC_RSA_PRIVATE_KEY={_PEM}", _web_environment(override))

    def test_an_existing_key_survives_a_rewrite(self):
        backend = _RecordingBackend(stored_key="-----BEGIN PRIVATE KEY-----\\nold\\n")
        stack = PostHogPreviewStack(backend)
        stack._ensure_oidc_private_key()
        self.assertEqual(stack.oidc_private_key, backend.stored_key)
        self.assertNotIn("openssl", " ".join(backend.commands))

    def test_a_box_that_cannot_mint_still_writes_an_override(self):
        backend = _RecordingBackend()
        backend.exec = lambda command, timeout=120: _ExecResult("")  # type: ignore[method-assign]
        stack = PostHogPreviewStack(backend)
        stack._ensure_oidc_private_key()
        stack.write_override()
        override = backend.files[f"{stack.repo_dir}/{stack.OVERRIDE}"]
        self.assertNotIn("OIDC_RSA_PRIVATE_KEY", override)


if __name__ == "__main__":
    unittest.main()
