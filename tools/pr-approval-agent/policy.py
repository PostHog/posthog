"""Declarative merge-gate policy: loader, resolver, and prompt sanitizer.

The engine's deny/allow/size/tier/dismiss data lives in `.stamphog/policy.yml`
(global, trusted) and optional per-folder `AGENT_APPROVALS.md` overrides
(untrusted, positive allow-list). This module loads and validates the global
policy, resolves the effective policy for a given set of changed files, and
owns the untrusted-text sanitizer shared with the reviewer prompt.

Security posture (see .stamphog/README.md):
- All files are read from the checked-out working tree - the repo root is
  resolved from this module's own location, never from cwd. In CI the workflow
  checks out `ref: master`, so the working tree IS the trusted ref.
- A malformed global policy hard-fails at load (fail closed - the tool crashes
  rather than approving with a half-loaded policy).
- Folder overrides are a positive allow-list: only explicitly delegated keys
  are read, within contract ceilings. Every AGENT_APPROVALS.md at or above a
  changed file governs it - guidance accumulates and a child file refines its
  ancestors rather than replacing them. An invalid folder file contributes
  nothing itself (frontmatter and prose ignored) but does not cancel its
  ancestors; files with no valid grant on their chain fall to the global pool.
- Folder prose is untrusted advisory text: sanitized and length-capped before
  it reaches the reviewer prompt, where it sits inside the untrusted region.
"""

import re
import functools
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

# ── Untrusted-text sanitizer (shared with reviewer.py) ───────────

# Strip only invisible characters - the prompt-smuggling vectors: C0/C1
# controls, bidi overrides, zero-width chars, and the Unicode tags block
# (invisible ASCII). Visible unicode must survive: reviewer bots express
# verdicts as 👍/👀 in review bodies, and stripping emoji garbles those
# into text that reads like tampering on the next run. ZWJ is stripped
# with the other zero-width chars (it interleaves invisibly into words);
# composite emoji degrade to their visible components, which stays readable.
_INVISIBLE_CHARS_RE = re.compile(
    "[\x00-\x08\x0b-\x1f\x7f-\x9f"  # C0/C1 controls and DEL (keep \t \n)
    "\u061c"  # Arabic letter mark (bidi)
    "\u200b-\u200f"  # zero-width space/joiners, LRM/RLM
    "\u2028\u2029"  # line/paragraph separators
    "\u202a-\u202e\u2066-\u2069"  # bidi embedding/override/isolate controls
    "\u2060\ufeff"  # word joiner, BOM
    "\U000e0000-\U000e007f]"  # tags block - invisible ASCII smuggling
)


def _sanitize_untrusted(text: str, max_len: int = 200) -> str:
    """Strip invisible/control chars and cap length; visible unicode passes through."""
    return _INVISIBLE_CHARS_RE.sub("", text)[:max_len]


# ── Repo-root resolution ─────────────────────────────────────────


@functools.lru_cache(maxsize=1)
def repo_root() -> Path:
    """Locate the repo root by walking up from this module's own location.

    Deterministic and cwd-independent: the policy files must be read from the
    same checked-out tree as this script, never from wherever the process runs.
    The single resolver for the whole tool; cached, the tree never moves
    mid-process.
    """
    here = Path(__file__).resolve().parent
    for parent in [here, *here.parents]:
        if (parent / ".stamphog").is_dir() or (parent / ".git").exists():
            return parent
    raise RuntimeError("Cannot locate repo root (no .stamphog/ or .git found above policy.py)")


def default_policy_path() -> Path:
    return repo_root() / ".stamphog" / "policy.yml"


def review_guidance_path() -> Path:
    return repo_root() / ".stamphog" / "review-guidance.md"


# ── Policy data structures ───────────────────────────────────────


@dataclass(frozen=True)
class DenyCategory:
    description: str
    rationale: str
    # Only the scopes present in the policy file, preserving pattern order.
    # Scope keys are a subset of {"any", "titles", "paths"}.
    match: dict[str, tuple[str, ...]]
    exempt_path_prefixes: tuple[str, ...] = ()


@dataclass(frozen=True)
class SizeGate:
    max_lines: int
    max_files: int


@dataclass(frozen=True)
class T1Subclass:
    max_lines: int
    max_files: int
    # "single-area" (exact match) or "not-cross-cutting" (anything but cross-cutting).
    breadth: str


