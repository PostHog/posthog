import math
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from django.utils import timezone

from posthog.schema import ProductKey

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.query_tagging import Feature, tag_queries
from posthog.clickhouse.workload import Workload
from posthog.dataclasses import frozen

from .fires_on_leave import LastDay
from .impact_lens import (
    MAX_ISSUES,
    WINDOW_HOURS,
    ImpactLens,
    issue_state_join,
    issue_summaries,
    per_team_results,
    property_expr,
    with_issue_details,
)

MIN_EVENTS = 20
MIN_THIRD_PARTY_SHARE = 0.5
# An issue whose stack reaches the app's own code in fewer than half of its events cannot be acted on in that code.
MIN_OWN_CODE_SHARE = 0.5
# A plain Error with a sentence for a message, such as "Not found.", is the app reporting a failure it expected.
MIN_APP_REPORTED_SHARE = 0.5
# Issues without events in the last day are judged on up to this many days before it.
NOISE_LOOKBACK_DAYS = 7

# Patterns that are usually noise or outside the app's control. A default, not a verdict: a hydration
# error can still hurt people, so the impact tab lowers these issues rather than hiding them.
KNOWN_PATTERNS = frozenset(
    {
        "resize_observer",
        "script_error",
        "extension",
        "chunk_load",
        "hydration",
        "abort",
        "network",
        "non_error_rejection",
        "environment",
    }
)

# Patterns that are noise for every lens that ranks issues. A failed request is an HTTP status, not a bug in the page,
# so it joins the known patterns here. The incident lenses keep these, since a broken deploy shows up as failed loads.
NOISE_PATTERNS = KNOWN_PATTERNS | {"http_status"}

# Patterns that never point at the app's own code, so they cannot explain a broken flow.
HARMLESS_PATTERNS = frozenset({"resize_observer", "script_error", "extension", "non_error_rejection", "environment"})

# Raw string, so that the regex escapes reach ClickHouse as written, for example `\\.` for a literal dot.
# The order matters: specific environment shapes first, then the shapes of a code bug, which win over the noise
# classes, so "reading 'clearTimeout'" is a code bug rather than a network failure. Noise words match whole words.
PATTERN = r"""multiIf(
    has_extension_frame, 'extension',
    match(type_and_value, '(?i)\\bethereum\\b|MetaMask'), 'extension',
    match(type_and_value, 'Java object is gone|Object Not Found Matching Id'), 'environment',
    match(type_and_value, 'ResizeObserver loop'), 'resize_observer',
    match(type_and_value, '"Script error\\.?"'), 'script_error',
    match(type_and_value, '(?i)Cannot read propert|undefined is not|null is not|is not a function|is not defined|Cannot access|is not iterable'), 'code_bug',
    match(type_and_value, '(?i)Loading chunk|ChunkLoadError|dynamically imported module|Importing a module script failed|Loading CSS chunk|Unable to preload CSS|is not a valid JavaScript MIME type'), 'chunk_load',
    match(type_and_value, 'Minified React error #(418|419|421|422|423|425)|(?i)\\bhydration\\b|\\bhydrating\\b|server-rendered HTML'), 'hydration',
    match(type_and_value, '(?i)\\bAbortError\\b|\\baborted\\b|\\bcancell?ed\\b'), 'abort',
    match(type_and_value, '(?i)Failed to fetch|\\bNetworkError\\b|Network request failed|\\bLoad failed\\b|\\bnetwork error\\b|ERR_NETWORK|ERR_INTERNET|\\bTimeoutError\\b|\\btimeout\\b|\\btimed out\\b|ECONNABORTED|\\boffline\\b|Error in input stream|network connection was lost|Unable to reach the server|check your (internet )?connection'), 'network',
    match(type_and_value, '(?i)Non-Error (promise rejection|exception) captured|Object captured as|UnhandledRejection|\\bCustomEvent\\b'), 'non_error_rejection',
    match(type_and_value, '(?i)status(:| code| of)? ?(4|5)[0-9][0-9]|\\b(401|403|404|429|500|502|503|504)\\b|\\bUnauthorized\\b|\\bForbidden\\b'), 'http_status',
    'other'
)"""

