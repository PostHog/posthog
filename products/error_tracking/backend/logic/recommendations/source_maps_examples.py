import re
import json
from datetime import datetime, timedelta
from time import monotonic
from typing import Any
from uuid import UUID

from django.contrib.postgres.aggregates import ArrayAgg
from django.contrib.postgres.fields import ArrayField
from django.db.models import Count, Func, Max, TextField, Value
from django.db.models.fields.json import KeyTextTransform
from django.db.models.functions import Cast, Concat
from django.utils import timezone

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import ClickHouseUser
from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception
from posthog.models import Team, User

from products.access_control.backend.facade.api import (
    get_restricted_properties_with_group_type_index_for_team,
    split_restricted_property_names,
)
from products.error_tracking.backend.facade.contracts import (
    MissingSymbolsExample,
    MissingSymbolsExampleException,
    MissingSymbolsExamples,
    MissingSymbolsIssue,
    MissingSymbolsReason,
    MissingSymbolsStackFrame,
    SymbolsPlatform,
)
from products.error_tracking.backend.logic import split_stack_frame_raw_id
from products.error_tracking.backend.models import ErrorTrackingIssueFingerprintV2, ErrorTrackingStackFrame

from .source_maps import LOOKBACK_HOURS, MISSING_SYMBOLS, MISSING_SYMBOLS_RULES, PLATFORM, frames_database

EXAMPLES_LIMIT = 10
# Ten examples of twenty frame IDs stay under ClickHouse's limit of 255 needles in one multi-search.
RAW_IDS_PER_EXAMPLE = 20
ISSUES_PER_EXAMPLE = 5
# Each example keeps at most this many fingerprints, so one busy file cannot push the others out.
FINGERPRINTS_PER_EXAMPLE = 100
FRAMES_PER_EXCEPTION = 30
EXCEPTIONS_QUERY_TIMEOUT_SECONDS = 15

_URL_PATTERN = re.compile(r"https?://[^\s)]+")
_HTTP_STATUS_PATTERN = re.compile(r"^HTTP error (\d{3}) ")
# The failure text of these reasons ends with the ID that the missing symbols must be uploaded under.
_REASONS_WITH_SYMBOL_ID = {
    MissingSymbolsReason.CHUNK_NOT_UPLOADED,
    MissingSymbolsReason.MAPPING_NOT_UPLOADED,
    MissingSymbolsReason.DSYM_NOT_UPLOADED,
    MissingSymbolsReason.DEBUG_SYMBOLS_NOT_UPLOADED,
}


# nosemgrep: python.django.security.audit.extends-custom-expression.extends-custom-expression
class _FirstRawIds(Func):
    # Postgres still aggregates every frame ID, but only the first ones leave the database. The template
    # holds only a module constant, and the only expression is an aggregate of columns, so no input reaches the SQL.
    template = f"(%(expressions)s)[1:{RAW_IDS_PER_EXAMPLE}]"
    output_field = ArrayField(TextField())


@frozen
class _ExampleKey:
    reason: MissingSymbolsReason
    location: str | None
    symbol_id: str | None
    http_status: int | None


@frozen(frozen=False)
class _ExampleGroup:
    key: _ExampleKey
    frames: int
    # In the `hash/part` form that events use for frame IDs.
    raw_ids: list[str]


@frozen
class _FingerprintMatch:
    example_index: int
    fingerprint: str
    occurrences: int
    event_uuid: UUID
    timestamp: datetime


@frozen
class _Scan:
    matches: list[_FingerprintMatch]
    # True when ClickHouse stopped the scan at its time limit and returned the events it read until then.
    stopped_early: bool


@frozen
class _ExampleIssues:
    top: list[MissingSymbolsIssue]
    count: int
    capped: bool


@frozen
class _ParsedException:
    fingerprint: str
    timestamp: datetime
    type: str | None
    value: str | None
    # Stored order: the entry point first and the crash site last.
    frames: list[dict[str, Any]]