@dataclass(frozen=True)
class DismissData:
    trivial_extensions: frozenset[str]
    trivial_name_prefixes: tuple[str, ...]
    test_regex: str
    generated_regex: str


@dataclass(frozen=True)
class OverrideContract:
    ceiling: int


@dataclass(frozen=True)
class FamiliarityStrong:
    # STRONG = blame overlap ≥ threshold. Deliberately the only criterion: the
    # Jul 2026 backtest found blame overlap the sole monotonic predictor of
    # human rubber-stamps; composite path/recency rules measured nothing.
    min_blame_overlap_pct: float


@dataclass(frozen=True)
class FamiliarityModerate:
    # MODERATE = both satisfied.
    min_prior_prs: int
    max_days_since_touch: int


@dataclass(frozen=True)
class FamiliarityPolicy:
    """Band thresholds for the author-familiarity signal (judgment layer only).

    Non-delegable by construction - absent from the `overrides` contract, so a
    folder file can never grant or tune it.
    """

    strong: FamiliarityStrong
    moderate: FamiliarityModerate


@dataclass(frozen=True)
class OwnershipSource:
    """One ownership-context source: a format plus exactly one locator.

    `format` names an entry in gates.OWNERSHIP_FORMATS; exactly one of `path`
    (a single file) or `glob` (a repo-root glob) is set, dictated by that
    entry's declared locator. Both locators stay repo-relative - the loader
    rejects absolute paths and any `..` escape.
    """

    format: str
    path: str | None = None
    glob: str | None = None


@dataclass(frozen=True)
class Policy:
    version: int
    deny: dict[str, DenyCategory]
    allow_path_patterns: tuple[str, ...]
    allow_extensions: frozenset[str]
    size_gate: SizeGate
    t1_subclasses: dict[str, T1Subclass]
    dismiss: DismissData
    overrides: dict[str, OverrideContract]
    familiarity: FamiliarityPolicy
    ownership: tuple[OwnershipSource, ...]

    def deny_pattern_defs(self) -> dict[str, dict[str, list[str]]]:
        """Reconstruct the raw scope→patterns mapping the compiler consumes."""
        return {
            category: {scope: list(pats) for scope, pats in cat.match.items()} for category, cat in self.deny.items()
        }


@dataclass(frozen=True)
class ScopeBudget:
    """One size-gate budget: a folder override's files, or the global pool.

    `path` is the granting AGENT_APPROVALS.md (repo-relative); None is the global
    pool, which absorbs every file whose chain grants no valid max_files so
    splitting files across pseudo-scopes can never inflate the allowance.
    """

    path: str | None
    max_files: int
    files: tuple[str, ...]


@dataclass(frozen=True)
class EffectivePolicy:
    """Per-PR resolved policy: per-scope size budgets plus advisory prose.

    Mixed PRs get mixed leniency: every AGENT_APPROVALS.md at or above a changed
    file governs it, and the file is budgeted by the nearest folder on that
    chain with a valid max_files grant. Each scope's files must fit that scope's
    own ceiling; files with no valid grant on their chain keep the global
    ceiling. No file ever gets more leniency than its own chain grants.
    max_lines stays a single global total; it is not delegable.
    """

    max_lines: int
    scopes: tuple[ScopeBudget, ...]
    folder_prose: str | None = None
    invalid_folder_files: tuple[str, ...] = ()


class PolicyError(ValueError):
    """Raised when the global policy is malformed - fail closed at load time."""


# ── Global policy loading + validation ───────────────────────────

_TOP_LEVEL_KEYS = {"version", "deny", "allow", "size_gate", "tiers", "dismiss", "overrides", "familiarity", "ownership"}
_DENY_SCOPES = {"any", "titles", "paths"}
_BREADTH_RULES = {"single-area", "not-cross-cutting"}

# The delegation contract's only delegable key. Everything else (deny, allow,
# dismiss, tiers, size_gate.max_lines) is non-delegable by construction.
_DELEGABLE_KEYS = {"size_gate.max_files"}

# Invariant 7: self-governance deny must cover these path families so a future
# policy edit cannot silently drop stamphog's protection of its own files.
_SELF_GOVERNANCE_REQUIRED = (".stamphog/", "AGENT_APPROVALS", "tools/pr-approval-agent/")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise PolicyError(message)


