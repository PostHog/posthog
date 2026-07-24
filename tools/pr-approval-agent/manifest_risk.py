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
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple

# Any change at all to these is execution-bearing — setup.py and Gemfile are
# code, and setup.cfg's declarative surface (entry_points, cmdclass) doesn't
# justify a parser for how rarely it changes.
_ANY_CHANGE_RISKY = frozenset({"setup.py", "setup.cfg", "gemfile"})

# Key-and-value share a line in go.mod, so a line scan can't be bypassed by
# editing a value without its key appearing in the diff. Only `replace` is
# risky there: a `require` bump without go.sum fails CI deterministically
# (Go defaults to -mod=readonly), so no silent fetch is possible.
_RISKY_LINE_PATTERNS: dict[str, re.Pattern[str]] = {
    "go.mod": re.compile(r"^\s*replace[\s(]"),
}
_TSCONFIG_LINE_PATTERN = re.compile(r'"(?:plugins|extends)"\s*:')


def _json_object(text: str, label: str) -> dict[str, object]:
    data = json.loads(text) if text.strip() else {}
    if not isinstance(data, dict):
        raise ValueError(f"{label} root is not an object")
    return data


def _package_json_risky_subtree(text: str) -> object:
    data = _json_object(text, "package.json")
    return {key: data.get(key) for key in ("scripts", "husky", "pnpm")}


def _composer_json_risky_subtree(text: str) -> object:
    return _json_object(text, "composer.json").get("scripts")


_TOML_RISKY_KEYS = frozenset({"scripts", "entry-points", "entry_points"})
# Cargo resolves manifests at build time and our CI doesn't pass --locked
# everywhere (cargo test in ci-rust.yml, cargo build in ci-mcp/ci-nodejs), so
# a dependency or feature edit without Cargo.lock silently fetches new code.
_CARGO_RISKY_KEYS = frozenset({"dependencies", "dev-dependencies", "build-dependencies", "features", "build"})


def _collect_risky_keys(data: dict[str, object], keys: frozenset[str]) -> list[tuple[tuple[str, ...], object]]:
    """Walk a TOML dict tree and collect (path, value) for every matching key."""
    found: list[tuple[tuple[str, ...], object]] = []

    def walk(node: object, path: tuple[str, ...]) -> None:
        if not isinstance(node, dict):
            return
        for key in sorted(node):
            if key in keys:
                found.append(((*path, key), node[key]))
            walk(node[key], (*path, key))

    walk(data, ())
    return found


def _toml_risky_subtree(text: str) -> object:
    """build-system plus every nested scripts/entry-points table, with paths."""
    data = tomllib.loads(text) if text.strip() else {}
    return [((), data.get("build-system")), *_collect_risky_keys(data, _TOML_RISKY_KEYS)]


def _cargo_risky_subtree(text: str) -> object:
    data = tomllib.loads(text) if text.strip() else {}
    return _collect_risky_keys(data, _CARGO_RISKY_KEYS)


def _tsconfig_risky_subtree(text: str) -> object:
    data = _json_object(text, "tsconfig")
    return (data.get("extends"), (data.get("compilerOptions") or {}).get("plugins"))


# Manifests compared by parsing base/head into a "risky subtree" and diffing
# that, rather than by diff-line matching (see module docstring). Each entry
# pairs the extractor with the parse-failure exceptions that must fail closed
# (return True) for that format.
class StructuralCheck(NamedTuple):
    extract: Callable[[str], object]
    fails_closed_on: tuple[type[Exception], ...]


_STRUCTURAL_RISK_CHECKS: dict[str, StructuralCheck] = {
    "package.json": StructuralCheck(_package_json_risky_subtree, (ValueError,)),
    "pyproject.toml": StructuralCheck(_toml_risky_subtree, (tomllib.TOMLDecodeError, ValueError)),
    "pipfile": StructuralCheck(_toml_risky_subtree, (tomllib.TOMLDecodeError, ValueError)),
    "cargo.toml": StructuralCheck(_cargo_risky_subtree, (tomllib.TOMLDecodeError,)),
    "composer.json": StructuralCheck(_composer_json_risky_subtree, (ValueError,)),
}


def manifest_change_is_risky(path: str, base_text: str, head_text: str, diff_text: str) -> bool:
    """True when the manifest change adds/edits/removes execution-bearing config."""
    name = Path(path).name.lower()
    if name in _ANY_CHANGE_RISKY:
        return base_text != head_text
    if name in _STRUCTURAL_RISK_CHECKS:
        check = _STRUCTURAL_RISK_CHECKS[name]
        try:
            return check.extract(base_text) != check.extract(head_text)
        except check.fails_closed_on:
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

    Both the structural compare and the diff are anchored at the merge base,
    matching the merge-base→head semantics of every other diff in this tool:
    comparing against the base branch *tip* would count base-side drift
    (someone else's scripts change landing on the base) as this PR's doing.
    Fails closed: if the merge base can't be resolved every manifest counts
    as risky — an unreadable repo state must not skip the deterministic gate.
    A file missing at one sha (added/deleted manifest) reads as empty.
    """
    if not manifest_paths:
        return []
    merge_base = _git(["merge-base", base_sha, head_sha], repo_root)
    if merge_base.returncode != 0:
        return list(manifest_paths)
    base = merge_base.stdout.strip()

    risky = []
    for path in manifest_paths:
        base_show = _git(["show", f"{base}:{path}"], repo_root)
        head_show = _git(["show", f"{head_sha}:{path}"], repo_root)
        diff = _git(["diff", f"{base}..{head_sha}", "--", path], repo_root)
        if manifest_change_is_risky(
            path,
            base_show.stdout if base_show.returncode == 0 else "",
            head_show.stdout if head_show.returncode == 0 else "",
            diff.stdout if diff.returncode == 0 else "",
        ):
            risky.append(path)
    return risky