def missing_symbols_examples(team_id: int, platform: SymbolsPlatform, user: User) -> MissingSymbolsExamples:
    """The files and builds with the most frames missing symbols on one platform, with the exceptions they appear in."""
    since = timezone.now() - timedelta(hours=LOOKBACK_HOURS)
    groups = _example_groups(team_id, platform, since)
    team = Team.objects.get(id=team_id)
    # Frames come from `$exception_list`. A user who cannot read it sees no paths or build IDs, and the
    # scans run as that user, so they would find no exceptions either.
    frames_hidden = _exception_list_restricted(team_id, user)

    try:
        scan = (
            _Scan(matches=[], stopped_early=False)
            if frames_hidden
            else _exceptions_containing(team, user, [group.raw_ids for group in groups], since)
        )
        representatives = _representatives(scan.matches)
        payloads = _exception_lists(team, user, list(representatives.values()))
        exceptions_loaded = True
    except Exception as error:
        # The examples stay useful without exceptions, so a failed scan only drops them.
        capture_exception(error)
        scan, representatives, payloads, exceptions_loaded = _Scan(matches=[], stopped_early=False), {}, {}, False
    matches = scan.matches

    issues = _issues_by_fingerprint(team_id, {match.fingerprint for match in matches})
    examples = [
        _parsed_example(group, representatives[index], payloads.get(representatives[index].event_uuid))
        if index in representatives
        else None
        for index, group in enumerate(groups)
    ]
    missing_raw_ids = _missing_raw_ids(
        team_id, [frame.get("raw_id") for example in examples if example for frame in example.frames]
    )

    results = []
    for index, (group, example) in enumerate(zip(groups, examples)):
        example_issues = _example_issues(
            index, matches, issues, scan_incomplete=scan.stopped_early or group.frames > len(group.raw_ids)
        )
        results.append(
            MissingSymbolsExample(
                reason=group.key.reason,
                location=None if frames_hidden else group.key.location,
                symbol_id=None if frames_hidden else group.key.symbol_id,
                http_status=group.key.http_status,
                frames=group.frames,
                issues=example_issues.top,
                issue_count=example_issues.count,
                issue_count_capped=example_issues.capped,
                example_exception=_example_exception(example, issues, missing_raw_ids) if example else None,
            )
        )
    return MissingSymbolsExamples(
        platform=platform, lookback_hours=LOOKBACK_HOURS, exceptions_loaded=exceptions_loaded, results=results
    )


def _exception_list_restricted(team_id: int, user: User) -> bool:
    restrictions = get_restricted_properties_with_group_type_index_for_team(user=user, team_id=team_id)
    return "$exception_list" in split_restricted_property_names(restrictions).event


def _example_groups(team_id: int, platform: SymbolsPlatform, since: datetime) -> list[_ExampleGroup]:
    # A JavaScript failure names its script, so frames group per file. Android and native failures
    # name the build's mapping or debug ID, so frames group per build and the class or image is an example.
    location_field = "source" if platform == SymbolsPlatform.JAVASCRIPT else "module"
    group_by = ("failure", "location") if platform == SymbolsPlatform.JAVASCRIPT else ("failure",)
    frame_id = Concat("raw_id", Value("/"), Cast("part", TextField()), output_field=TextField())
    rows = (
        ErrorTrackingStackFrame.objects.using(frames_database())
        .filter(MISSING_SYMBOLS, team_id=team_id, created_at__gte=since)
        .alias(platform=PLATFORM)
        .filter(platform=platform.value)
        .annotate(
            failure=KeyTextTransform("resolve_failure", "contents"),
            location=KeyTextTransform(location_field, "contents"),
        )
        .values(*group_by)
        .annotate(
            frames=Count("id"),
            example_location=Max("location"),
            raw_ids=_FirstRawIds(ArrayAgg(frame_id, order_by="-created_at")),
        )
        .order_by("-frames")[: EXAMPLES_LIMIT * 5]
    )

    # Rows with different failure texts can name the same file, such as one script that failed to fetch
    # under several URLs, so merge them on what the user sees.
    groups: dict[_ExampleKey, _ExampleGroup] = {}
    for row in rows:
        failure: str = row["failure"]
        rule = next(rule for rule in MISSING_SYMBOLS_RULES if failure.startswith(rule.prefixes))
        prefix = next(prefix for prefix in rule.prefixes if failure.startswith(prefix))
        url = _URL_PATTERN.search(failure)
        status = _HTTP_STATUS_PATTERN.match(failure)
        key = _ExampleKey(
            reason=rule.reason,
            location=url.group(0) if url else row["example_location"],
            symbol_id=failure[len(prefix) :].strip() if rule.reason in _REASONS_WITH_SYMBOL_ID else None,
            http_status=int(status.group(1)) if status else None,
        )
        group = groups.setdefault(key, _ExampleGroup(key=key, frames=0, raw_ids=[]))
        group.frames += row["frames"]
        group.raw_ids = list(dict.fromkeys([*group.raw_ids, *row["raw_ids"]]))[:RAW_IDS_PER_EXAMPLE]

    return sorted(groups.values(), key=lambda group: -group.frames)[:EXAMPLES_LIMIT]