def _compile_or_raise(pattern: str, context: str) -> None:
    try:
        re.compile(pattern)
    except re.error as exc:
        raise PolicyError(f"{context}: pattern {pattern!r} does not compile: {exc}") from exc


def _parse_deny(raw: Any, lockfile_names: Iterable[str]) -> dict[str, DenyCategory]:
    _require(isinstance(raw, dict) and bool(raw), "deny: must be a non-empty mapping")
    lockfile_patterns = [re.escape(name) for name in sorted(lockfile_names)]

    deny: dict[str, DenyCategory] = {}
    for category, spec in raw.items():
        _require(isinstance(spec, dict), f"deny.{category}: must be a mapping")
        match_raw = spec.get("match")
        _require(isinstance(match_raw, dict) and bool(match_raw), f"deny.{category}.match: must be a non-empty mapping")

        match: dict[str, tuple[str, ...]] = {}
        for scope, patterns in match_raw.items():
            _require(scope in _DENY_SCOPES, f"deny.{category}.match.{scope}: unknown scope")
            _require(
                isinstance(patterns, list) and bool(patterns),
                f"deny.{category}.match.{scope}: must be a non-empty list",
            )
            values = list(patterns)
            # Splice the code-derived lockfile names ahead of the literal
            # patterns - they stay code-sourced (see DEPENDENCY_ECOSYSTEMS).
            if category == "deps_toolchain" and scope == "paths":
                values = lockfile_patterns + values
            for pattern in values:
                _require(isinstance(pattern, str), f"deny.{category}.match.{scope}: patterns must be strings")
                _compile_or_raise(pattern, f"deny.{category}.match.{scope}")
            match[scope] = tuple(values)

        exempt = spec.get("exempt_path_prefixes", [])
        _require(isinstance(exempt, list), f"deny.{category}.exempt_path_prefixes: must be a list")
        deny[category] = DenyCategory(
            description=str(spec.get("description", "")),
            rationale=str(spec.get("rationale", "")),
            match=match,
            exempt_path_prefixes=tuple(str(p) for p in exempt),
        )

    _assert_self_governance(deny)
    if lockfile_patterns:
        # Same fail-closed posture as self-governance: renaming or splitting
        # the category must break loudly, not silently drop lockfile coverage.
        _require(
            "deps_toolchain" in deny,
            "deny: missing 'deps_toolchain' category (the code-derived lockfile patterns splice into it)",
        )
    return deny


def _assert_self_governance(deny: dict[str, DenyCategory]) -> None:
    _require("stamphog_policy" in deny, "deny: missing required 'stamphog_policy' self-governance category")
    paths = " ".join(deny["stamphog_policy"].match.get("paths", ()))
    for token in _SELF_GOVERNANCE_REQUIRED:
        _require(token in paths, f"deny.stamphog_policy: self-governance must cover {token!r}")


def _parse_allow(raw: Any) -> tuple[tuple[str, ...], frozenset[str]]:
    _require(isinstance(raw, dict), "allow: must be a mapping")
    path_patterns = raw.get("path_patterns")
    extensions = raw.get("extensions_only")
    _require(isinstance(path_patterns, list) and bool(path_patterns), "allow.path_patterns: must be a non-empty list")
    _require(isinstance(extensions, list) and bool(extensions), "allow.extensions_only: must be a non-empty list")
    return tuple(str(p) for p in path_patterns), frozenset(str(e) for e in extensions)


def _parse_size_gate(raw: Any) -> SizeGate:
    _require(isinstance(raw, dict), "size_gate: must be a mapping")
    max_lines = raw.get("max_lines")
    max_files = raw.get("max_files")
    _require(isinstance(max_lines, int) and not isinstance(max_lines, bool), "size_gate.max_lines: must be an integer")
    _require(isinstance(max_files, int) and not isinstance(max_files, bool), "size_gate.max_files: must be an integer")
    return SizeGate(max_lines=max_lines, max_files=max_files)


