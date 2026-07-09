"""Deterministic gate logic for PR approval classification.

Handles deny-lists, allow-lists, multi-source ownership (declared in
`.stamphog/policy.yml`), tier assignment, and file classification. Policy data
loads from .stamphog/policy.yml at import via policy.py, which needs PyYAML:
any uv-run script that imports this module must declare pyyaml in its PEP 723
dependencies block.
"""

import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path
from typing import Protocol

import yaml
from policy import OwnershipSource, load_policy

# ── Dependency ecosystems ────────────────────────────────────────
#
# Source of truth for how each package ecosystem pairs manifests with
# lockfiles. The deps_toolchain deny patterns, DISMISS_TIME_LOCKFILES, and
# the manifest/lockfile helper sets all derive from this table — add a new
# ecosystem here, not in several places. (requirements*.{txt,in} stays out:
# a pinned requirements.txt is arguably both manifest and lockfile, so
# has_dependency_changes recognizes it directly instead of forcing it into
# one column of this table.)
#
# `manifests` entries are fnmatch patterns, not just literal names — a
# plain filename like "package.json" matches itself, so ecosystems with no
# glob needs can still write literal names.


@dataclass(frozen=True)
class Ecosystem:
    manifests: frozenset[str]
    lockfiles: frozenset[str]
    # Whether this ecosystem's lockfiles are trivially trusted at dismiss
    # time (a lockfile-only push retains a prior stamphog approval without
    # LLM re-review). Defaults to NOT trusted so a newly added ecosystem
    # narrows trust rather than silently widening it — dismiss-time trust
    # is an explicit decision made here, not inherited from the deny list.
    trusted_at_dismiss: bool = False


DEPENDENCY_ECOSYSTEMS: dict[str, Ecosystem] = {
    "node": Ecosystem(
        manifests=frozenset({"package.json"}),
        lockfiles=frozenset({"pnpm-lock.yaml", "package-lock.json", "yarn.lock", "npm-shrinkwrap.json"}),
        trusted_at_dismiss=True,
    ),
    "python": Ecosystem(
        # setup.py/setup.cfg execute code at install/build time even though
        # no lockfile pairs with them in this repo.
        manifests=frozenset({"pyproject.toml", "setup.py", "setup.cfg", "pipfile"}),
        lockfiles=frozenset({"uv.lock", "poetry.lock", "pipfile.lock"}),
        trusted_at_dismiss=True,
    ),
    "ruby": Ecosystem(
        manifests=frozenset({"gemfile"}),
        lockfiles=frozenset({"gemfile.lock"}),
        trusted_at_dismiss=True,
    ),
    # No composer usage in-repo today; listed so a future composer.json
    # doesn't arrive ungated.
    "php": Ecosystem(
        manifests=frozenset({"composer.json"}),
        lockfiles=frozenset({"composer.lock"}),
        trusted_at_dismiss=True,
    ),
    "rust": Ecosystem(
        manifests=frozenset({"cargo.toml"}),
        lockfiles=frozenset({"cargo.lock"}),
        trusted_at_dismiss=True,
    ),
    # go.sum deliberately stays untrusted at dismiss time: it hashes what
    # go.mod names rather than being the sole source of installed code.
    "go": Ecosystem(
        manifests=frozenset({"go.mod"}),
        lockfiles=frozenset({"go.sum"}),
    ),
    # tsconfig configures the compiler, not dependencies — no lockfile ever
    # pairs with it, so a tsconfig change is always flagged for scrutiny
    # (empty `lockfiles` means dependency_manifests_without_lockfile can
    # never find a paired lockfile to suppress it).
    "typescript": Ecosystem(
        manifests=frozenset({"tsconfig*.json"}),
        lockfiles=frozenset(),
    ),
}

_ALL_LOCKFILE_NAMES: frozenset[str] = frozenset().union(*(e.lockfiles for e in DEPENDENCY_ECOSYSTEMS.values()))

# Call sites match against Path(...).name.lower(), so a mixed-case table entry
# would silently never match — a fail-open hole in a security gate. Enforce the
# invariant at import so a bad entry fails the gate closed (the tool crashes
# instead of auto-approving). A raise, not an assert, so python -O can't strip
# it; test_dependency_ecosystem_names_are_lowercase covers it once the suite is
# wired into CI.
if any(
    n != n.lower()
    for spec in DEPENDENCY_ECOSYSTEMS.values()
    for names in (spec.manifests, spec.lockfiles)
    for n in names
):
    raise ValueError("DEPENDENCY_ECOSYSTEMS names must be lowercase — call sites match against Path(...).name.lower()")


