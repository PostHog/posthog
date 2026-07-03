"""Deterministic scan of dependency-manifest diffs for execution-bearing keys.

Manifests without a lockfile change can't install third-party code, but
their scripts and lifecycle hooks execute in CI and on dev machines. The
reviewer prompt guards that — this module is the deterministic first line,
so a scripts edit hard-denies instead of resting solely on LLM judgment.
"""

import re
import subprocess
from pathlib import Path

# Per-manifest-family patterns matched against changed diff lines only.
# `None` means any change to the file is execution-bearing (setup.py and
# Gemfile are code, not data).
_NODE_KEYS = r'"(?:scripts|husky|pnpm|preinstall|install|postinstall|prepare|prepack|prepublish\w*)"\s*:'
_RISKY_LINE_PATTERNS: dict[str, re.Pattern[str] | None] = {
    "package.json": re.compile(_NODE_KEYS),
    "pyproject.toml": re.compile(
        r"\[(?:project\.scripts|project\.entry-points[^\]]*|build-system|tool\.[^\]]*scripts[^\]]*)\]"
    ),
    "setup.py": None,
    "gemfile": None,
    "setup.cfg": re.compile(r"\[options\.entry_points\]|^\s*cmdclass"),
    "pipfile": re.compile(r"\[scripts\]"),
    "cargo.toml": re.compile(r"^\s*build\s*="),
    "go.mod": re.compile(r"^\s*replace[\s(]"),
}
_TSCONFIG_PATTERN = re.compile(r'"(?:plugins|extends)"\s*:')


def _risk_pattern_for(path: str) -> re.Pattern[str] | None | str:
    """The risky-line pattern for a manifest, None (all lines risky), or "" (unknown file)."""
    name = Path(path).name.lower()
    if name.startswith("tsconfig") and name.endswith(".json"):
        return _TSCONFIG_PATTERN
    if name in _RISKY_LINE_PATTERNS:
        return _RISKY_LINE_PATTERNS[name]
    return ""


def diff_touches_risky_keys(path: str, diff_text: str) -> bool:
    """True when the manifest's changed lines add/remove execution-bearing config."""
    pattern = _risk_pattern_for(path)
    if pattern == "":
        return False
    changed_lines = [
        line[1:] for line in diff_text.splitlines() if line[:1] in "+-" and not line.startswith(("+++", "---"))
    ]
    if pattern is None:
        return bool(changed_lines)
    return any(pattern.search(line) for line in changed_lines)


def manifest_script_changes(manifest_paths: list[str], base_sha: str, head_sha: str, repo_root: Path) -> list[str]:
    """Manifests whose diff touches scripts/hooks/build config.

    Fails closed: if the diff can't be read, the manifest counts as risky —
    an unreadable diff must not skip the deterministic gate.
    """
    risky = []
    for path in manifest_paths:
        result = subprocess.run(
            ["git", "diff", f"{base_sha}...{head_sha}", "--", path],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=repo_root,
        )
        if result.returncode != 0 or diff_touches_risky_keys(path, result.stdout):
            risky.append(path)
    return risky