def _parse_tiers(raw: Any) -> dict[str, T1Subclass]:
    _require(isinstance(raw, dict), "tiers: must be a mapping")
    subclasses_raw = raw.get("t1_subclasses")
    _require(
        isinstance(subclasses_raw, dict) and bool(subclasses_raw),
        "tiers.t1_subclasses: must be a non-empty mapping",
    )
    subclasses: dict[str, T1Subclass] = {}
    for name, spec in subclasses_raw.items():
        _require(isinstance(spec, dict), f"tiers.t1_subclasses.{name}: must be a mapping")
        max_lines = spec.get("max_lines")
        max_files = spec.get("max_files")
        breadth = spec.get("breadth")
        _require(
            isinstance(max_lines, int) and not isinstance(max_lines, bool), f"{name}.max_lines: must be an integer"
        )
        _require(
            isinstance(max_files, int) and not isinstance(max_files, bool), f"{name}.max_files: must be an integer"
        )
        _require(breadth in _BREADTH_RULES, f"{name}.breadth: must be one of {sorted(_BREADTH_RULES)}")
        subclasses[name] = T1Subclass(max_lines=max_lines, max_files=max_files, breadth=breadth)
    return subclasses


def _parse_dismiss(raw: Any) -> DismissData:
    _require(isinstance(raw, dict), "dismiss: must be a mapping")
    extensions = raw.get("trivial_extensions")
    prefixes = raw.get("trivial_name_prefixes")
    test_regex = raw.get("test_regex")
    generated_regex = raw.get("generated_regex")
    _require(isinstance(extensions, list) and bool(extensions), "dismiss.trivial_extensions: must be a non-empty list")
    _require(isinstance(prefixes, list) and bool(prefixes), "dismiss.trivial_name_prefixes: must be a non-empty list")
    _require(isinstance(test_regex, str), "dismiss.test_regex: must be a string")
    _require(isinstance(generated_regex, str), "dismiss.generated_regex: must be a string")
    _compile_or_raise(test_regex, "dismiss.test_regex")
    _compile_or_raise(generated_regex, "dismiss.generated_regex")
    return DismissData(
        trivial_extensions=frozenset(str(e) for e in extensions),
        trivial_name_prefixes=tuple(str(p) for p in prefixes),
        test_regex=test_regex,
        generated_regex=generated_regex,
    )


def _parse_overrides(raw: Any) -> dict[str, OverrideContract]:
    _require(isinstance(raw, dict), "overrides: must be a mapping")
    overrides: dict[str, OverrideContract] = {}
    for key, spec in raw.items():
        _require(key in _DELEGABLE_KEYS, f"overrides.{key}: not a delegable key (allowed: {sorted(_DELEGABLE_KEYS)})")
        _require(isinstance(spec, dict), f"overrides.{key}: must be a mapping")
        ceiling = spec.get("ceiling")
        _require(
            isinstance(ceiling, int) and not isinstance(ceiling, bool), f"overrides.{key}.ceiling: must be an integer"
        )
        overrides[key] = OverrideContract(ceiling=ceiling)
    return overrides


_FAMILIARITY_STRONG_KEYS = {"min_blame_overlap_pct"}
_FAMILIARITY_MODERATE_KEYS = {"min_prior_prs", "max_days_since_touch"}


def _require_percentage(value: Any, context: str) -> float:
    _require(isinstance(value, (int, float)) and not isinstance(value, bool), f"{context}: must be a number")
    _require(0 <= value <= 100, f"{context}: must be between 0 and 100")
    return float(value)


def _require_positive_int(value: Any, context: str) -> int:
    _require(isinstance(value, int) and not isinstance(value, bool), f"{context}: must be an integer")
    _require(value > 0, f"{context}: must be positive")
    return value


def _require_exact_keys(raw: dict, expected: set[str], context: str) -> None:
    unknown = set(raw) - expected
    _require(not unknown, f"{context}: unknown keys {sorted(unknown)}")
    missing = expected - set(raw)
    _require(not missing, f"{context}: missing keys {sorted(missing)}")