def _ecosystem_for_manifest(name: str) -> str | None:
    for ecosystem, spec in DEPENDENCY_ECOSYSTEMS.items():
        if any(fnmatch(name, pattern) for pattern in spec.manifests):
            return ecosystem
    return None


# ── Pattern data ─────────────────────────────────────────────────

# Deny patterns use word-boundary matching (\b) to avoid false positives
# from substring hits like "session" in "SessionAnalysis" or "key" in
# "localStorage key". Patterns are compiled into regexes at import time.
#
# Only file paths hard-deny. PR titles never deny on their own: calibration
# against ~440 deny-listed PRs showed title-only hits were dominated by
# incidental mentions ("treat OAuth invalid_grant as non-retryable" in a
# connector fix) that humans approved unchanged. Title matches surface as
# scrutiny flags for the LLM instead (see detect_title_scrutiny_flags),
# which reads the actual diff and can refuse when the change really does
# touch the flagged domain.
#
# Three pattern lists per category:
#   "paths"  — matched against file paths (hard deny)
#   "any"    — matched against file paths (hard deny) and the PR title
#              (scrutiny flag only)
#   "titles" — matched against the PR title only (scrutiny flag, never a
#              deny) — for words whose path-side hits are false positives

# ── Ownership sources ────────────────────────────────────────────
#
# Ownership is advisory reviewer context, not a hard gate. The sources are
# declared in `.stamphog/policy.yml` (`ownership:`) and compiled here into
# resolvers; each resolver answers "which teams own this file?" and the
# per-file result is the union across sources. Two formats ship today:
# `gh-codeowners` (a CODEOWNERS-soft file, last-match-wins) and `ph-product`
# (products/*/product.yaml owners). OWNERSHIP_FORMATS is the single place a new
# format registers.


class OwnershipResolver(Protocol):
    """A compiled ownership source: which teams own a given file."""

    def owners(self, filepath: str) -> set[str]: ...


class CodeownersRule:
    def __init__(self, pattern: str, teams: list[str]):
        self.raw_pattern = pattern
        self.teams = set(teams)
        self._pattern = pattern.lstrip("/").replace("\\*\\*", "**").replace("\\*", "*")

    def matches(self, filepath: str) -> bool:
        pat = self._pattern
        if not any(c in pat for c in ("*", "?")):
            if filepath == pat or filepath == pat.rstrip("/"):
                return True
            prefix = pat if pat.endswith("/") else pat + "/"
            if filepath.startswith(prefix):
                return True
            return False
        if fnmatch(filepath, pat):
            return True
        if "**" in pat and fnmatch(filepath, pat.rstrip("/") + "/**"):
            return True
        return False


def parse_codeowners_soft(path: Path) -> list[CodeownersRule]:
    rules = []
    if not path.exists():
        return rules
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            pattern = parts[0]
            teams = [t for t in parts[1:] if t.startswith("@")]
            if teams:
                rules.append(CodeownersRule(pattern, teams))
    return rules


def resolve_owners(filepath: str, rules: list[CodeownersRule]) -> set[str]:
    matched_teams: set[str] = set()
    for rule in rules:
        if rule.matches(filepath):
            matched_teams = rule.teams
    return matched_teams


class _CodeownersResolver:
    """gh-codeowners: last-match-wins CODEOWNERS-soft semantics over one file."""

    def __init__(self, rules: list[CodeownersRule]) -> None:
        self._rules = rules

    def owners(self, filepath: str) -> set[str]:
        return set(resolve_owners(filepath, self._rules))


def _normalize_product_owner(slug: object) -> str | None:
    """Normalize a product.yaml owner slug exactly like assign-reviewers.js.

    Skip empty / `team-CHANGEME` / already-`@`-prefixed slugs (an existing
    prefix would build `@PostHog/@PostHog/...`); otherwise prefix `@PostHog/`.
    """
    if not isinstance(slug, str):
        return None
    slug = slug.strip()
    if not slug or slug == "team-CHANGEME" or slug.startswith("@"):
        return None
    return f"@PostHog/{slug}"


