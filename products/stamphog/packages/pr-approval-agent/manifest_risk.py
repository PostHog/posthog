"""Deterministic scan of dependency-manifest changes for execution-bearing config.

Manifests without a lockfile change can't install third-party code, but
their scripts and lifecycle hooks execute in CI and on dev machines. The
reviewer prompt guards that — this module is the deterministic first line,
so a scripts edit hard-denies instead of resting solely on LLM judgment.

Every manifest is compared structurally (base vs head risky subtrees), never
by diff-line matching: editing an existing script's command produces a changed
line keyed by the script's own name, and two diff algorithms can mark different
lines as changed for the same edit, so a line scan answers differently on the
worker and in the checkout. Parse failures fail closed.
"""

import re
import json
import tomllib
import subprocess
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import NamedTuple

import yaml

# Any change at all to these is execution-bearing — setup.py and Gemfile are
# code, and setup.cfg's declarative surface (entry_points, cmdclass) doesn't
# justify a parser for how rarely it changes.
_ANY_CHANGE_RISKY = frozenset({"setup.py", "setup.cfg", "gemfile"})


def _json_object(text: str, label: str) -> dict[str, object]:
    data = json.loads(text) if text.strip() else {}
    if not isinstance(data, dict):
        raise ValueError(f"{label} root is not an object")
    return data


def _package_json_risky_subtree(text: str) -> object:
    data = _json_object(text, "package.json")
    return {key: data.get(key) for key in ("scripts", "husky", "pnpm")}


_PNPM_WORKSPACE_INERT_KEYS = frozenset({"packages", "catalog", "catalogs"})


def _pnpm_workspace_risky_subtree(text: str) -> object:
    data = yaml.safe_load(text) if text.strip() else {}
    if not isinstance(data, dict):
        raise ValueError("pnpm-workspace.yaml root is not a mapping")
    return {key: value for key, value in data.items() if key not in _PNPM_WORKSPACE_INERT_KEYS}


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


_JS_LINE_TERMINATOR = re.compile("[\n\r  ]")


def _without_jsonc_comments(text: str) -> str:
    kept: list[str] = []
    index, in_string = 0, False
    while index < len(text):
        char = text[index]
        if in_string:
            kept.append(text[index : index + 2] if char == "\\" else char)
            index += 2 if char == "\\" else 1
            in_string = char != '"'
            continue
        if text.startswith("//", index):
            line_end = _JS_LINE_TERMINATOR.search(text, index)
            index = len(text) if line_end is None else line_end.start()
            continue
        if text.startswith("/*", index):
            comment_end = text.find("*/", index + 2)
            if comment_end == -1:
                raise ValueError("tsconfig has an unterminated block comment")
            kept.append(" ")
            index = comment_end + 2
            continue
        in_string = char == '"'
        kept.append(char)
        index += 1
    return "".join(kept)


_WHITESPACE_THEN_CLOSE = re.compile(r"[ \t\r\n]*[}\]]")


def _without_trailing_commas(text: str) -> str:
    kept: list[str] = []
    index, in_string = 0, False
    while index < len(text):
        char = text[index]
        if in_string:
            kept.append(text[index : index + 2] if char == "\\" else char)
            index += 2 if char == "\\" else 1
            in_string = char != '"'
            continue
        if char == "," and _WHITESPACE_THEN_CLOSE.match(text, index + 1):
            index += 1
            continue
        in_string = char == '"'
        kept.append(char)
        index += 1
    return "".join(kept)


def _tsconfig_risky_subtree(text: str) -> object:
    data = _json_object(_without_trailing_commas(_without_jsonc_comments(text)), "tsconfig")
    compiler_options = data.get("compilerOptions")
    plugins = compiler_options.get("plugins") if isinstance(compiler_options, dict) else compiler_options
    return (data.get("extends"), plugins)


_GO_MOD_DIRECTIVES = frozenset(
    {"module", "go", "toolchain", "godebug", "require", "exclude", "replace", "retract", "tool", "ignore"}
)
_GO_MOD_PUNCTUATION = ("(", ")", "=>")


def _go_mod_line_tokens(line: str) -> list[str]:
    """One go.mod line as Go's lexer splits it, with quoted strings kept exactly as written.

    Anything this reader can't place raises, so the caller fails closed rather than guessing.
    """
    tokens: list[str] = []
    index = 0
    while index < len(line):
        char = line[index]
        if char in " \t":
            index += 1
        elif line.startswith("//", index):
            break
        elif char in ('"', "`"):
            end = index + 1
            while end < len(line) and line[end] != char:
                end += 2 if char == '"' and line[end] == "\\" else 1
            if end >= len(line):
                raise ValueError("go.mod has an unterminated string")
            tokens.append(line[index : end + 1])
            index = end + 1
        elif punctuation := next((p for p in _GO_MOD_PUNCTUATION if line.startswith(p, index)), None):
            tokens.append(punctuation)
            index += len(punctuation)
        else:
            end = index
            while end < len(line) and line[end] not in ' \t"`()' and not line.startswith("=>", end):
                if line.startswith("//", end):
                    raise ValueError("go.mod has a comment marker inside a token")
                end += 1
            tokens.append(line[index:end])
            index = end
    return tokens