def _parse_familiarity(raw: Any) -> FamiliarityPolicy:
    _require(isinstance(raw, dict), "familiarity: must be a mapping")
    _require_exact_keys(raw, {"strong", "moderate"}, "familiarity")

    strong_raw = raw["strong"]
    moderate_raw = raw["moderate"]
    _require(isinstance(strong_raw, dict), "familiarity.strong: must be a mapping")
    _require(isinstance(moderate_raw, dict), "familiarity.moderate: must be a mapping")
    _require_exact_keys(strong_raw, _FAMILIARITY_STRONG_KEYS, "familiarity.strong")
    _require_exact_keys(moderate_raw, _FAMILIARITY_MODERATE_KEYS, "familiarity.moderate")

    strong = FamiliarityStrong(
        min_blame_overlap_pct=_require_percentage(
            strong_raw["min_blame_overlap_pct"], "familiarity.strong.min_blame_overlap_pct"
        ),
    )
    moderate = FamiliarityModerate(
        min_prior_prs=_require_positive_int(moderate_raw["min_prior_prs"], "familiarity.moderate.min_prior_prs"),
        max_days_since_touch=_require_positive_int(
            moderate_raw["max_days_since_touch"], "familiarity.moderate.max_days_since_touch"
        ),
    )
    return FamiliarityPolicy(strong=strong, moderate=moderate)


def _require_repo_relative(value: str, context: str) -> None:
    """A source locator must stay inside the checked-out tree - no absolute path, no `..`.

    The workflow pins `ref: master`, so sources are read from the trusted
    checkout; an absolute or escaping locator could reach outside it.
    """
    parts = PurePosixPath(value).parts
    _require(not PurePosixPath(value).is_absolute(), f"{context}: must be repo-relative, not absolute")
    _require(".." not in parts, f"{context}: must not escape the repo (no '..')")


def _parse_ownership(raw: Any, known_formats: Mapping[str, str]) -> tuple[OwnershipSource, ...]:
    _require(isinstance(raw, dict), "ownership: must be a mapping")
    _require_exact_keys(raw, {"sources"}, "ownership")
    sources_raw = raw["sources"]
    _require(isinstance(sources_raw, list) and bool(sources_raw), "ownership.sources: must be a non-empty list")

    formats = dict(known_formats)
    sources: list[OwnershipSource] = []
    for index, entry in enumerate(sources_raw):
        context = f"ownership.sources[{index}]"
        _require(isinstance(entry, dict), f"{context}: must be a mapping")
        _require(
            not set(entry) - {"format", "path", "glob"},
            f"{context}: unknown keys {sorted(set(entry) - {'format', 'path', 'glob'})}",
        )

        fmt = entry.get("format")
        _require(isinstance(fmt, str) and fmt in formats, f"{context}.format: must be one of {sorted(formats)}")

        key = formats[fmt]
        locator_keys = {"path", "glob"} & set(entry)
        _require(locator_keys == {key}, f"{context}: format {fmt!r} takes exactly one locator, {key!r}")
        value = entry[key]
        _require(isinstance(value, str) and bool(value), f"{context}.{key}: must be a non-empty string")
        _require_repo_relative(value, f"{context}.{key}")
        sources.append(OwnershipSource(format=fmt, **{key: value}))
    return tuple(sources)


def load_policy(
    policy_path: Path | None = None, *, lockfile_names: Iterable[str], ownership_formats: Mapping[str, str]
) -> Policy:
    """Parse and validate `.stamphog/policy.yml`, splicing code-derived data.

    `lockfile_names` are the deps_toolchain lockfile filenames owned by
    gates.py's DEPENDENCY_ECOSYSTEMS table; the loader re.escapes them and
    splices them into the deps_toolchain deny paths (they stay code-sourced,
    never copied into the YAML). `ownership_formats` maps each source-format
    name gates.py's OWNERSHIP_FORMATS registry knows how to build to its
    required locator key ("path" or "glob"); the loader validates every
    `ownership.sources[*]` format and locator pairing against it (same
    code-sourced pattern as lockfile_names). Raises PolicyError on any
    malformed input.
    """
    path = policy_path or default_policy_path()
    try:
        raw = yaml.safe_load(path.read_text())
    except (OSError, yaml.YAMLError) as exc:
        raise PolicyError(f"could not read/parse {path}: {exc}") from exc

    _require(isinstance(raw, dict), "policy root: must be a mapping")
    unknown = set(raw) - _TOP_LEVEL_KEYS
    _require(not unknown, f"policy root: unknown top-level keys {sorted(unknown)}")
    for required in _TOP_LEVEL_KEYS:
        _require(required in raw, f"policy root: missing required section {required!r}")
    _require(raw["version"] == 1, f"policy version: unsupported version {raw['version']!r}")

    path_patterns, extensions = _parse_allow(raw["allow"])
    return Policy(
        version=1,
        deny=_parse_deny(raw["deny"], lockfile_names),
        allow_path_patterns=path_patterns,
        allow_extensions=extensions,
        size_gate=_parse_size_gate(raw["size_gate"]),
        t1_subclasses=_parse_tiers(raw["tiers"]),
        dismiss=_parse_dismiss(raw["dismiss"]),
        overrides=_parse_overrides(raw["overrides"]),
        familiarity=_parse_familiarity(raw["familiarity"]),
        ownership=_parse_ownership(raw["ownership"], ownership_formats),
    )