def _read_product_owners(path: Path) -> frozenset[str]:
    """Normalized owners from a product.yaml, or empty on any parse/shape problem."""
    try:
        data = yaml.safe_load(path.read_text())
    except (OSError, yaml.YAMLError):
        return frozenset()
    if not isinstance(data, dict) or not isinstance(data.get("owners"), list):
        return frozenset()
    teams = {norm for slug in data["owners"] if (norm := _normalize_product_owner(slug)) is not None}
    return frozenset(teams)


class _ProductYamlResolver:
    """ph-product: each product.yaml owns its parent directory subtree."""

    def __init__(self, owned_dirs: dict[str, frozenset[str]]) -> None:
        # Maps a repo-relative directory (posix, no trailing slash) to its owners.
        self._owned_dirs = owned_dirs

    def owners(self, filepath: str) -> set[str]:
        result: set[str] = set()
        for directory, teams in self._owned_dirs.items():
            if filepath.startswith(directory + "/"):
                result |= teams
        return result


def _build_codeowners_resolver(repo_root: Path, source: OwnershipSource) -> _CodeownersResolver:
    assert source.path is not None  # validated by the loader (gh-codeowners uses `path`)
    return _CodeownersResolver(parse_codeowners_soft(repo_root / source.path))


def _build_product_yaml_resolver(repo_root: Path, source: OwnershipSource) -> _ProductYamlResolver:
    assert source.glob is not None  # validated by the loader (ph-product uses `glob`)
    owned_dirs: dict[str, frozenset[str]] = {}
    for yaml_path in sorted(repo_root.glob(source.glob)):
        teams = _read_product_owners(yaml_path)
        if teams:
            owned_dirs[yaml_path.parent.relative_to(repo_root).as_posix()] = teams
    return _ProductYamlResolver(owned_dirs)


@dataclass(frozen=True)
class OwnershipFormat:
    """A registered source format: its required locator key and resolver builder."""

    locator: str  # "path" or "glob" - which locator the format's builder reads
    build: Callable[[Path, OwnershipSource], OwnershipResolver]


# Registry: format name -> format. Adding a new ownership format is a one-line
# entry here plus its resolver above; the loader validates each declared
# source's format name and locator pairing against this table.
OWNERSHIP_FORMATS: dict[str, OwnershipFormat] = {
    "gh-codeowners": OwnershipFormat("path", _build_codeowners_resolver),
    "ph-product": OwnershipFormat("glob", _build_product_yaml_resolver),
}

OWNERSHIP_FORMAT_LOCATORS: dict[str, str] = {name: fmt.locator for name, fmt in OWNERSHIP_FORMATS.items()}


def build_ownership(repo_root: Path, sources: tuple[OwnershipSource, ...]) -> list[OwnershipResolver]:
    """Compile the declared ownership sources into resolvers, in declared order."""
    return [OWNERSHIP_FORMATS[source.format].build(repo_root, source) for source in sources]


def detect_ownership(files: list[str], resolvers: list[OwnershipResolver]) -> dict:
    """Aggregate per-file team ownership, unioning each source's owners per file."""
    all_teams: set[str] = set()
    owned_files = 0
    unowned_files = 0
    team_file_counts: Counter = Counter()

    for f in files:
        teams: set[str] = set()
        for resolver in resolvers:
            teams |= resolver.owners(f)
        if teams:
            owned_files += 1
            all_teams.update(teams)
            for t in teams:
                team_file_counts[t] += 1
        else:
            unowned_files += 1

    return {
        "teams": sorted(all_teams),
        "team_count": len(all_teams),
        "owned_files": owned_files,
        "unowned_files": unowned_files,
        "team_file_counts": dict(team_file_counts.most_common()),
        "cross_team": len(all_teams) > 1,
    }


# ── Policy-sourced data ──────────────────────────────────────────
#
# The deny/allow/size/tier/dismiss data lives in .stamphog/policy.yml and is
# loaded here at import time, keeping the existing module-level constant names
# populated so importers and tests are unchanged. DEPENDENCY_ECOSYSTEMS (and
# DISMISS_TIME_LOCKFILES below) stay code-derived; the loader splices the
# lockfile names into the deps_toolchain deny paths and validates the declared
# ownership formats against OWNERSHIP_FORMATS. A malformed policy raises at
# import - fail closed, the tool crashes rather than gating on a half-loaded
# policy.
POLICY = load_policy(lockfile_names=_ALL_LOCKFILE_NAMES, ownership_formats=OWNERSHIP_FORMAT_LOCATORS)