def _exceptions_containing(team: Team, user: User, raw_ids_per_example: list[list[str]], since: datetime) -> _Scan:
    """Recent exceptions whose stack traces contain each example's frames, per example and fingerprint."""
    # The quotes make each needle match a whole JSON string, so `hash/1` cannot match `hash/10`.
    needles = [f'"{raw_id}"' for raw_ids in raw_ids_per_example for raw_id in raw_ids]
    needle_examples = [index for index, raw_ids in enumerate(raw_ids_per_example) for _ in raw_ids]
    if not needles:
        return _Scan(matches=[], stopped_early=False)

    started = monotonic()
    with tags_context(
        product=Product.ERROR_TRACKING, feature=Feature.QUERY, team_id=team.id, name="source_maps_examples"
    ):
        # Events keep no frame IDs outside `$exception_list`, so the scan reads each exception's properties.
        # It runs only when someone opens the examples, never in the hourly sweep.
        response = execute_hogql_query(
            query="""
                SELECT
                    example_index,
                    properties.$exception_fingerprint AS fingerprint,
                    count() AS occurrences,
                    argMax(uuid, timestamp) AS example_uuid,
                    max(timestamp) AS last_seen
                FROM events
                ARRAY JOIN arrayDistinct(
                    arrayFilter(
                        (example, position) -> position > 0,
                        {needle_examples},
                        multiSearchAllPositions(properties, {needles})
                    )
                ) AS example_index
                WHERE event = '$exception' AND timestamp >= {since}
                GROUP BY example_index, fingerprint
                ORDER BY occurrences DESC
                LIMIT {fingerprints_per_example} BY example_index
                LIMIT {max_rows}
            """,
            placeholders={
                "needles": ast.Constant(value=needles),
                "needle_examples": ast.Constant(value=needle_examples),
                "since": ast.Constant(value=since),
                "fingerprints_per_example": ast.Constant(value=FINGERPRINTS_PER_EXAMPLE),
                # Without a top-level limit, HogQL adds its default row limit and cuts off whole examples.
                "max_rows": ast.Constant(value=len(raw_ids_per_example) * FINGERPRINTS_PER_EXAMPLE),
            },
            team=team,
            user=user,
            ch_user=ClickHouseUser.ERROR_TRACKING,
            # A team with many exceptions can take longer than the limit. Stopping there still gives
            # examples, with counts that are lower bounds.
            settings=HogQLGlobalSettings(
                max_execution_time=EXCEPTIONS_QUERY_TIMEOUT_SECONDS, timeout_overflow_mode="break"
            ),
        )
    matches = [
        _FingerprintMatch(
            example_index=example_index,
            fingerprint=fingerprint,
            occurrences=occurrences,
            event_uuid=event_uuid,
            timestamp=timestamp,
        )
        for example_index, fingerprint, occurrences, event_uuid, timestamp in response.results or []
        if fingerprint
    ]
    # ClickHouse does not report a break, so a scan that ran to the limit counts as stopped early.
    return _Scan(matches=matches, stopped_early=monotonic() - started >= EXCEPTIONS_QUERY_TIMEOUT_SECONDS)


def _representatives(matches: list[_FingerprintMatch]) -> dict[int, _FingerprintMatch]:
    """The latest event of each example's most frequent fingerprint."""
    representatives: dict[int, _FingerprintMatch] = {}
    for match in sorted(matches, key=lambda match: -match.occurrences):
        representatives.setdefault(match.example_index, match)
    return representatives


def _exception_lists(team: Team, user: User, representatives: list[_FingerprintMatch]) -> dict[UUID, str]:
    if not representatives:
        return {}
    with tags_context(
        product=Product.ERROR_TRACKING, feature=Feature.QUERY, team_id=team.id, name="source_maps_examples"
    ):
        response = execute_hogql_query(
            query="""
                SELECT uuid, properties.$exception_list
                FROM events
                WHERE event = '$exception' AND timestamp >= {earliest} AND timestamp <= {latest} AND uuid IN {uuids}
                LIMIT {max_rows}
            """,
            placeholders={
                "earliest": ast.Constant(value=min(match.timestamp for match in representatives)),
                "latest": ast.Constant(value=max(match.timestamp for match in representatives)),
                "uuids": ast.Constant(value=[match.event_uuid for match in representatives]),
                "max_rows": ast.Constant(value=len(representatives)),
            },
            team=team,
            user=user,
            ch_user=ClickHouseUser.ERROR_TRACKING,
            settings=HogQLGlobalSettings(max_execution_time=EXCEPTIONS_QUERY_TIMEOUT_SECONDS),
        )
    return {event_uuid: exception_list for event_uuid, exception_list in response.results or [] if exception_list}