EXTENSION_SOURCE = r"^(chrome|moz|safari|safari-web|ms-browser)-extension:|^webkit-masked-url:|^user-script:"

# Text that only code contains: brackets, operators, dotted or snake_case names, backticks and hashes. Quoted values,
# such as a name inside a sentence, are removed first, since they are data rather than code.
CODE_TEXT = r"[()\\[\\]{}<>=`#]|\\w\\.\\w|\\w_\\w"
QUOTED_TEXT = r"\'[^\']*\'|\"[^\"]*\""

# Whether an error is a plain Error whose message is a sentence without code, from its first type and value.
SENTENCE_MESSAGE = """{first_type} = 'Error'
        AND position({first_value}, ' ') > 0
        AND NOT match(replaceRegexpAll({first_value}, '{quoted_text}', ''), '{code_text}')"""

# Per exception: its pattern and the facts about its stack, read from the exception list.
EXCEPTION_COLUMNS = """
    events.team_id AS team_id,
    issue_state.issue_id AS issue_id,
    events.`$session_id` AS session_id,
    concat({types}, ' ', {values}) AS type_and_value,
    JSONExtractArrayRaw(JSONExtractRaw(events.properties, '$exception_list')) AS exception_list,
    arrayFlatten(arrayMap(
        exception -> JSONExtractArrayRaw(JSONExtractRaw(JSONExtractRaw(exception, 'stacktrace'), 'frames')),
        exception_list
    )) AS frames,
    length(frames) AS frame_count,
    arrayCount(frame -> JSONExtractBool(frame, 'resolved'), frames) AS resolved_frame_count,
    arrayMap(
        frame -> if(
            JSONExtractString(JSONExtractRaw(JSONExtractRaw(frame, 'junk_drawer'), 'raw_frame'), 'filename') != '',
            JSONExtractString(JSONExtractRaw(JSONExtractRaw(frame, 'junk_drawer'), 'raw_frame'), 'filename'),
            JSONExtractString(frame, 'source')
        ),
        frames
    ) AS frame_sources,
    arrayExists(source -> match(source, '{extension_source}'), frame_sources) AS has_extension_frame,
    arrayFilter(
        frame -> startsWith(tupleElement(frame, 1), 'http'),
        arrayZip(frame_sources, arrayMap(frame -> JSONExtractBool(frame, 'resolved'), frames))
    ) AS http_frames,
    length(http_frames) AS http_frame_count,
    if({host} != '', cutToFirstSignificantSubdomain(concat('https://', {host})), '') AS host_domain,
    -- The last frame is the innermost one, where the error was thrown. A frame resolved through the project's
    -- source maps is the project's own code, even when a CDN on another domain serves it.
    http_frame_count > 0
        AND NOT tupleElement(http_frames[-1], 2)
        AND cutToFirstSignificantSubdomain(tupleElement(http_frames[-1], 1)) != host_domain AS top_frame_third_party,
    -- Frames from dependencies, ignored sources and anonymous scripts are not in the app, so an event without a stack
    -- or with only such frames never reaches the app's own code.
    arrayExists(frame -> JSONExtractBool(frame, 'in_app'), frames) AS own_code,
    arrayExists(exception -> JSONExtractBool(JSONExtractRaw(exception, 'mechanism'), 'handled'), exception_list) AS handled,
    {sentence_message} AS sentence_message,
    {pattern} AS pattern
"""