_DENY_PATTERN_DEFS: dict[str, dict[str, list[str]]] = POLICY.deny_pattern_defs()


def _compile_pattern(p: str, *, for_paths: bool) -> re.Pattern[str]:
    r"""Compile a single deny pattern into a case-insensitive regex.

    Patterns containing path separators (/) or starting with a dot are
    treated as literal path fragments — no boundaries added.

    For other patterns, boundary matching depends on context:
    - Title matching uses \b (standard word boundaries — underscore is
      a word char, which is correct for natural-language titles).
    - Path matching uses a looser boundary that also breaks on _ and -,
      since file paths use those as separators. This ensures "secret"
      matches "secret_key_store.py" but not "nosecrets.py".
    """
    if "/" in p or p.startswith(r"\."):
        return re.compile(rf"(?i){p}")
    if for_paths:
        # Break on non-alphanumeric (including _ and -) or string edges
        return re.compile(rf"(?i)(?<![a-zA-Z0-9]){p}(?![a-zA-Z0-9])")
    return re.compile(rf"(?i)\b{p}\b")


def _compile_patterns(
    defs: dict[str, dict[str, list[str]]],
) -> dict[str, dict[str, list[re.Pattern[str]]]]:
    """Compile pattern definitions into regexes.

    "paths" patterns use path-friendly boundaries (break on _ and -).
    "titles" patterns use natural-language word boundaries.
    "any" patterns are compiled twice: once for paths, once for titles,
    and stored as a list of (path_rx, title_rx) tuples.
    """
    compiled: dict[str, dict[str, list]] = {}
    for category, groups in defs.items():
        compiled[category] = {}
        for scope, patterns in groups.items():
            if scope == "paths":
                compiled[category][scope] = [_compile_pattern(p, for_paths=True) for p in patterns]
            elif scope == "titles":
                compiled[category][scope] = [_compile_pattern(p, for_paths=False) for p in patterns]
            else:
                # "any" — store (path_regex, title_regex) pairs
                compiled[category][scope] = [
                    (_compile_pattern(p, for_paths=True), _compile_pattern(p, for_paths=False)) for p in patterns
                ]
    return compiled


DENY_PATTERNS = _compile_patterns(_DENY_PATTERN_DEFS)

# Compiled path patterns for stamphog's own policy/engine files. A dismiss-time
# guard consults these so a retained approval can't silently absorb a policy
# edit - .md is otherwise blanket-trivial and AGENT_APPROVALS.md would slip in.
_STAMPHOG_POLICY_PATH_PATTERNS = DENY_PATTERNS["stamphog_policy"]["paths"]

ALLOW_ONLY_EXTENSIONS = set(POLICY.allow_extensions)

ALLOW_PATH_PATTERNS = list(POLICY.allow_path_patterns)

# ── Dismiss-time allow-list ──────────────────────────────────────
#
# Stricter than ALLOW_PATH_PATTERNS / ALLOW_ONLY_EXTENSIONS. Used by
# dismiss_check.py to decide whether to retain Stamphog's prior approval
# after new commits land on a PR. At approve time the LLM also reviews;
# at dismiss time the path alone is the only signal, so this list excludes
# anything that could carry executable code into CI, prod, or the build
# pipeline (workflows, configs, build files) even though those paths may
# be allow-listed at approve time.

# Derived from the ecosystems that explicitly opted in via trusted_at_dismiss
# — dismiss-time trust is a per-ecosystem decision made in the table, never a
# default a new deny-list entry inherits. See the field's comment on Ecosystem.
DISMISS_TIME_LOCKFILES: frozenset[str] = frozenset().union(
    *(spec.lockfiles for spec in DEPENDENCY_ECOSYSTEMS.values() if spec.trusted_at_dismiss)
)

_DISMISS_TIME_TEST_RE = re.compile(POLICY.dismiss.test_regex, re.IGNORECASE)