# ── Per-folder override resolution ───────────────────────────────

FOLDER_PROSE_MAX_LEN = 2000
_PROSE_TRUNCATION_MARKER = "\n[... folder policy guidance truncated ...]"
_FOLDER_POLICY_FILENAME = "AGENT_APPROVALS.md"
_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n?(.*)\Z", re.DOTALL)


@dataclass(frozen=True)
class _FolderOverride:
    """Result of parsing a folder AGENT_APPROVALS.md."""

    max_files: int | None = None
    prose: str | None = None
    invalid: bool = False


def _scope_chain_for(
    file_path: str, root: Path, cache: dict[PurePosixPath, tuple[PurePosixPath, ...]]
) -> tuple[PurePosixPath, ...]:
    """Directories carrying an AGENT_APPROVALS.md at or above `file_path`, nearest first.

    A child folder file refines its ancestors rather than replacing them, so the
    whole ancestor chain governs the file, not just the nearest folder. Empty
    when no folder file governs the path (the file belongs to the global pool).
    Per-directory cache keeps this one stat per distinct directory: it maps a
    directory to the full chain of policy-bearing directories at or above it.
    """
    start = PurePosixPath(file_path).parent
    if start in cache:
        return cache[start]

    # Walk up until a directory already resolved (or the root), remembering the
    # directories we still have to stat.
    pending: list[PurePosixPath] = []
    tail: tuple[PurePosixPath, ...] = ()
    for rel in [start, *start.parents]:
        if rel in cache:
            tail = cache[rel]
            break
        pending.append(rel)

    # Fill the cache outermost-first so each directory builds on its parent's
    # chain; prepending keeps the whole chain nearest-first.
    for rel in reversed(pending):
        if (root / rel / _FOLDER_POLICY_FILENAME).is_file():
            tail = (rel, *tail)
        cache[rel] = tail
    return cache[start]


def _sanitize_folder_prose(raw: str) -> str:
    """Strip invisibles and cap folder prose, appending a marker when truncated."""
    cleaned = _INVISIBLE_CHARS_RE.sub("", raw).strip()
    if len(cleaned) > FOLDER_PROSE_MAX_LEN:
        return cleaned[:FOLDER_PROSE_MAX_LEN] + _PROSE_TRUNCATION_MARKER
    return cleaned


def _parse_folder_policy(path: Path, contract: dict[str, OverrideContract]) -> _FolderOverride:
    """Positive allow-list parse of a folder AGENT_APPROVALS.md.

    Reads ONLY the delegated keys from the `stamphog:` frontmatter block within
    contract ceilings; any bad frontmatter, undelegated key, or out-of-bounds
    value invalidates the whole file (frontmatter AND prose), never crashing.
    """
    try:
        text = path.read_text()
    except OSError:
        return _FolderOverride(invalid=True)

    frontmatter_match = _FRONTMATTER_RE.match(text)
    if frontmatter_match is None:
        return _FolderOverride(invalid=True)

    try:
        frontmatter = yaml.safe_load(frontmatter_match.group(1))
    except yaml.YAMLError:
        return _FolderOverride(invalid=True)
    if not isinstance(frontmatter, dict):
        return _FolderOverride(invalid=True)

    prose = _sanitize_folder_prose(frontmatter_match.group(2))

    stamphog = frontmatter.get("stamphog")
    if stamphog is None:
        # Advisory-only file: no delegated override, prose still applies.
        return _FolderOverride(max_files=None, prose=prose or None)
    if not isinstance(stamphog, dict):
        return _FolderOverride(invalid=True)

    # Positive allow-list: the only delegated path is size_gate.max_files.
    max_files = _read_delegated_max_files(stamphog, contract)
    if max_files is None:
        return _FolderOverride(invalid=True)
    return _FolderOverride(max_files=max_files, prose=prose or None)


