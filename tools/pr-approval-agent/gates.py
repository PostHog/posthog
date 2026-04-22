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
# Two pattern lists per category:
#   "paths"  — matched against file paths only
#   "any"    — matched against both file paths and the PR title
# If a category only has "any", all patterns apply everywhere.

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
        "paths": [
            "session_auth",
            "session_token",
            "auth/session",
            "auth/token",
            "permission",
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
        "paths": [
            "migrations/",
            "migrate",
            "backfill",
            "schema_change",
        ],
    },
    "infra_cicd": {
        "any": [
            "terraform",
            "kubernetes",
            "helm",
        ],
        "paths": [
            r"k8s",
            "dockerfile",
            "docker-compose",
            r"\.github/workflows",
            "deploy",
            "iam",
            "cloudflare",
            "cdn",
            "waf",
            "routing",
        ],
    },
    "billing": {
        "any": [
            "billing",
            "payment",
            "stripe",
            "invoice",
            "subscription",
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


def detect_deny_categories(files: list[str], subject: str) -> list[str]:
    hits: set[str] = set()
    paths_lower = [f.lower() for f in files]
    subject_lower = subject.lower()

    for category, scopes in DENY_PATTERNS.items():
        found = False
        # "paths" patterns — only match against file paths
        for rx in scopes.get("paths", []):
            if found:
                break
            for p in paths_lower:
                if rx.search(p):
                    hits.add(category)
                    found = True
                    break
        if found:
            continue
        # "any" patterns — match against file paths (path_rx) and title (title_rx)
        for path_rx, title_rx in scopes.get("any", []):
            if found:
                break
            for p in paths_lower:
                if path_rx.search(p):
                    hits.add(category)
                    found = True
                    break
            if not found and title_rx.search(subject_lower):
                hits.add(category)
                found = True
    return sorted(hits)


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


# ── Tier assignment ──────────────────────────────────────────────


MAX_LINES = 500
MAX_FILES = 20


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