# Non-executable-at-dismiss-time on purpose: at dismiss time the path is
# the only signal, so generated files in runnable backend languages
# (.py, .go) trigger re-review even though the LLM accepted them at
# approve time. Type stubs (.pyi) are read by type checkers, not runtime.
# Real-world cost in this repo: proto regen under
# posthog/personhog_client/proto/generated/ falls through to re-review,
# which is rare and cheap.
_DISMISS_TIME_GENERATED_RE = re.compile(POLICY.dismiss.generated_regex, re.IGNORECASE)


def is_trivial_at_dismiss_time(path: str) -> bool:
    """Return True if `path` alone is safe enough to retain a prior approval.

    Strictly narrower than `is_allow_listed_only`: excludes `.github/**`,
    bare `*.yaml`/`*.json` configs, `Dockerfile*`, `*.sh`, `Makefile`, and
    anything else that can execute or alter build/CI behavior.
    """
    # Stamphog's own policy/engine files are never trivial at dismiss time -
    # otherwise a retained approval would let a post-approval policy edit land
    # unreviewed (AGENT_APPROVALS.md is .md, which is blanket-trivial below).
    if any(rx.search(path) for rx in _STAMPHOG_POLICY_PATH_PATTERNS):
        return False

    name = Path(path).name
    name_lower = name.lower()
    if name_lower in DISMISS_TIME_LOCKFILES:
        return True

    suffix = Path(path).suffix.lower()
    if suffix in POLICY.dismiss.trivial_extensions:
        return True
    if name_lower.startswith(POLICY.dismiss.trivial_name_prefixes):
        return True
    if path.startswith("docs/") or "/docs/" in path:
        return True
    if "/__snapshots__/" in path or path.startswith("__snapshots__/"):
        return True
    if _DISMISS_TIME_TEST_RE.search(path):
        return True
    if _DISMISS_TIME_GENERATED_RE.search(path):
        return True
    return False


CONVENTIONAL_RE = re.compile(r"^(\w+)(?:\(([^)]*)\))?!?:\s*(.+)")


# ── Conventional commit parsing ──────────────────────────────────


def parse_conventional_commit(subject: str) -> dict:
    m = CONVENTIONAL_RE.match(subject)
    if not m:
        return {"type": None, "scope": None, "description": subject}
    return {"type": m.group(1), "scope": m.group(2), "description": m.group(3)}


# ── File classification ──────────────────────────────────────────


# Directory matching is exact-segment only (__tests__/, test/, tests/, _tests/):
# suffix matching like `*_tests/` catches runtime packages that merely end in
# the word (destination_tests/ is API code, ingestion_acceptance_test/ is a
# Temporal worker). Files inside looser test-tree layouts are still covered by
# the filename branches (test_*.py, *.test.*, *_test.py).
_TEST_FILE_RE = re.compile(
    r"(?:^|/)(?:__tests__|tests?|_tests?)/|(?:^|/)test_[^/]+\.py$|[_.](?:test|spec)\.[^/]+$|_test\.py$",
    re.IGNORECASE,
)


