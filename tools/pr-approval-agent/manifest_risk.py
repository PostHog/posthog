"""Deterministic scan of dependency-manifest changes for execution-bearing config.

Manifests without a lockfile change can't install third-party code, but
their scripts and lifecycle hooks execute in CI and on dev machines. The
reviewer prompt guards that — this module is the deterministic first line,
so a scripts edit hard-denies instead of resting solely on LLM judgment.

Parseable manifests are compared structurally (base vs head risky subtrees)
rather than by diff-line matching: editing an existing script's command
produces a changed line keyed by the script's own name, which a line scan
keyed on "scripts"/lifecycle names misses entirely. Line scanning remains
only where key and value share a line (cargo build scripts, go.mod replace
directives). Parse failures fail closed.
"""

import re
import json
import tomllib
import subprocess
from pathlib import Path

# Any change at all to these is execution-bearing — setup.py and Gemfile are
# code, and setup.cfg's declarative surface (entry_points, cmdclass) doesn't
# justify a parser for how rarely it changes.
_ANY_CHANGE_RISKY = frozenset({"setup.py", "setup.cfg", "gemfile"})

# Key-and-value share a line in these formats, so a line scan can't be
# bypassed by editing a value without its key appearing in the diff.
_RISKY_LINE_PATTERNS: dict[str, re.Pattern[str]] = {
    "cargo.toml": re.compile(r"^\s*build\s*="),
    "go.mod": re.compile(r"^\s*replace[\s(]"),
}
_TSCONFIG_LINE_PATTERN = re.compile(r'"(?:plugins|extends)"\s*:')


def _package_json_risky_subtree(text: str) -> object:
    data = json.loads(text) if text.strip() else {}
    if not isinstance(data, dict):
        raise ValueError("package.json root is not an object")
    return {key: data.get(key) for key in ("scripts", "husky", "pnpm")}


def _toml_risky_subtree(text: str) -> object:
    """build-system plus every nested scripts/entry-points table, with paths."""
    data = tomllib.loads(text) if text.strip() else {}
    found: list[tuple[tuple[str, ...], object]] = [((), data.get("build-system"))]

    def walk(node: object, path: tuple[str, ...]) -> None:
        if not isinstance(node, dict):
            return
        for key in sorted(node):
            if key in ("scripts", "entry-points", "entry_points"):
                found.append(((*path, key), node[key]))
            walk(node[key], (*path, key))

    walk(data, ())
    return found


def _tsconfig_risky_subtree(text: str) -> object:
    data = json.loads(text) if text.strip() else {}
    if not isinstance(data, dict):
        raise ValueError("tsconfig root is not an object")
    return (data.get("extends"), (data.get("compilerOptions") or {}).get("plugins"))


def manifest_change_is_risky(path: str, base_text: str, head_text: str, diff_text: str) -> bool:
    """True when the manifest change adds/edits/removes execution-bearing config."""
    name = Path(path).name.lower()
    if name in _ANY_CHANGE_RISKY:
        return base_text != head_text
    if name == "package.json":
        try:
            return _package_json_risky_subtree(base_text) != _package_json_risky_subtree(head_text)
        except ValueError:
            return True
    if name in ("pyproject.toml", "pipfile"):
        try:
            return _toml_risky_subtree(base_text) != _toml_risky_subtree(head_text)
        except (tomllib.TOMLDecodeError, ValueError):
            return True
    if name.startswith("tsconfig") and name.endswith(".json"):
        # tsconfig is often JSONC (comments, trailing commas); a strict-JSON
        # parse failure falls back to line scanning rather than failing
        # closed, or every commented tsconfig edit would hard-deny.
        try:
            return _tsconfig_risky_subtree(base_text) != _tsconfig_risky_subtree(head_text)
        except ValueError:
            return _scan_changed_lines(diff_text, _TSCONFIG_LINE_PATTERN)
    if name in _RISKY_LINE_PATTERNS:
        return _scan_changed_lines(diff_text, _RISKY_LINE_PATTERNS[name])
    return False


def _scan_changed_lines(diff_text: str, pattern: re.Pattern[str]) -> bool:
    return any(
        pattern.search(line[1:])
        for line in diff_text.splitlines()
        if line[:1] in "+-" and not line.startswith(("+++", "---"))
    )


def _git(args: list[str], repo_root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], capture_output=True, text=True, timeout=30, cwd=repo_root)


def manifest_script_changes(manifest_paths: list[str], base_sha: str, head_sha: str, repo_root: Path) -> list[str]:
    """Manifests whose change touches scripts/hooks/build config.

    Fails closed: if the shas can't be resolved every manifest counts as
    risky — an unreadable repo state must not skip the deterministic gate.
    A file missing at one sha (added/deleted manifest) reads as empty.
    """
    if not manifest_paths:
        return []
    for sha in (base_sha, head_sha):
        if _git(["rev-parse", "--verify", f"{sha}^{{commit}}"], repo_root).returncode != 0:
            return list(manifest_paths)

    risky = []
    for path in manifest_paths:
        base_show = _git(["show", f"{base_sha}:{path}"], repo_root)
        head_show = _git(["show", f"{head_sha}:{path}"], repo_root)
        diff = _git(["diff", f"{base_sha}...{head_sha}", "--", path], repo_root)
        if manifest_change_is_risky(
            path,
            base_show.stdout if base_show.returncode == 0 else "",
            head_show.stdout if head_show.returncode == 0 else "",
            diff.stdout if diff.returncode == 0 else "",
        ):
            risky.append(path)
    return risky