ISSUE_QUERY = """
    SELECT
        team_id,
        issue_id,
        count() AS occurrences,
        uniqExactIf(session_id, session_id != '') AS sessions,
        topK(1)(pattern)[1] AS top_pattern,
        avg(frame_count = 0) AS no_stack_share,
        avgIf(top_frame_third_party, http_frame_count > 0 AND host_domain != '') AS third_party_share,
        avgIf(resolved_frame_count / frame_count, frame_count > 0) AS resolved_share,
        avg(own_code) AS own_code_share,
        avg(handled) AS handled_share,
        avg(sentence_message) AS sentence_share
    FROM (
        SELECT {columns}
        FROM events
        {issue_state_join}
        WHERE events.team_id IN %(team_ids)s
            AND events.event = '$exception'
            AND events.timestamp >= toDateTime64(%(since)s, 6, 'UTC')
            AND events.timestamp < toDateTime64(%(until)s, 6, 'UTC')
            AND {lib} = 'web'
            AND issue_state.issue_status = 'active'
            {issue_filter}
    )
    GROUP BY team_id, issue_id
"""

# The most common pattern of a few given issues, over a given time range.
ISSUE_PATTERN_QUERY = """
    SELECT toString(issue_id), topK(1)(pattern)[1]
    FROM (
        SELECT {columns}
        FROM events
        {issue_state_join}
        WHERE events.team_id IN %(team_ids)s
            AND events.event = '$exception'
            AND events.timestamp >= toDateTime64(%(since)s, 6, 'UTC')
            AND events.timestamp < toDateTime64(%(until)s, 6, 'UTC')
            AND {lib} = 'web'
            AND toString(issue_state.issue_id) IN %(issue_ids)s
    )
    GROUP BY issue_id
"""


def _sentence_message(first_type: str, first_value: str) -> str:
    return SENTENCE_MESSAGE.format(
        first_type=first_type, first_value=first_value, quoted_text=QUOTED_TEXT, code_text=CODE_TEXT
    )


def _format(template: str, issue_filter: str = "") -> str:
    types = property_expr("$exception_types")
    values = property_expr("$exception_values")
    columns = EXCEPTION_COLUMNS.format(
        types=types,
        values=values,
        host=property_expr("$host"),
        extension_source=EXTENSION_SOURCE,
        sentence_message=_sentence_message(f"JSONExtractString({types}, 1)", f"JSONExtractString({values}, 1)"),
        pattern=PATTERN,
    )
    return template.format(
        columns=columns, issue_state_join=issue_state_join(), lib=property_expr("$lib"), issue_filter=issue_filter
    )