# Only `replace` is risky in go.mod: a `require` bump without go.sum fails CI deterministically
# (Go defaults to -mod=readonly), so no silent fetch is possible.
def _go_mod_replaces(text: str) -> list[tuple[str, ...]]:
    replaces: list[tuple[str, ...]] = []
    block: str | None = None
    for line in text.split("\n"):
        tokens = _go_mod_line_tokens(line)
        if not tokens:
            continue
        if block is not None:
            if tokens == [")"]:
                block = None
            elif "(" in tokens or ")" in tokens:
                raise ValueError("go.mod has a paren inside a block")
            elif block == "replace":
                replaces.append(tuple(tokens))
            continue
        if tokens[0] not in _GO_MOD_DIRECTIVES:
            raise ValueError(f"go.mod has an unknown directive {tokens[0]!r}")
        if tokens[1:] == ["("]:
            block = tokens[0]
        elif "(" in tokens or ")" in tokens:
            raise ValueError("go.mod has a paren outside a block opener")
        elif tokens[0] == "replace":
            replaces.append(tuple(tokens[1:]))
    if block is not None:
        raise ValueError("go.mod has an unclosed block")
    return sorted(replaces)


# Manifests compared by parsing base/head into a "risky subtree" and diffing
# that, rather than by diff-line matching (see module docstring). Each entry
# pairs the extractor with the parse-failure exceptions that must fail closed
# (return True) for that format.
class StructuralCheck(NamedTuple):
    extract: Callable[[str], object]
    fails_closed_on: tuple[type[Exception], ...]


_STRUCTURAL_RISK_CHECKS: dict[str, StructuralCheck] = {
    "package.json": StructuralCheck(_package_json_risky_subtree, (ValueError,)),
    "pnpm-workspace.yaml": StructuralCheck(_pnpm_workspace_risky_subtree, (yaml.YAMLError, ValueError)),
    "pyproject.toml": StructuralCheck(_toml_risky_subtree, (tomllib.TOMLDecodeError, ValueError)),
    "pipfile": StructuralCheck(_toml_risky_subtree, (tomllib.TOMLDecodeError, ValueError)),
    "cargo.toml": StructuralCheck(_cargo_risky_subtree, (tomllib.TOMLDecodeError,)),
    "composer.json": StructuralCheck(_composer_json_risky_subtree, (ValueError,)),
    "go.mod": StructuralCheck(_go_mod_replaces, (ValueError,)),
}
# tsconfig is JSONC, so its parse strips comments and trailing commas first. A file that still does
# not parse fails closed like the other formats.
_TSCONFIG_CHECK = StructuralCheck(_tsconfig_risky_subtree, (ValueError,))


def manifest_change_is_risky(path: str, base_text: str, head_text: str) -> bool:
    """True when the manifest change adds/edits/removes execution-bearing config."""
    name = Path(path).name.lower()
    if name in _ANY_CHANGE_RISKY:
        return base_text != head_text
    if name.startswith("tsconfig") and name.endswith(".json"):
        check = _TSCONFIG_CHECK
    elif name in _STRUCTURAL_RISK_CHECKS:
        check = _STRUCTURAL_RISK_CHECKS[name]
    else:
        return False
    try:
        return check.extract(_with_lf_line_ends(base_text)) != check.extract(_with_lf_line_ends(head_text))
    except check.fails_closed_on:
        return True


def _with_lf_line_ends(text: str) -> str:
    # The checkout scan reads `git show` in text mode, which turns CR and CRLF into LF, while the
    # worker reads raw blobs. Both paths must parse the same text, or one attests what the other denies.
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _git(args: list[str], repo_root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], capture_output=True, text=True, timeout=30, cwd=repo_root)


def manifest_script_changes(
    manifest_paths: list[str], base_sha: str, head_sha: str, repo_root: Path, merge_base_sha: str = ""
) -> list[str]:
    """Manifests whose change touches scripts/hooks/build config.

    The structural compare is anchored at the merge base,
    matching the merge-base→head semantics of every other diff in this tool:
    comparing against the base branch *tip* would count base-side drift
    (someone else's scripts change landing on the base) as this PR's doing.
    A given ``merge_base_sha`` is used as is, because a shallow checkout has no
    history to compute it from.
    Fails closed: if the merge base can't be resolved every manifest counts
    as risky — an unreadable repo state must not skip the deterministic gate.
    A file missing at one sha (added/deleted manifest) reads as empty.
    """
    if not manifest_paths:
        return []
    base = merge_base_sha
    if not base:
        merge_base = _git(["merge-base", base_sha, head_sha], repo_root)
        if merge_base.returncode != 0:
            return list(manifest_paths)
        base = merge_base.stdout.strip()

    risky = []
    for path in manifest_paths:
        base_show = _git(["show", f"{base}:{path}"], repo_root)
        head_show = _git(["show", f"{head_sha}:{path}"], repo_root)
        if manifest_change_is_risky(
            path,
            base_show.stdout if base_show.returncode == 0 else "",
            head_show.stdout if head_show.returncode == 0 else "",
        ):
            risky.append(path)
    return risky


def manifest_script_changes_from_contents(
    manifest_paths: list[str], contents: Mapping[str, Mapping[str, str]]
) -> list[str]:
    """``manifest_script_changes`` over texts that a caller read at the merge base and at the head.

    The server's gate check has no checkout, so it reads each manifest from GitHub and passes the
    texts in. A manifest without both texts counts as risky, the same fail-closed answer that the
    checkout scan gives for an unreadable repo state.
    """
    risky = []
    for path in manifest_paths:
        entry = contents.get(path)
        base_text = entry.get("base") if isinstance(entry, Mapping) else None
        head_text = entry.get("head") if isinstance(entry, Mapping) else None
        if not isinstance(base_text, str) or not isinstance(head_text, str):
            risky.append(path)
            continue
        if manifest_change_is_risky(path, base_text, head_text):
            risky.append(path)
    return risky
