"""Extract PostHog feature-flag keys from a unified diff.

We deliberately keep this pure (no IO, no Django) so it is trivially
testable and reusable. The scanner only looks at *added* lines (the
"after" side of the diff) — flags removed by a PR are not part of the
forward-looking impact.

Accuracy caveats (surfaced to callers, not silently swallowed):
- We do not resolve flag-key constants (e.g. `FEATURE_FLAGS.MY_FLAG`)
  back to their string values. Such references are returned with a
  synthetic key of `const:<identifier>` so the caller can choose to
  ignore them or warn.
- We do not climb out of the diff to find enclosing flag gates. Those
  are real for accuracy but require AST/call-graph work — out of scope
  for the first cut.
"""

import re
from collections import defaultdict

# Each pattern captures group 1 = flag key (a string literal) OR
# group 1 of a *const* pattern (an identifier) routed to its own branch.
_STRING_LITERAL_PATTERNS: tuple[re.Pattern[str], ...] = (
    # Python: covers `posthoganalytics.feature_enabled`, `posthog.feature_enabled`,
    # bare `feature_enabled`, etc. The leading `\b` matches the word boundary
    # after the module dot, so we don't need separate prefixed patterns.
    re.compile(r"""\bfeature_enabled\(\s*["']([^"']+)["']"""),
    re.compile(r"""\bget_feature_flag\(\s*["']([^"']+)["']"""),
    # JS/TS client SDK
    re.compile(r"""posthog\.isFeatureEnabled\(\s*["']([^"']+)["']"""),
    re.compile(r"""posthog\.getFeatureFlag\(\s*["']([^"']+)["']"""),
    # PostHog React hooks / kea selectors
    re.compile(r"""useFeatureFlag\(\s*["']([^"']+)["']"""),
    re.compile(r"""useFeatureFlagEnabled\(\s*["']([^"']+)["']"""),
    re.compile(r"""useFeatureFlagPayload\(\s*["']([^"']+)["']"""),
    # JSX tag form: <FlaggedFeature flag="key"> / <Feature name="key">
    re.compile(r"""<FlaggedFeature\b[^>]*\bflag\s*=\s*["']([^"']+)["']"""),
    re.compile(r"""<PostHogFeature\b[^>]*\bflag\s*=\s*["']([^"']+)["']"""),
)

# Captures group 1 = the constant identifier (e.g. "MY_NEW_FLAG").
# Caller decides whether to use these — they're surfaced as `const:<id>`.
_CONST_REFERENCE_PATTERN = re.compile(r"""\bFEATURE_FLAGS\.([A-Z][A-Z0-9_]*)""")


_HUNK_HEADER = re.compile(r"^@@\s")


def _iter_added_segments(diff_text: str) -> list[tuple[str, str]]:
    """Yield (file_path, added_line) tuples from a unified diff.

    Only `+` lines inside a hunk are emitted. File-header `+++` lines
    set the current path. Untouched context lines and removed lines
    are skipped.
    """
    current_path = ""
    in_hunk = False
    out: list[tuple[str, str]] = []
    for raw in diff_text.splitlines():
        if raw.startswith("+++ "):
            # Strip leading "b/" if present (standard git diff prefix)
            path = raw[4:].strip()
            if path.startswith("b/"):
                path = path[2:]
            current_path = path
            in_hunk = False
            continue
        if raw.startswith("--- "):
            in_hunk = False
            continue
        if _HUNK_HEADER.match(raw):
            in_hunk = True
            continue
        if not in_hunk:
            continue
        if raw.startswith("+") and not raw.startswith("+++"):
            out.append((current_path, raw[1:]))
    return out


def extract_flag_keys(diff_text: str) -> list:
    """Return a list[FlagReference] of flag keys found in added diff lines.

    Sorted by descending occurrence count, then key for stability.
    """
    # Import here to avoid a hard dependency from logic -> facade in tools
    # that consume only the regex helpers; keeps this module dependency-light.
    from ..facade.contracts import FlagReference

    occurrences: dict[str, int] = defaultdict(int)
    files_by_key: dict[str, set[str]] = defaultdict(set)

    for path, line in _iter_added_segments(diff_text):
        for pattern in _STRING_LITERAL_PATTERNS:
            for match in pattern.finditer(line):
                key = match.group(1)
                occurrences[key] += 1
                files_by_key[key].add(path)
        for match in _CONST_REFERENCE_PATTERN.finditer(line):
            key = f"const:{match.group(1)}"
            occurrences[key] += 1
            files_by_key[key].add(path)

    references = [
        FlagReference(
            key=key,
            file_paths=tuple(sorted(files_by_key[key])),
            occurrences=count,
        )
        for key, count in occurrences.items()
    ]
    references.sort(key=lambda r: (-r.occurrences, r.key))
    return references
