"""Unit tests for the preview's PERSISTED_FEATURE_FLAGS env.

Self-contained: no network, no live box. A fake backend answers the two awk
reads with file contents, so the test covers the parse and the compose line.

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

_CONSTANTS_TSX = """
export const FEATURE_FLAGS = {
    // Eternal feature flags, shouldn't be removed
    ENGINEERING_ANALYTICS: 'engineering-analytics', // owner: #team-devex
    CONTROL_SUPPORT_LOGIN: 'control_support_login', // owner: #team-support
    MULTIVARIATE: 'some-multivariate', // owner: #team-x, multivariate=control,test
} satisfies Record<string, string>

export const ENTITY_MATCH_TYPE = 'entities'
"""

_SYNC_FEATURE_FLAGS_PY = """
INACTIVE_FLAGS = [
    "control_support_login",
    "halloween-override",
]


class Command(BaseCommand):
    help = "Add and enable all feature flags"
"""


class _FileServingBackend:
    """Duck-typed PreviewBackend: answers the awk reads and records the override."""

    def __init__(self, files: dict[str, str]):
        self.files: dict[str, str] = {}
        self._sources = files

    def exec(self, command: str, *, timeout: int = 120) -> ExecResult:
        for name, body in self._sources.items():
            if name in command:
                program = command.split("'")[1]
                return ExecResult(0, _run_awk(program, body), "")
        return ExecResult(1, "", "no such file")

    def write_file(self, remote_path, content) -> None:
        self.files[remote_path] = content if isinstance(content, str) else content.decode()


def _run_awk(program: str, body: str) -> str:
    import shutil
    import subprocess

    awk = shutil.which("awk")
    if awk is None:
        raise unittest.SkipTest("awk not available")
    return subprocess.run([awk, program], input=body, capture_output=True, text=True, check=True).stdout


def _override_lines(stack, backend: _FileServingBackend) -> list[str]:
    stack.write_override()
    return backend.files[f"{stack.repo_dir}/{stack.OVERRIDE}"].splitlines()


@unittest.skipUnless(HAVE_SDK, "posthog-hogland SDK not installed")
class PersistedFeatureFlagsTest(unittest.TestCase):
    def _flag_env(self, backend: _FileServingBackend) -> str | None:
        stack = PostHogPreviewStack(backend)
        for line in _override_lines(stack, backend):
            stripped = line.strip().lstrip("- ")
            if stripped.startswith("PERSISTED_FEATURE_FLAGS="):
                return stripped.split("=", 1)[1]
        return None

    def test_override_carries_the_checkout_flags_without_the_held_back_ones(self):
        backend = _FileServingBackend(
            {"constants.tsx": _CONSTANTS_TSX, "sync_feature_flags.py": _SYNC_FEATURE_FLAGS_PY}
        )

        self.assertEqual(self._flag_env(backend), "engineering-analytics,some-multivariate")

    def test_unreadable_flag_list_leaves_the_env_out(self):
        backend = _FileServingBackend({})

        self.assertIsNone(self._flag_env(backend))


if __name__ == "__main__":
    unittest.main()
