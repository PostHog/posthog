"""URL-path detection and pageview reach.

Two complementary inputs:

  - **Deterministic extraction**: a regex over added/context diff lines that
    catches obvious path literals like ``"/pricing"``, ``"/api/users"``,
    ``"/checkout/start"``. Cheap, language-agnostic, no framework
    assumptions — but misses paths the diff doesn't spell out (e.g. when
    the route is implied by file location alone).

  - **LLM tool**: ``get_pageview_reach(paths)`` exposed to the orchestrator
    so the model can infer paths from framework conventions (Next.js
    ``app/pricing/page.tsx`` → ``/pricing``, Express
    ``router.get('/users')``, etc.) and pull real reach.

Reach is measured from ``$pageview`` events grouped by
``properties.$pathname``. We deliberately match on ``$pathname`` rather
than ``$current_url`` so query strings and origins don't fragment the
counts.
"""

import re
from typing import TYPE_CHECKING

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

if TYPE_CHECKING:
    from posthog.models import Team

    from ..facade.contracts import WebPathReach


# A "URL path" literal: starts with /, then a letter (avoids /, //, comments),
# then path-safe characters. Bounded length to skip absurdly long matches.
# Captures the whole path including the leading slash.
_PATH_LITERAL_PATTERN = re.compile(r"""["'](/[a-zA-Z][\w\-./\[\]()]{1,120})["']""")

# Paths that almost certainly aren't user-facing URLs in production.
_PATH_BLOCKLIST: frozenset[str] = frozenset(
    {
        "/",  # Too generic — matches everything
        "/dev/null",
        "/tmp",
        "/usr",
        "/var",
        "/etc",
        "/bin",
        "/opt",
        "/home",
        "/root",
    }
)

# Path prefixes that suggest internal / non-product traffic. We don't block
# these outright — internal admin routes can still be worth surfacing — but
# we cap how many we consider so they don't crowd out user-facing routes.
_LOWER_PRIORITY_PREFIXES: tuple[str, ...] = ("/api/", "/_next/", "/static/", "/assets/")


_MAX_PATHS_FROM_DIFF = 40
_MAX_LLM_PATHS = 10


def _iter_added_segments(diff_text: str) -> list[tuple[str, str]]:
    """Mirror of diff_scanner._iter_added_segments — context + added lines only.

    Kept inline rather than imported to avoid cross-module coupling for a
    one-off use; the iterator is intentionally tiny and stable.
    """
    out: list[tuple[str, str]] = []
    current_path = ""
    in_hunk = False
    for raw in diff_text.splitlines():
        if raw.startswith("+++ "):
            path = raw[4:].strip()
            if path.startswith("b/"):
                path = path[2:]
            current_path = path
            in_hunk = False
            continue
        if raw.startswith("--- "):
            in_hunk = False
            continue
        if raw.startswith("@@"):
            in_hunk = True
            continue
        if not in_hunk:
            continue
        if raw.startswith("+") and not raw.startswith("+++"):
            out.append((current_path, raw[1:]))
        elif raw.startswith(" "):
            out.append((current_path, raw[1:]))
    return out


def extract_url_paths_from_diff(diff_text: str) -> list[str]:
    """Pull plausible URL paths from string literals in the diff.

    Returns a deduplicated list, capped to keep the downstream HogQL query
    bounded. User-facing paths are prioritized over internal-looking ones
    (``/api/...``, ``/_next/...``) when trimming to the cap.
    """
    seen: set[str] = set()
    for _path, line in _iter_added_segments(diff_text):
        for match in _PATH_LITERAL_PATTERN.finditer(line):
            candidate = match.group(1)
            # Strip trailing punctuation that snuck into the captured path
            # (the regex's bounded char class catches most of this, but a
            # trailing ``.`` from sentence-style URLs in comments slips through).
            candidate = candidate.rstrip(".,;:")
            if candidate in _PATH_BLOCKLIST or len(candidate) < 2:
                continue
            seen.add(candidate)

    if not seen:
        return []

    # Sort user-facing routes first, internal-looking ones after.
    def sort_key(p: str) -> tuple[int, str]:
        is_lower_priority = any(p.startswith(prefix) for prefix in _LOWER_PRIORITY_PREFIXES)
        return (1 if is_lower_priority else 0, p)

    ordered = sorted(seen, key=sort_key)
    return ordered[:_MAX_PATHS_FROM_DIFF]


def compute_pageview_reach(
    team: "Team",
    paths: list[str],
    lookback_days: int,
    matched_from: str = "diff_literal",
) -> list["WebPathReach"]:
    """Measure pageview counts for a fixed set of URL paths.

    Returns one ``WebPathReach`` per requested path, in the order supplied.
    Paths with no recorded pageviews come back with zeroed counts and
    ``has_data=False`` so the UI can say "no pageviews in window" rather
    than misleadingly showing zero.
    """
    from ..facade.contracts import WebPathReach

    deduped = list(dict.fromkeys(p for p in paths if p))
    if not deduped:
        return []

    response = execute_hogql_query(
        query="""
            SELECT
                toString(properties.$pathname) AS pathname,
                count() AS pageviews,
                uniq(person_id) AS visitors,
                uniq($session_id) AS sessions
            FROM events
            WHERE event = '$pageview'
              AND timestamp > now() - toIntervalDay({lookback_days})
              AND toString(properties.$pathname) IN {paths}
            GROUP BY pathname
        """,
        team=team,
        placeholders={
            "lookback_days": ast.Constant(value=lookback_days),
            "paths": ast.Array(exprs=[ast.Constant(value=p) for p in deduped]),
        },
    )

    by_path: dict[str, tuple[int, int, int]] = {}
    for row in response.results or []:
        pathname, pageviews, visitors, sessions = row
        by_path[pathname] = (int(pageviews or 0), int(visitors or 0), int(sessions or 0))

    out: list[WebPathReach] = []
    for path in deduped:
        pageviews, visitors, sessions = by_path.get(path, (0, 0, 0))
        out.append(
            WebPathReach(
                path=path,
                pageviews=pageviews,
                unique_visitors=visitors,
                sessions=sessions,
                has_data=path in by_path,
                matched_from=matched_from,
            )
        )
    return out


def cap_llm_paths(paths: list[str]) -> list[str]:
    """Public cap used by the LLM tool — keeps a single tool call bounded."""
    return list(dict.fromkeys(p for p in paths if p))[:_MAX_LLM_PATHS]