def _clickhouse_time(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S")


def issue_patterns(team_ids: list[int], issue_ids: list[str], since: datetime, until: datetime) -> dict[str, str]:
    """The most common pattern of each given issue between ``since`` and ``until``."""
    if not issue_ids:
        return {}
    rows = sync_execute(
        _format(ISSUE_PATTERN_QUERY),
        {
            "team_ids": team_ids,
            "issue_ids": issue_ids,
            "since": _clickhouse_time(since),
            "until": _clickhouse_time(until),
        },
        workload=Workload.OFFLINE,
    )
    return dict(rows)


@frozen
class IssuePatternRow:
    """One active issue's web exceptions in the window. A share is NaN when no exception has the frames it needs."""

    team_id: int
    issue_id: str
    events: int
    sessions: int
    pattern: str
    no_stack_share: float
    third_party_share: float
    resolved_share: float
    own_code_share: float
    handled_share: float
    sentence_share: float

    @property
    def noise_reasons(self) -> list[str]:
        """Why the issue is likely noise that nobody can act on, or an empty list when it is not."""
        return [
            reason
            for reason, applies in (
                ("known_pattern", self.pattern in NOISE_PATTERNS),
                ("third_party", _share(self.third_party_share) >= MIN_THIRD_PARTY_SHARE),
                ("no_own_code", self.own_code_share < MIN_OWN_CODE_SHARE),
                # Browsers word some of their own errors as sentences too, so only an unmatched message counts here.
                ("app_reported", self.pattern == "other" and self.sentence_share >= MIN_APP_REPORTED_SHARE),
            )
            if applies
        ]


def _query_pattern_rows(
    team_ids: list[int], since: datetime, until: datetime, issue_ids: list[str] | None = None
) -> list[IssuePatternRow]:
    return [
        IssuePatternRow(
            team_id=team_id,
            issue_id=str(issue_id),
            events=events,
            sessions=sessions,
            pattern=pattern,
            no_stack_share=no_stack_share,
            third_party_share=third_party_share,
            resolved_share=resolved_share,
            own_code_share=own_code_share,
            handled_share=handled_share,
            sentence_share=sentence_share,
        )
        for (
            team_id,
            issue_id,
            events,
            sessions,
            pattern,
            no_stack_share,
            third_party_share,
            resolved_share,
            own_code_share,
            handled_share,
            sentence_share,
        ) in sync_execute(
            _format(ISSUE_QUERY, "AND toString(issue_state.issue_id) IN %(issue_ids)s" if issue_ids else ""),
            {
                "team_ids": team_ids,
                "since": _clickhouse_time(since),
                "until": _clickhouse_time(until),
                "issue_ids": issue_ids or [],
            },
            workload=Workload.OFFLINE,
        )
    ]


def issue_pattern_rows(team_ids: list[int], day: LastDay) -> list[IssuePatternRow]:
    """Every active issue's web exceptions on the day. Within one sweep batch, each team's rows are read once and
    shared by every lens that leaves noise out."""

    def fetch(missing: list[int]) -> dict[int, list[IssuePatternRow]]:
        by_team: dict[int, list[IssuePatternRow]] = defaultdict(list)
        for row in _query_pattern_rows(missing, day.start, day.end):
            by_team[row.team_id].append(row)
        return by_team

    by_team = per_team_results(("issue_patterns", day.start), team_ids, fetch, list)
    return [row for team_id in team_ids for row in by_team[team_id]]


# The pattern and sentence verdict of issues without recent events, from their stored type and message.
STORED_TEXT_QUERY = """
    SELECT key, {pattern}, {sentence_message}
    FROM (
        SELECT
            tupleElement(item, 1) AS key,
            tupleElement(item, 2) AS first_type,
            tupleElement(item, 3) AS first_value,
            concat('["', first_type, '"] ["', first_value, '"]') AS type_and_value,
            0 AS has_extension_frame
        FROM (SELECT arrayJoin(%(items)s) AS item)
    )
"""


def _stored_text_noise(issues: list[tuple[int, str]]) -> set[tuple[int, str]]:
    """The issues whose stored type and message, from their first event, match a noise pattern or a plain sentence."""
    summaries = issue_summaries(
        sorted({team_id for team_id, _ in issues}), sorted({issue_id for _, issue_id in issues})
    )
    items = [
        (f"{team_id}:{issue_id}", summary["name"] or "", summary["description"] or "")
        for team_id, issue_id in issues
        if (summary := summaries.get((team_id, issue_id))) is not None
    ]
    if not items:
        return set()
    noise = set()
    for key, pattern, sentence in sync_execute(
        STORED_TEXT_QUERY.format(pattern=PATTERN, sentence_message=_sentence_message("first_type", "first_value")),
        {"items": items},
        workload=Workload.OFFLINE,
    ):
        if pattern in NOISE_PATTERNS or (pattern == "other" and sentence):
            team_id, issue_id = key.split(":", 1)
            noise.add((int(team_id), issue_id))
    return noise


def noise_issue_ids(
    team_ids: list[int], candidates: dict[int, set[str]] | None = None, since: datetime | None = None
) -> dict[int, set[str]]:
    """Per team, the issues that are likely noise, judged on their web exceptions of the last day.

    A lens that looks further back passes the issues it ranks and the start of its window, so that issues without
    events in the last day are judged on the days before it, up to NOISE_LOOKBACK_DAYS, and issues without web events
    even then on their stored type and message. Backend errors only count as noise by their stored type and message.
    """
    day = LastDay.before(timezone.now())
    noise: dict[int, set[str]] = {team_id: set() for team_id in team_ids}
    judged: set[tuple[int, str]] = set()
    for row in issue_pattern_rows(team_ids, day):
        judged.add((row.team_id, row.issue_id))
        if row.noise_reasons:
            noise[row.team_id].add(row.issue_id)
    if candidates is None or since is None or since >= day.start:
        return noise
    unjudged = sorted(
        {
            issue_id
            for team_id, issue_ids in candidates.items()
            for issue_id in issue_ids
            if (team_id, issue_id) not in judged
        }
    )
    if not unjudged:
        return noise
    earlier = max(since, day.start - timedelta(days=NOISE_LOOKBACK_DAYS))
    for row in _query_pattern_rows(sorted(candidates), earlier, day.start, unjudged):
        judged.add((row.team_id, row.issue_id))
        if row.noise_reasons:
            noise[row.team_id].add(row.issue_id)
    remaining = [
        (team_id, issue_id)
        for team_id, issue_ids in candidates.items()
        for issue_id in issue_ids
        if (team_id, issue_id) not in judged
    ]
    for team_id, issue_id in _stored_text_noise(remaining):
        noise[team_id].add(issue_id)
    return noise


def _share(value: float) -> float:
    return 0.0 if math.isnan(value) else round(value, 4)


def find_known_patterns(rows: list[IssuePatternRow]) -> dict[int, dict[str, Any]]:
    """Summarize each team's error volume by pattern and pick the issues with a known pattern or a third-party top frame."""
    totals: dict[int, int] = defaultdict(int)
    class_events: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    flagged: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        totals[row.team_id] += row.events
        class_events[row.team_id][row.pattern] += row.events
        reasons = row.noise_reasons
        if row.events < MIN_EVENTS or not reasons:
            continue
        flagged[row.team_id].append(
            {
                "id": row.issue_id,
                "events": row.events,
                "sessions": row.sessions,
                "pattern": row.pattern,
                "reasons": reasons,
                "no_stack_share": round(row.no_stack_share, 4),
                "third_party_share": _share(row.third_party_share),
                "resolved_share": None if math.isnan(row.resolved_share) else round(row.resolved_share, 4),
                "own_code_share": round(row.own_code_share, 4),
                "handled_share": round(row.handled_share, 4),
            }
        )

    result: dict[int, dict[str, Any]] = {}
    for team_id, total in totals.items():
        classes = sorted(class_events[team_id].items(), key=lambda item: (-item[1], item[0]))
        result[team_id] = {
            "total_events": total,
            "pattern_events": sum(events for pattern, events in classes if pattern in NOISE_PATTERNS),
            "classes": [{"pattern": pattern, "events": events} for pattern, events in classes],
            "issues": sorted(flagged[team_id], key=lambda issue: -issue["events"])[:MAX_ISSUES],
        }
    return result


class KnownPatternsRecommendation(ImpactLens):
    type = "known_patterns"
    refresh_interval = timedelta(hours=6)

    def compute_batch(self, team_ids: list[int]) -> dict[int, dict[str, Any]]:
        tag_queries(
            product=ProductKey.ERROR_TRACKING,
            feature=Feature.ENRICHMENT,
            name="recommendations:known_patterns",
        )
        rows = issue_pattern_rows(team_ids, LastDay.before(timezone.now()))
        summaries = find_known_patterns(rows)
        issues = with_issue_details(team_ids, {team_id: summary["issues"] for team_id, summary in summaries.items()})
        metas: dict[int, dict[str, Any]] = {}
        for team_id in team_ids:
            summary = summaries.get(team_id, {"total_events": 0, "pattern_events": 0, "classes": []})
            metas[team_id] = {
                "window_hours": WINDOW_HOURS,
                # A project with no web exceptions in the window has nothing this lens can label.
                "evaluable": team_id in summaries,
                "total_events": summary["total_events"],
                "pattern_events": summary["pattern_events"],
                "classes": summary["classes"],
                "issues": issues[team_id],
            }
        return metas
