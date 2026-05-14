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
from collections.abc import Iterable

# Each pattern captures group 1 = flag key (a string literal) OR
# group 1 of a *const* pattern (an identifier) routed to its own branch.
_STRING_LITERAL_PATTERNS: tuple[re.Pattern[str], ...] = (
    # Python: covers `posthoganalytics.feature_enabled`, `posthog.feature_enabled`,
    # bare `feature_enabled`, etc. The leading `\b` matches the word boundary
    # after the module dot, so we don't need separate prefixed patterns.
    re.compile(r"""\bfeature_enabled\(\s*["']([^"']+)["']"""),
    re.compile(r"""\bget_feature_flag\(\s*["']([^"']+)["']"""),
    # JS/TS client SDK — match any receiver so wrapped clients
    # (`this.posthog.client.isFeatureEnabled`, `client.isFeatureEnabled`,
    # dependency-injected services, etc.) still register. Both method names
    # are distinctive enough that a leading word boundary is a safe filter.
    re.compile(r"""\bisFeatureEnabled\(\s*["']([^"']+)["']"""),
    re.compile(r"""\bgetFeatureFlag\(\s*["']([^"']+)["']"""),
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


# Each pattern captures group 1 = an event name (a string literal).
# Covers the common SDK call sites; intentionally conservative — we'd rather
# miss an exotic emitter than hallucinate event names.
_EVENT_NAME_PATTERNS: tuple[re.Pattern[str], ...] = (
    # JS/TS: posthog.capture('event_name', ...) — event is the 1st positional arg.
    # Leading word boundary lets us match bare `capture(...)` too (destructured client).
    re.compile(r"""\bposthog\.capture\(\s*["']([^"']+)["']"""),
    re.compile(r"""\busePostHog\(\)\.capture\(\s*["']([^"']+)["']"""),
    # Python keyword form: posthoganalytics.capture(distinct_id, event='event_name', ...)
    # or `capture(... event="event_name" ...)`. Cap the lookahead to a single call's
    # paren contents so we don't bleed across statements on the same diff line.
    re.compile(r"""\bposthoganalytics\.capture\([^)]*?\bevent\s*=\s*["']([^"']+)["']"""),
    re.compile(r"""\bph_client\.capture\([^)]*?\bevent\s*=\s*["']([^"']+)["']"""),
    re.compile(r"""\bph_scoped_capture\([^)]*?\bevent\s*=\s*["']([^"']+)["']"""),
    # Python positional form: posthoganalytics.capture(distinct_id, 'event_name', ...).
    # 1st arg is distinct_id (string OR identifier), 2nd is event name. We require
    # the 2nd arg to be a string literal; identifier-valued event names are skipped.
    re.compile(r"""\bposthoganalytics\.capture\(\s*[^,()]+,\s*["']([^"']+)["']"""),
)


_HUNK_HEADER = re.compile(r"^@@\s")

# Matches any single- or double-quoted string literal. Used to find the
# *contents* of literals and compare them against a known-key list — handles
# const-indirected and wrapped-SDK cases the call-shape patterns miss.
_STRING_LITERAL = re.compile(r"""["']([^"'\s]+)["']""")

# Below this length, key/name matches are too noisy to be useful (think single
# letters, common words). PostHog flag keys and event names should comfortably
# exceed this in practice.
_MIN_KNOWN_KEY_LEN = 3


def _iter_added_segments(diff_text: str) -> list[tuple[str, str]]:
    """Yield (file_path, line) tuples for content visible in the diff and still in HEAD.

    Both `+` (added) and ` ` (unchanged context) lines are emitted — context lines
    represent code that already exists at HEAD adjacent to the change, and a PR that
    modifies code *near* a `posthog.capture(...)` is materially affected by it even
    though the capture itself isn't in the added set. Removed (`-`) and header lines
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
        elif raw.startswith(" "):
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


def extract_changed_files(diff_text: str) -> list[str]:
    """Return the unique file paths that have added lines in this diff.

    Useful for cross-referencing the diff against external systems
    (error tracking issues, dashboards, etc.) where the connection is
    "code in this file" rather than "specific string in the diff."
    """
    seen: set[str] = set()
    for path, _line in _iter_added_segments(diff_text):
        if path:
            seen.add(path)
    return sorted(seen)


def extract_known_flag_mentions(diff_text: str, known_keys: Iterable[str]) -> list:
    """Find flag keys from ``known_keys`` appearing as string literals in added lines.

    Complements ``extract_flag_keys``: catches flag references that the SDK
    call-shape regex can't see — wrapped clients, const-indirected keys,
    config-driven lookups, anywhere the key string appears verbatim.

    Returns list[FlagReference]. Keys shorter than 3 characters are skipped
    to avoid trivial substring noise.
    """
    from ..facade.contracts import FlagReference

    known = {k for k in known_keys if k and len(k) >= _MIN_KNOWN_KEY_LEN}
    if not known:
        return []

    occurrences: dict[str, int] = defaultdict(int)
    files_by_key: dict[str, set[str]] = defaultdict(set)

    for path, line in _iter_added_segments(diff_text):
        for match in _STRING_LITERAL.finditer(line):
            value = match.group(1)
            if value in known:
                occurrences[value] += 1
                files_by_key[value].add(path)

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


def extract_known_event_mentions(diff_text: str, known_names: Iterable[str]) -> list:
    """Find event names from ``known_names`` appearing as string literals in added lines.

    Mirrors ``extract_known_flag_mentions`` for events. Skips internal
    $-prefixed events (PRs don't add `$pageview`).
    """
    from ..facade.contracts import EventReference

    known = {n for n in known_names if n and len(n) >= _MIN_KNOWN_KEY_LEN and not n.startswith("$")}
    if not known:
        return []

    occurrences: dict[str, int] = defaultdict(int)
    files_by_name: dict[str, set[str]] = defaultdict(set)

    for path, line in _iter_added_segments(diff_text):
        for match in _STRING_LITERAL.finditer(line):
            value = match.group(1)
            if value in known:
                occurrences[value] += 1
                files_by_name[value].add(path)

    references = [
        EventReference(
            name=name,
            file_paths=tuple(sorted(files_by_name[name])),
            occurrences=count,
        )
        for name, count in occurrences.items()
    ]
    references.sort(key=lambda r: (-r.occurrences, r.name))
    return references


def extract_event_names(diff_text: str) -> list:
    """Return a list[EventReference] of event names found in added diff lines.

    Sorted by descending occurrence count, then name for stability.
    """
    from ..facade.contracts import EventReference

    occurrences: dict[str, int] = defaultdict(int)
    files_by_name: dict[str, set[str]] = defaultdict(set)

    for path, line in _iter_added_segments(diff_text):
        for pattern in _EVENT_NAME_PATTERNS:
            for match in pattern.finditer(line):
                name = match.group(1)
                # PostHog-internal events use a leading `$`. They are valid
                # event names, but a PR rarely "emits" them — skip to reduce noise.
                if name.startswith("$"):
                    continue
                occurrences[name] += 1
                files_by_name[name].add(path)

    references = [
        EventReference(
            name=name,
            file_paths=tuple(sorted(files_by_name[name])),
            occurrences=count,
        )
        for name, count in occurrences.items()
    ]
    references.sort(key=lambda r: (-r.occurrences, r.name))
    return references