def _issues_by_fingerprint(team_id: int, fingerprints: set[str]) -> dict[str, MissingSymbolsIssue]:
    rows = ErrorTrackingIssueFingerprintV2.objects.filter(team_id=team_id, fingerprint__in=fingerprints).values(
        "fingerprint", "issue_id", "issue__name", "issue__description"
    )
    return {
        row["fingerprint"]: MissingSymbolsIssue(
            id=row["issue_id"], name=row["issue__name"], description=row["issue__description"], occurrences=0
        )
        for row in rows
    }


def _example_issues(
    example_index: int,
    matches: list[_FingerprintMatch],
    issues: dict[str, MissingSymbolsIssue],
    *,
    scan_incomplete: bool,
) -> _ExampleIssues:
    # Merged issues own several fingerprints, so their counts add up.
    occurrences: dict[UUID, int] = {}
    by_id: dict[UUID, MissingSymbolsIssue] = {}
    fingerprints = 0
    for match in matches:
        if match.example_index != example_index:
            continue
        fingerprints += 1
        issue = issues.get(match.fingerprint)
        if issue is None:
            continue
        occurrences[issue.id] = occurrences.get(issue.id, 0) + match.occurrences
        by_id[issue.id] = issue
    ranked = sorted(occurrences, key=lambda issue_id: -occurrences[issue_id])
    return _ExampleIssues(
        top=[
            MissingSymbolsIssue(
                id=issue_id,
                name=by_id[issue_id].name,
                description=by_id[issue_id].description,
                occurrences=occurrences[issue_id],
            )
            for issue_id in ranked[:ISSUES_PER_EXAMPLE]
        ],
        count=len(ranked),
        # The scan misses the issues of frames left out of the sample, of events past its time limit,
        # and of fingerprints past its row limit.
        capped=scan_incomplete or fingerprints >= FINGERPRINTS_PER_EXAMPLE,
    )


def _parsed_example(
    group: _ExampleGroup, representative: _FingerprintMatch, exception_list: str | None
) -> _ParsedException | None:
    """The exception in the representative event that holds the example's frames."""
    if not exception_list:
        return None
    try:
        exceptions = json.loads(exception_list)
    except ValueError:
        return None
    if not isinstance(exceptions, list):
        return None
    raw_ids = set(group.raw_ids)
    for exception in exceptions:
        frames = ((exception or {}).get("stacktrace") or {}).get("frames") or []
        matching = [index for index, frame in enumerate(frames) if frame.get("raw_id") in raw_ids]
        if not matching:
            continue
        # Keep the frames nearest the crash site, unless that would drop every frame of the example.
        start = min(max(len(frames) - FRAMES_PER_EXCEPTION, 0), matching[-1])
        return _ParsedException(
            fingerprint=representative.fingerprint,
            timestamp=representative.timestamp,
            type=exception.get("type"),
            value=exception.get("value"),
            frames=frames[start : start + FRAMES_PER_EXCEPTION],
        )
    return None


def _missing_raw_ids(team_id: int, raw_ids: list[str | None]) -> set[str]:
    """The `hash/part` frame IDs among these that an upload of symbols would resolve."""
    wanted = {raw_id for raw_id in raw_ids if raw_id}
    if not wanted:
        return set()
    rows = (
        ErrorTrackingStackFrame.objects.using(frames_database())
        .filter(
            MISSING_SYMBOLS,
            team_id=team_id,
            raw_id__in={split_stack_frame_raw_id(raw_id)[0] for raw_id in wanted},
        )
        .values_list("raw_id", "part")
    )
    return {f"{raw_id}/{part}" for raw_id, part in rows} & wanted


def _example_exception(
    example: _ParsedException, issues: dict[str, MissingSymbolsIssue], missing_raw_ids: set[str]
) -> MissingSymbolsExampleException:
    issue = issues.get(example.fingerprint)
    return MissingSymbolsExampleException(
        issue_id=issue.id if issue else None,
        fingerprint=example.fingerprint,
        timestamp=example.timestamp,
        type=example.type,
        value=example.value,
        frames=[
            MissingSymbolsStackFrame(
                function=frame.get("resolved_name") or frame.get("mangled_name"),
                source=frame.get("source"),
                line=frame.get("line") if isinstance(frame.get("line"), int) else None,
                column=frame.get("column") if isinstance(frame.get("column"), int) else None,
                in_app=bool(frame.get("in_app")),
                missing_symbols=frame.get("raw_id") in missing_raw_ids,
            )
            for frame in reversed(example.frames)
        ],
    )
