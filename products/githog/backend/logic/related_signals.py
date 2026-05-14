"""Filename-token-based fuzzy match against the team's known flag keys / event names.

For PRs that don't literally reference any flag or event but clearly touch
business logic (think: a service refactor, a new endpoint, a migration), we
tokenize the basenames of changed files and look for known flag keys / event
names whose own tokens overlap. These aren't *confirmed* references — they're
*related signals* that share a vocabulary with the touched files.

Imperfect: a file called "alerts.service.ts" produces a 'alerts' token that
will match every flag/event with 'alerts' in the name. That's fine for
hackathon framing — we surface them as suggestions, not assertions, and the
reviewer can dismiss false positives at a glance.
"""

import os
import re
from typing import TYPE_CHECKING

from .event_reach import compute_per_event_reach
from .flag_reach import compute_per_flag_reach

if TYPE_CHECKING:
    from posthog.models import Team

    from ..facade.contracts import RelatedSignal


# Common technical / framing tokens that produce noisy matches against any
# event or flag name in a real codebase. Filtered out before matching.
_STOP_TOKENS: frozenset[str] = frozenset(
    {
        "service",
        "services",
        "controller",
        "module",
        "modules",
        "provider",
        "providers",
        "interface",
        "interfaces",
        "manager",
        "managers",
        "helper",
        "helpers",
        "util",
        "utils",
        "common",
        "shared",
        "core",
        "lib",
        "libs",
        "test",
        "tests",
        "spec",
        "specs",
        "main",
        "index",
        "types",
        "config",
        "configs",
        "schema",
        "schemas",
        "model",
        "models",
        "view",
        "views",
        "page",
        "pages",
        "component",
        "components",
        "hooks",
        "client",
        "server",
        "api",
        "data",
        "store",
        "json",
        "yaml",
        "yml",
        "html",
        "scss",
        "css",
        "tsx",
        "jsx",
        "swift",
        "ruby",
        "python",
        "node",
        "next",
        "app",
        "apps",
        "src",
        "dist",
        "build",
        "public",
        "static",
        "assets",
        "migration",
        "migrations",
        "prisma",
    }
)
_MIN_TOKEN_LEN = 4
_MAX_RELATED = 30


_SPLIT_RE = re.compile(r"[\W_]+", flags=re.UNICODE)
_CAMEL_RE = re.compile(r"(?<!^)(?=[A-Z])")


def _tokenize_filename(path: str) -> set[str]:
    """Extract distinctive lowercase tokens from a file path.

    Splits on path/extension boundaries, kebab/snake delimiters, and
    camelCase. Stop tokens and tokens shorter than 4 chars are dropped.
    """
    if not path:
        return set()
    basename = os.path.basename(path)
    # Strip all extensions ("foo.test.ts" → "foo").
    while True:
        stem, ext = os.path.splitext(basename)
        if not ext:
            break
        basename = stem
    rough = _SPLIT_RE.split(basename)
    tokens: set[str] = set()
    for piece in rough:
        if not piece:
            continue
        for sub in _CAMEL_RE.split(piece):
            t = sub.lower()
            if len(t) < _MIN_TOKEN_LEN or t in _STOP_TOKENS:
                continue
            tokens.add(t)
    return tokens


def _matches_for_terms(known: list[str], tokens: set[str]) -> dict[str, set[str]]:
    """For each known key/name, return the set of file tokens it overlaps.

    A "match" is: the token appears as a substring of the lowercased
    known key/name. Cheap and good enough for fuzzy "shares vocabulary"
    semantics. Skips known names shorter than the token threshold so
    one-letter keys don't shadow everything.
    """
    out: dict[str, set[str]] = {}
    for name in known:
        if not name or len(name) < _MIN_TOKEN_LEN:
            continue
        lower = name.lower()
        for token in tokens:
            if token in lower:
                out.setdefault(name, set()).add(token)
    return out


def find_related_signals(
    team: "Team",
    changed_files: list[str],
    known_flag_keys: list[str],
    known_event_names: list[str],
    lookback_days: int,
    exclude_flag_keys: set[str],
    exclude_event_names: set[str],
) -> list["RelatedSignal"]:
    """Return RelatedSignal entries for keys/names whose tokens overlap touched filenames.

    ``exclude_*`` skips anything already surfaced as a confirmed reference,
    so we don't double-count.
    """
    from ..facade.contracts import RelatedSignal

    tokens: set[str] = set()
    for path in changed_files:
        tokens |= _tokenize_filename(path)
    if not tokens:
        return []

    flag_matches = _matches_for_terms(known_flag_keys, tokens)
    event_matches = _matches_for_terms(known_event_names, tokens)

    # Drop anything already confirmed in the diff.
    flag_matches = {k: toks for k, toks in flag_matches.items() if k not in exclude_flag_keys}
    event_matches = {n: toks for n, toks in event_matches.items() if n not in exclude_event_names}

    if not flag_matches and not event_matches:
        return []

    # Reach for these is real — pull the same numbers we'd pull for a
    # confirmed reference. One query per kind, no per-name N+1.
    flag_keys = list(flag_matches.keys())
    event_names = list(event_matches.keys())
    flag_reach = {r.key: r for r in compute_per_flag_reach(team, flag_keys, lookback_days)}
    event_reach = {r.name: r for r in compute_per_event_reach(team, event_names, lookback_days)}

    out: list[RelatedSignal] = []
    for key, toks in flag_matches.items():
        reach = flag_reach.get(key)
        if reach is None:
            continue
        out.append(
            RelatedSignal(
                kind="flag",
                key=key,
                matched_tokens=tuple(sorted(toks)),
                users_affected=reach.users_affected,
                sessions_affected=reach.sessions_affected,
                call_count=reach.call_count,
                is_server_side=reach.is_server_side,
                has_data=reach.has_data,
            )
        )
    for name, toks in event_matches.items():
        reach = event_reach.get(name)
        if reach is None:
            continue
        out.append(
            RelatedSignal(
                kind="event",
                key=name,
                matched_tokens=tuple(sorted(toks)),
                users_affected=reach.users_affected,
                sessions_affected=reach.sessions_affected,
                call_count=reach.call_count,
                is_server_side=reach.is_server_side,
                has_data=reach.has_data,
            )
        )

    # Rank: data-having first (sorted by users desc), then no-data.
    out.sort(key=lambda r: (not r.has_data, -r.users_affected, -r.call_count, r.key))
    return out[:_MAX_RELATED]
