"""Holds the mined-patterns payload inside a size an agent can read in one piece.

One template can be a whole stack trace or a serialized query, and the miner returns up to
`LOGS_PATTERNS_MAX_PATTERNS` of them, each with its own match predicates. An unbounded response
therefore costs more context than an agent has, and a truncated tool result is worse than a small
one: the agent cannot tell what it lost. Requests that arrive over MCP get bounded defaults for
that reason, and every caller can set the bounds itself.

Each bound keeps the drill-down path usable. A cut template says it was cut. A kept subset of
`match_patterns` still filters exactly the lines of those members. A cut `match_literal` is still a
literal substring of every line of the pattern, so `icontains` still matches them, only more
broadly. A regex cannot survive a cut, so a regex over the budget is dropped and reported instead.
"""

from typing import Any

from rest_framework import exceptions

from products.logs.backend.log_patterns import _env

# Defaults for a request that arrived over MCP. Small enough that a full response fits a tool
# result next to the rest of an investigation, large enough to read a template and pivot on it.
MCP_PATTERN_LIMIT = 20
MCP_MAX_PATTERN_CHARS = 400

# A budget below this cannot hold the cut marker plus usable template text, and a caller that
# cannot see the marker reads a cut template as the whole one.
MIN_PATTERN_CHARS = 80

PATTERN_CUT_NOTE = "[cut at {max_chars} chars, re-run with maxPatternChars=0 for the whole template]"


def max_pattern_limit() -> int:
    """The most pattern groups the miner itself will return, which no `limit` can exceed."""
    return max(1, _env("LOGS_PATTERNS_MAX_PATTERNS", 200, int))


def parse_limit(raw: Any, *, over_mcp: bool) -> int:
    """Resolve the `limit` param: how many pattern groups the response carries."""
    if raw is None:
        return MCP_PATTERN_LIMIT if over_mcp else max_pattern_limit()
    limit = _parse_int(raw, "limit")
    if limit < 1:
        raise exceptions.ValidationError("limit must be 1 or greater.")
    return min(limit, max_pattern_limit())


def parse_max_pattern_chars(raw: Any, *, over_mcp: bool) -> int:
    """Resolve the `maxPatternChars` param. Zero means whole templates and predicates."""
    if raw is None:
        return MCP_MAX_PATTERN_CHARS if over_mcp else 0
    max_chars = _parse_int(raw, "maxPatternChars")
    if max_chars < 0:
        raise exceptions.ValidationError("maxPatternChars must be zero or greater.")
    if 0 < max_chars < MIN_PATTERN_CHARS:
        raise exceptions.ValidationError(
            f"maxPatternChars must be {MIN_PATTERN_CHARS} or greater, or zero for whole templates."
        )
    return max_chars


def bound_patterns_response(results: dict[str, Any], *, limit: int, max_pattern_chars: int) -> dict[str, Any]:
    """Cap the pattern groups and the text of each one, reporting what was left out.

    The groups are already ordered by count, so the cap keeps the highest-volume ones. The
    window-level counts (`total_count`, `represented_count`, `remainder_count`) are untouched:
    they describe the logs, not the payload.
    """
    patterns = results.get("patterns") or []
    kept = patterns[:limit]
    return {
        **results,
        "patterns": [_bound_pattern(pattern, max_pattern_chars) for pattern in kept],
        "returned_pattern_count": len(kept),
        "omitted_pattern_count": len(patterns) - len(kept),
    }


def _bound_pattern(pattern: dict[str, Any], max_chars: int) -> dict[str, Any]:
    template, pattern_truncated = _cut(pattern.get("pattern") or "", max_chars, marker=True)
    members, omitted = _bound_members(pattern.get("match_patterns") or [], max_chars)
    regex = pattern.get("match_regex")
    regex_omitted = bool(max_chars and regex and len(regex) > max_chars)
    literal = pattern.get("match_literal")
    literal, literal_truncated = _cut(literal, max_chars, marker=False) if literal else (literal, False)
    return {
        **pattern,
        "pattern": template,
        "pattern_truncated": pattern_truncated,
        "match_patterns": members,
        "match_patterns_omitted": omitted,
        "match_regex": None if regex_omitted else regex,
        "match_regex_omitted": regex_omitted,
        "match_literal": literal,
        "match_literal_truncated": literal_truncated,
    }


def _cut(text: str, max_chars: int, *, marker: bool) -> tuple[str, bool]:
    """Hold `text` inside `max_chars`, marker included when one is wanted."""
    if max_chars <= 0 or len(text) <= max_chars:
        return text, False
    if not marker:
        return text[:max_chars], True
    note = PATTERN_CUT_NOTE.format(max_chars=max_chars)
    return text[: max(0, max_chars - len(note) - 1)] + " " + note, True


def _bound_members(members: list[str], max_chars: int) -> tuple[list[str], int]:
    """Keep the exact members that fit the budget, never cutting one.

    A member is the canonical pattern an agent filters on, so a cut member matches nothing. The
    first member is always kept, even when it alone is over budget, so the exact pivot survives.
    """
    if max_chars <= 0 or not members:
        return members, 0
    kept = [members[0]]
    used = len(members[0])
    for member in members[1:]:
        if used + len(member) > max_chars:
            break
        kept.append(member)
        used += len(member)
    return kept, len(members) - len(kept)


def _parse_int(raw: Any, field: str) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int | str):
        raise exceptions.ValidationError(f"{field} must be an integer.")
    try:
        return int(str(raw).strip())
    except ValueError as exc:
        raise exceptions.ValidationError(f"{field} must be an integer.") from exc