def _read_delegated_max_files(stamphog: dict[str, Any], contract: dict[str, OverrideContract]) -> int | None:
    """Return the delegated max_files if valid and within ceiling, else None (invalid)."""
    if "size_gate.max_files" not in contract:
        return None
    if set(stamphog) - {"size_gate"}:
        return None
    size_gate = stamphog.get("size_gate")
    if not isinstance(size_gate, dict) or set(size_gate) - {"max_files"}:
        return None
    value = size_gate.get("max_files")
    if not isinstance(value, int) or isinstance(value, bool):
        return None
    ceiling = contract["size_gate.max_files"].ceiling
    if value < 1 or value > ceiling:
        return None
    return value


def resolve(policy: Policy, changed_files: list[str]) -> EffectivePolicy:
    """Resolve the per-scope size budgets for a PR's changed files.

    Every AGENT_APPROVALS.md at or above a changed file governs it. A file's size
    budget comes from the nearest folder on its chain with a valid max_files
    grant; files whose chain grants nothing (no folder file, prose-only, or only
    invalid grants) pool into the global budget. Advisory prose accumulates from
    every valid folder file on the chain of at least one changed file, outermost
    first so general guidance precedes specific. An invalid folder file is
    treated as absent - it grants nothing and adds no prose, but its ancestors
    still apply - and is reported in invalid_folder_files.
    """
    root = repo_root()
    dir_cache: dict[PurePosixPath, tuple[PurePosixPath, ...]] = {}
    parse_cache: dict[PurePosixPath, tuple[str, _FolderOverride]] = {}

    def parsed_for(scope_dir: PurePosixPath) -> tuple[str, _FolderOverride]:
        if scope_dir not in parse_cache:
            rel_path = (scope_dir / _FOLDER_POLICY_FILENAME).as_posix()
            parse_cache[scope_dir] = (rel_path, _parse_folder_policy(root / rel_path, policy.overrides))
        return parse_cache[scope_dir]

    # Files sharing a granting AGENT_APPROVALS.md pool into one budget; the folder
    # files touched by any chain feed the prose and invalid-file reporting.
    grant_files: dict[str, list[str]] = {}
    grant_max: dict[str, int] = {}
    global_files: list[str] = []
    on_chain: dict[str, _FolderOverride] = {}  # rel path -> parse, each file once
    for file_path in changed_files:
        grant: tuple[str, int] | None = None
        for scope_dir in _scope_chain_for(file_path, root, dir_cache):
            rel_path, parsed = parsed_for(scope_dir)
            on_chain[rel_path] = parsed
            if grant is None and not parsed.invalid and parsed.max_files is not None:
                grant = (rel_path, parsed.max_files)
        if grant is None:
            global_files.append(file_path)
        else:
            grant_files.setdefault(grant[0], []).append(file_path)
            grant_max[grant[0]] = grant[1]

    override_scopes = [
        ScopeBudget(path=rel_path, max_files=grant_max[rel_path], files=tuple(files))
        for rel_path, files in sorted(grant_files.items())
    ]

    prose_parts: list[tuple[str, str]] = []
    invalid_files: list[str] = []
    for rel_path, parsed in on_chain.items():
        if parsed.invalid:
            invalid_files.append(rel_path)
        elif parsed.prose:
            prose_parts.append((rel_path, parsed.prose))
    # Outermost first: shallower path depth wins, ties broken lexicographically.
    prose_parts.sort(key=lambda item: (item[0].count("/"), item[0]))
    invalid_files.sort()

    if len(prose_parts) == 1:
        folder_prose = prose_parts[0][1]
    elif prose_parts:
        folder_prose = "\n\n".join(f"[{path}]\n{prose}" for path, prose in prose_parts)
    else:
        folder_prose = None

    scopes = (*override_scopes, ScopeBudget(path=None, max_files=policy.size_gate.max_files, files=tuple(global_files)))
    return EffectivePolicy(
        max_lines=policy.size_gate.max_lines,
        scopes=scopes,
        folder_prose=folder_prose,
        invalid_folder_files=tuple(invalid_files),
    )
