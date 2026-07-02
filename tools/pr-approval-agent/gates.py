"""Deterministic gate logic for PR approval classification.

Handles deny-lists, allow-lists, CODEOWNERS-soft ownership,
tier assignment, and file classification. No external dependencies.
"""

import re
from collections import Counter
from fnmatch import fnmatch
from pathlib import Path

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
# Two pattern lists per category:
#   "paths"  — matched against file paths (hard deny)
#   "any"    — matched against file paths (hard deny) and the PR title
#              (scrutiny flag only)

_DENY_PATTERN_DEFS: dict[str, dict[str, list[str]]] = {
    "auth": {
        "any": [
            "auth",
            "login",
            "signup",
            "oauth",
            "saml",
            "sso",
            "oidc",
            "credential",
            "password",
            "2fa",
            "mfa",
        ],
        # "session" and "token" match too broadly in titles and non-auth
        # file paths (e.g. SessionAnalysisWarning, tokenize, tokenizer).
        # "permission" matches permission-checking helpers everywhere.
        # Restrict these to path-only with tighter patterns.
        # "authentication"/"authorize"/"authorization" are here because the
        # word-boundary regex doesn't break inside them, so a bare "auth"
        # pattern misses posthog/api/authentication.py and the whole
        # frontend/src/scenes/authentication/ tree.
        "paths": [
            "session_auth",
            "session_token",
            "auth/session",
            "auth/token",
            "permission",
            "authentication",
            "authorize",
            "authorization",
        ],
    },
    "crypto_secrets": {
        "any": [
            "crypto",
            "encrypt",
            "decrypt",
            "vault",
        ],
        # "key", "secret", "cert", "signing" are too broad for titles.
        # "key" alone matches "keyboard", "hotkey", "localStorage key".
        # Use path-only with compound patterns.
        "paths": [
            "secret",
            r"api[_-]?key",
            r"secret[_-]?key",
            r"private[_-]?key",
            r"signing[_-]?key",
            "certificate",
            r"\.env",
            r"\.pem",
        ],
    },
    "migrations": {
        # `migrations/` substring is load-bearing — also catches rust
        # *_migrations/ dirs applied by sqlx at deploy.
        "paths": [
            "migrations/",
            "schema_change",
        ],
    },
    "infra_cicd": {
        "any": [
            "terraform",
            "kubernetes",
            "helm",
        ],
        # "routing" and "deploy" are gone on purpose: every historical match
        # was app-level (posthog/api/routing.py DRF routers, Slack/Teams
        # message-routing tests, deploy-timing docs), never infrastructure.
        "paths": [
            r"k8s",
            "dockerfile",
            "docker-compose",
            r"\.github/workflows",
            "iam",
            "cloudflare",
            "cdn",
            "waf",
        ],
    },
    "billing": {
        # "subscription" is gone on purpose: in this repo it means scheduled
        # insight/report deliveries (ee/api/subscription.py, products/exports),
        # not payments. Real billing surfaces still match via the other words.
        "any": [
            "billing",
            "payment",
            "stripe",
            "invoice",
            "pricing",
        ],
    },
    "public_api": {
        "any": [
            "openapi",
            "api_schema",
            "swagger",
            "public_api",
        ],
    },
    "deps_toolchain": {
        # All path-only — these are literal filenames, not title words.
        "paths": [
            r"package\.json",
            r"requirements\.txt",
            r"pyproject\.toml",
            "pnpm-lock",
            "package-lock",
            r"yarn\.lock",
            r"uv\.lock",
            r"Cargo\.toml",
            r"go\.mod",
            "Makefile",
            "Dockerfile",
            "tsconfig",
            r"\.tool-versions",
            r"\.nvmrc",
        ],
    },
}


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
    "any" patterns are compiled twice: once for paths, once for titles,
    and stored as a list of (path_rx, title_rx) tuples.
    """
    compiled: dict[str, dict[str, list]] = {}
    for category, groups in defs.items():
        compiled[category] = {}
        for scope, patterns in groups.items():
            if scope == "paths":
                compiled[category][scope] = [_compile_pattern(p, for_paths=True) for p in patterns]
            else:
                # "any" — store (path_regex, title_regex) pairs
                compiled[category][scope] = [
                    (_compile_pattern(p, for_paths=True), _compile_pattern(p, for_paths=False)) for p in patterns
                ]
    return compiled


DENY_PATTERNS = _compile_patterns(_DENY_PATTERN_DEFS)

ALLOW_ONLY_EXTENSIONS = {
    ".md",
    ".mdx",
    ".txt",
    ".rst",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".cfg",
    ".csv",
    ".svg",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".ico",
    ".webp",
    ".snap",
    ".lock",
}

ALLOW_PATH_PATTERNS = [
    "docs/",
    "README",
    "CHANGELOG",
    "LICENSE",
    "CONTRIBUTING",
    ".github/CODEOWNERS",
    ".gitignore",
    ".editorconfig",
    "generated/",
    "__snapshots__/",
]

# ── Dismiss-time allow-list ──────────────────────────────────────
#
# Stricter than ALLOW_PATH_PATTERNS / ALLOW_ONLY_EXTENSIONS. Used by
# dismiss_check.py to decide whether to retain Stamphog's prior approval
# after new commits land on a PR. At approve time the LLM also reviews;
# at dismiss time the path alone is the only signal, so this list excludes
# anything that could carry executable code into CI, prod, or the build
# pipeline (workflows, configs, build files) even though those paths may
# be allow-listed at approve time.

DISMISS_TIME_LOCKFILES: frozenset[str] = frozenset(
    {
        "package-lock.json",
        "pnpm-lock.yaml",
        "yarn.lock",
        "uv.lock",
        "cargo.lock",
        "pipfile.lock",
        "poetry.lock",
        "gemfile.lock",
        "composer.lock",
    }
)

_DISMISS_TIME_TEST_RE = re.compile(
    r"(?:^|/)(?:__tests__|tests?|fixtures)/"
    r"|(?:^|/)test_[^/]+\.py$"
    r"|_test\.(py|go)$"
    r"|\.test\.(ts|tsx|js|jsx)$"
    r"|\.spec\.(ts|tsx|js|jsx)$"
    r"|(?:^|/)conftest\.py$",
    re.IGNORECASE,
)

# Non-executable-at-dismiss-time on purpose: at dismiss time the path is
# the only signal, so generated files in runnable backend languages
# (.py, .go) trigger re-review even though the LLM accepted them at
# approve time. Type stubs (.pyi) are read by type checkers, not runtime.
# Real-world cost in this repo: proto regen under
# posthog/personhog_client/proto/generated/ falls through to re-review,
# which is rare and cheap.
_DISMISS_TIME_GENERATED_RE = re.compile(
    r"(?:^|/)generated/.*\.(ts|tsx|js|jsx|json|md|snap|pyi|txt)$"
    r"|\.gen\.(ts|tsx|js|jsx)$"
    r"|\.generated\.(ts|tsx|js|jsx)$"
    r"|^frontend/src/queries/schema/",
    re.IGNORECASE,
)


def is_trivial_at_dismiss_time(path: str) -> bool:
    """Return True if `path` alone is safe enough to retain a prior approval.

    Strictly narrower than `is_allow_listed_only`: excludes `.github/**`,
    bare `*.yaml`/`*.json` configs, `Dockerfile*`, `*.sh`, `Makefile`, and
    anything else that can execute or alter build/CI behavior.
    """
    name = Path(path).name
    name_lower = name.lower()
    if name_lower in DISMISS_TIME_LOCKFILES:
        return True

    suffix = Path(path).suffix.lower()
    if suffix in {".md", ".mdx"}:
        return True
    if name_lower.startswith(("readme", "changelog")):
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


_TEST_FILE_RE = re.compile(
    r"(?:^|/)(?:__tests__|tests?)/|[_.](?:test|spec)\.[^/]+$|_test\.py$",
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

# Code under these trees performs auth/OAuth/billing-API handshakes as part of
# its normal job — every data warehouse import connector (Stripe, Google Ads,
# Salesforce, …) — so file names legitimately mention auth, oauth, stripe,
# api_key, etc. without touching the auth *system* or PostHog's own billing.
_CONNECTOR_SOURCE_PREFIXES = ("products/warehouse_sources/backend/temporal/data_imports/sources/",)

# Per-category path prefixes exempt from deny matching. Categories not listed
# (crypto_secrets, migrations, infra_cicd, …) apply everywhere — connector
# code that stores customer API keys still deserves the crypto gate. Add new
# exempt trees here rather than special-casing in detect_deny_categories.
DENY_EXEMPT_PATH_PREFIXES: dict[str, tuple[str, ...]] = {
    "auth": _CONNECTOR_SOURCE_PREFIXES,
    "billing": _CONNECTOR_SOURCE_PREFIXES,
}


def _is_exempt_path(category: str, path: str) -> bool:
    return path.startswith(DENY_EXEMPT_PATH_PREFIXES.get(category, ()))


def detect_deny_categories(files: list[str], ignored_files: set[str] | None = None) -> list[str]:
    """Categories hard-denied by the changed file paths. Titles never deny."""
    hits: set[str] = set()
    ignored_files_lower = {f.lower() for f in ignored_files or set()}
    paths_lower = [f.lower() for f in files if f.lower() not in ignored_files_lower]

    for category, scopes in DENY_PATTERNS.items():
        category_paths = [p for p in paths_lower if not _is_exempt_path(category, p)]
        path_regexes = list(scopes.get("paths", [])) + [path_rx for path_rx, _title_rx in scopes.get("any", [])]
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
    )


def has_dependency_changes(files: list[str]) -> bool:
    dep_files = {
        "package.json",
        "pnpm-lock.yaml",
        "yarn.lock",
        "package-lock.json",
        "requirements.txt",
        "pyproject.toml",
        "uv.lock",
        "Cargo.toml",
        "go.mod",
        "go.sum",
    }
    dep_files_lower = {d.lower() for d in dep_files}
    return any(Path(f).name.lower() in dep_files_lower for f in files)


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


# ── CODEOWNERS-soft ──────────────────────────────────────────────


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


def detect_ownership(files: list[str], rules: list[CodeownersRule]) -> dict:
    all_teams: set[str] = set()
    owned_files = 0
    unowned_files = 0
    team_file_counts: Counter = Counter()

    for f in files:
        teams = resolve_owners(f, rules)
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


# ── Size gate ────────────────────────────────────────────────────


MAX_LINES = 500
MAX_FILES = 20

# Files that inflate a diff without adding review surface: prose docs,
# regenerated artifacts, and test snapshots. The size ceiling counts only the
# substantive remainder, so a 2000-line docs rewrite or type regen isn't
# auto-denied. Exempt files still count toward tier/subclass classification
# (which calibrates LLM scrutiny) and still appear in the diff the LLM reads.
# Deliberately narrower than ALLOW_ONLY_EXTENSIONS: .json/.yaml/.toml configs
# change runtime behavior, so they stay in the count.
SIZE_EXEMPT_EXTENSIONS = {
    ".md",
    ".mdx",
    ".txt",
    ".rst",
    ".snap",
    ".ambr",
    ".svg",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".ico",
    ".webp",
    ".lock",
}

_SIZE_EXEMPT_PATH_RE = re.compile(
    r"(?:^|/)(?:docs|__snapshots__|generated)/"
    r"|\.gen\.(ts|tsx|js|jsx)$"
    r"|\.generated\.(ts|tsx|js|jsx)$"
    r"|^frontend/src/queries/schema/",
    re.IGNORECASE,
)


def is_size_exempt(path: str) -> bool:
    if Path(path).suffix.lower() in SIZE_EXEMPT_EXTENSIONS:
        return True
    return bool(_SIZE_EXEMPT_PATH_RE.search(path))


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


def t1_risk_subclass(
    *,
    lines_total: int,
    files_changed: int,
    breadth: str,
) -> str:
    if lines_total <= 20 and files_changed <= 3 and breadth == "single-area":
        return "T1a-trivial"
    if lines_total <= 100 and files_changed <= 5 and breadth != "cross-cutting":
        return "T1b-small"
    if lines_total <= 300 and files_changed <= 15 and breadth != "cross-cutting":
        return "T1c-medium"
    return "T1d-complex"