def classify_path(path: str) -> str:
    low = path.lower()
    if _TEST_FILE_RE.search(low):
        return "test"
    if low.endswith(".md"):
        return "docs"
    if "migration" in low:
        return "migration"
    if low.endswith((".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".lock")):
        return "config"
    if low.endswith((".ts", ".tsx", ".js", ".jsx", ".css", ".scss")):
        return "frontend"
    if low.endswith(".py"):
        return "python"
    return "other"


def classify_files(files: list[str]) -> dict:
    categories: Counter = Counter()
    top_dirs: set[str] = set()
    extensions: Counter = Counter()

    for path in files:
        parts = path.split("/")
        if len(parts) > 1:
            top_dirs.add(parts[0])
            if parts[0] == "products" and len(parts) > 2:
                top_dirs.add(f"products/{parts[1]}")
        if "." in path:
            extensions[path.rsplit(".", 1)[-1]] += 1
        categories[classify_path(path)] += 1

    return {
        "categories": dict(categories),
        "top_dirs": sorted(top_dirs),
        "extensions": dict(extensions),
    }


# ── Scope helpers ────────────────────────────────────────────────


def scope_breadth(top_dirs: list[str]) -> str:
    top = {d.split("/")[0] for d in top_dirs}
    if len(top) <= 1:
        return "single-area"
    if len(top) == 2:
        return "two-areas"
    return "cross-cutting"


def test_only(categories: dict[str, int]) -> bool:
    return categories.get("test", 0) > 0 and sum(categories.values()) == categories.get("test", 0)


# ── Deny / allow detection ───────────────────────────────────────

# Per-category path prefixes exempt from deny matching, sourced from each deny
# category's `exempt_path_prefixes` in the policy file. Categories without an
# entry (crypto_secrets, migrations, infra_cicd, …) apply everywhere - connector
# code that stores customer API keys still deserves the crypto gate. Code under
# the warehouse-connector trees performs auth/OAuth/billing-API handshakes as
# part of its normal job, so it legitimately mentions auth, oauth, stripe,
# api_key, etc. without touching the auth *system* or PostHog's own billing.
DENY_EXEMPT_PATH_PREFIXES: dict[str, tuple[str, ...]] = {
    category: cat.exempt_path_prefixes for category, cat in POLICY.deny.items() if cat.exempt_path_prefixes
}


def _is_exempt_path(category: str, path: str) -> bool:
    return path.lower().startswith(DENY_EXEMPT_PATH_PREFIXES.get(category, ()))


def category_fully_exempt(category: str, files: list[str]) -> bool:
    """True when every changed file is exempt for this category.

    Used to suppress title scrutiny flags on connector-only PRs: a Stripe
    source fix legitimately says "stripe"/"oauth" in its title, and flagging
    it re-creates the friction the path exemption exists to remove.
    """
    return bool(files) and all(_is_exempt_path(category, f) for f in files)


def detect_deny_categories(files: list[str], ignored_files: set[str] | None = None) -> list[str]:
    """Categories hard-denied by the changed file paths. Titles never deny."""
    hits: set[str] = set()
    ignored_files_lower = {f.lower() for f in ignored_files or set()}
    paths_lower = [fl for f in files if (fl := f.lower()) not in ignored_files_lower]

    for category, scopes in DENY_PATTERNS.items():
        category_paths = [p for p in paths_lower if not _is_exempt_path(category, p)]
        path_regexes = scopes.get("paths", []) + [path_rx for path_rx, _title_rx in scopes.get("any", [])]
        if any(rx.search(p) for rx in path_regexes for p in category_paths):
            hits.add(category)
    return sorted(hits)


def detect_title_scrutiny_flags(subject: str) -> list[str]:
    """Categories whose keywords appear in the PR title.

    Not a gate: the reviewer prompt tells the LLM to refuse only when the
    diff behaviorally touches the flagged domain, so incidental mentions
    (an OAuth error string in a connector fix) don't force a human review.
    """
    subject_lower = subject.lower()
    return sorted(
        category
        for category, scopes in DENY_PATTERNS.items()
        if any(title_rx.search(subject_lower) for _path_rx, title_rx in scopes.get("any", []))
        or any(rx.search(subject_lower) for rx in scopes.get("titles", []))
    )


def has_dependency_changes(files: list[str]) -> bool:
    for f in files:
        name = Path(f).name.lower()
        if name in _ALL_LOCKFILE_NAMES or _ecosystem_for_manifest(name) is not None:
            return True
        if name.startswith("requirements") and name.endswith((".txt", ".in")):
            return True
    return False


def is_dependency_manifest(path: str) -> bool:
    return _ecosystem_for_manifest(Path(path).name.lower()) is not None


def dependency_manifests_without_lockfile(files: list[str]) -> list[str]:
    """Manifest files changed without their own ecosystem's lockfile.

    Such a change cannot install new third-party code (CI installs are
    frozen-lockfile), so it passes the deny-list — but manifest scripts/hooks
    execute in CI, so these paths feed the deterministic scripts scan and the
    reviewer prompt. The lockfile check is per-ecosystem: a Cargo.lock bump
    hard-denies on its own but must not silence the scripts guard on an
    unrelated package.json edit in the same PR.
    """
    names = {Path(f).name.lower() for f in files}
    ecosystems_with_lockfile_change = {
        ecosystem for ecosystem, spec in DEPENDENCY_ECOSYSTEMS.items() if names & spec.lockfiles
    }
    return sorted(
        f
        for f in files
        if (ecosystem := _ecosystem_for_manifest(Path(f).name.lower())) is not None
        and ecosystem not in ecosystems_with_lockfile_change
    )


def has_ci_workflow_changes(files: list[str]) -> bool:
    return any(".github/workflows" in f or ".github/actions" in f for f in files)


def is_allow_listed_only(files: list[str]) -> bool:
    if not files:
        return False
    for f in files:
        low = f.lower()
        ext = Path(low).suffix
        if ext in ALLOW_ONLY_EXTENSIONS:
            continue
        if any(p.lower() in low for p in ALLOW_PATH_PATTERNS):
            continue
        return False
    return True


# ── Size gate ────────────────────────────────────────────────────


MAX_LINES = POLICY.size_gate.max_lines
MAX_FILES = POLICY.size_gate.max_files

# Files that inflate a diff without raising auto-approval risk: prose docs,
# regenerated artifacts, test snapshots, and tests (which cannot change
# production runtime behavior; counting them punished exactly the well-tested
# PRs the review philosophy waves through). The size ceiling counts only the substantive
# remainder, so a 2000-line docs rewrite, a type regen, or a fix arriving with
# extensive tests isn't auto-denied. Exempt files still count toward
# tier/subclass classification (which calibrates LLM scrutiny) and still
# appear in the diff the LLM reads.
# Deliberately narrower than ALLOW_ONLY_EXTENSIONS: .json/.yaml/.toml configs
# change runtime behavior, so they stay in the count.
SIZE_EXEMPT_EXTENSIONS = {
    ".md",
    ".mdx",
    ".txt",
    ".rst",
    ".snap",
    ".ambr",
    ".storyshot",
    ".svg",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".ico",
    ".webp",
    ".lock",
}

# __snapshots__/ deliberately has no directory-wide exemption: snapshot
# artifacts are covered by extension (.snap/.ambr/.storyshot), so an
# executable file placed under a snapshots dir still counts toward the
# ceiling — same reasoning as the extension allowlists below.
_SIZE_EXEMPT_PATH_RE = re.compile(
    r"(?:^|/)docs/.*\.(ts|tsx|js|jsx|json|md|snap|pyi|txt)$"
    r"|(?:^|/)generated/.*\.(ts|tsx|js|jsx|json|md|snap|pyi|txt)$"
    r"|\.gen\.(ts|tsx|js|jsx)$"
    r"|\.generated\.(ts|tsx|js|jsx)$"
    r"|^frontend/src/queries/schema/",
    re.IGNORECASE,
)


def is_size_exempt(path: str) -> bool:
    return (
        Path(path).suffix.lower() in SIZE_EXEMPT_EXTENSIONS
        or bool(_SIZE_EXEMPT_PATH_RE.search(path))
        or bool(_TEST_FILE_RE.search(path))
    )


def substantive_size(files: list[dict]) -> tuple[int, int]:
    """(changed lines, file count) over the files that count toward the size ceiling."""
    counted = [f for f in files if not is_size_exempt(f["filename"])]
    return sum(f["additions"] + f["deletions"] for f in counted), len(counted)


# ── Tier assignment ──────────────────────────────────────────────


def assign_tier(
    *,
    deny_categories: list[str],
    allow_listed_only: bool,
    is_test_only: bool,
    has_new_files: bool,
    lines_total: int,
    files_changed: int,
    breadth: str,
    commit_type: str | None,
) -> str:
    if deny_categories:
        return "T2-never"
    if has_new_files:
        return "T1-agent"
    if allow_listed_only:
        return "T0-deterministic"
    if is_test_only:
        return "T0-deterministic"
    return "T1-agent"


def _breadth_within(rule: str, breadth: str) -> bool:
    """Whether a PR's breadth satisfies a sub-tier's breadth rule from the policy.

    `single-area` requires an exact match; `not-cross-cutting` admits anything
    but a cross-cutting change.
    """
    if rule == "single-area":
        return breadth == "single-area"
    return breadth != "cross-cutting"


def t1_risk_subclass(
    *,
    lines_total: int,
    files_changed: int,
    breadth: str,
) -> str:
    # First matching sub-tier wins (policy order is narrowest first); T1d is the
    # engine fallback for anything past the largest configured sub-tier.
    for label, sub in POLICY.t1_subclasses.items():
        if lines_total <= sub.max_lines and files_changed <= sub.max_files and _breadth_within(sub.breadth, breadth):
            return label
    return "T1d-complex"
