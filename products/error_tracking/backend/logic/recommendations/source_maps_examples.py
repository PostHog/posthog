import re
import json
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from django.contrib.postgres.aggregates import ArrayAgg
from django.contrib.postgres.fields import ArrayField
from django.db.models import Count, Func, Max, TextField
from django.db.models.fields.json import KeyTextTransform
from django.utils import timezone

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import ClickHouseUser
from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception
from posthog.models import Team

from products.error_tracking.backend.facade.contracts import (
    MissingSymbolsExample,
    MissingSymbolsExampleException,
    MissingSymbolsExamples,
    MissingSymbolsIssue,
    MissingSymbolsReason,
    MissingSymbolsStackFrame,
    SymbolsPlatform,
)
from products.error_tracking.backend.models import ErrorTrackingIssueFingerprintV2, ErrorTrackingStackFrame

from .source_maps import LOOKBACK_HOURS, MISSING_SYMBOLS, MISSING_SYMBOLS_RULES, PLATFORM, frames_database

EXAMPLES_LIMIT = 10
# Ten examples of twenty frame IDs stay under ClickHouse's limit of 255 needles in one multi-search.
RAW_IDS_PER_EXAMPLE = 20
ISSUES_PER_EXAMPLE = 5
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


class _FirstRawIds(Func):
    # Postgres still aggregates every frame ID, but only the first ones leave the database.
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
    raw_ids: list[str]


@frozen
class _ExceptionMatch:
    example_index: int
    fingerprint: str
    occurrences: int
    exception_list: str | None


@frozen
class _ParsedException:
    type: str | None
    value: str | None
    # Stored order: the entry point first and the crash site last.
    frames: list[dict[str, Any]]


def missing_symbols_examples(team_id: int, platform: SymbolsPlatform) -> MissingSymbolsExamples:
    """The files and builds with the most frames missing symbols on one platform, with the exceptions they appear in."""
    since = timezone.now() - timedelta(hours=LOOKBACK_HOURS)
    groups = _example_groups(team_id, platform, since)

    try:
        matches = _exceptions_containing(team_id, [group.raw_ids for group in groups], since)
        exceptions_loaded = True
    except Exception as error:
        # The examples stay useful without exceptions, so a slow or failed scan only drops them.
        capture_exception(error)
        matches, exceptions_loaded = [], False

    issues = _issues_by_fingerprint(team_id, {match.fingerprint for match in matches})
    examples = [_parsed_example(group, matches, index) for index, group in enumerate(groups)]
    missing_raw_ids = _missing_raw_ids(
        team_id, [frame.get("raw_id") for example in examples if example for frame in example.frames]
    )

    return MissingSymbolsExamples(
        platform=platform,
        lookback_hours=LOOKBACK_HOURS,
        exceptions_loaded=exceptions_loaded,
        results=[
            MissingSymbolsExample(
                reason=group.key.reason,
                location=group.key.location,
                symbol_id=group.key.symbol_id,
                http_status=group.key.http_status,
                frames=group.frames,
                issues=_example_issues(index, matches, issues),
                example_exception=_example_exception(example, missing_raw_ids) if example else None,
            )
            for index, (group, example) in enumerate(zip(groups, examples))
        ],
    )


def _example_groups(team_id: int, platform: SymbolsPlatform, since: datetime) -> list[_ExampleGroup]:
    # A JavaScript failure names its script, so frames group per file. Android and native failures
    # name the build's mapping or debug ID, so frames group per build and the class or image is an example.
    location_field = "source" if platform == SymbolsPlatform.JAVASCRIPT else "module"
    group_by = ("failure", "location") if platform == SymbolsPlatform.JAVASCRIPT else ("failure",)
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
            raw_ids=_FirstRawIds(ArrayAgg("raw_id", order_by="-created_at")),
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


def _exceptions_containing(
    team_id: int, raw_ids_per_example: list[list[str]], since: datetime
) -> list[_ExceptionMatch]:
    """Recent exceptions whose stack traces contain each example's frames, per example and fingerprint."""
    needles = [raw_id for raw_ids in raw_ids_per_example for raw_id in raw_ids]
    needle_examples = [index for index, raw_ids in enumerate(raw_ids_per_example) for _ in raw_ids]
    if not needles:
        return []

    with tags_context(
        product=Product.ERROR_TRACKING, feature=Feature.QUERY, team_id=team_id, name="source_maps_examples"
    ):
        # Events keep no frame IDs outside `$exception_list`, so the scan reads each exception's properties.
        # It runs only when someone opens the examples, never in the hourly sweep.
        response = execute_hogql_query(
            query="""
                SELECT
                    example_index,
                    properties.$exception_fingerprint AS fingerprint,
                    count() AS occurrences,
                    argMax(properties.$exception_list, timestamp) AS exception_list
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
                LIMIT 1000
            """,
            placeholders={
                "needles": ast.Constant(value=needles),
                "needle_examples": ast.Constant(value=needle_examples),
                "since": ast.Constant(value=since),
            },
            team=Team.objects.get(id=team_id),
            ch_user=ClickHouseUser.ERROR_TRACKING,
            settings=HogQLGlobalSettings(max_execution_time=EXCEPTIONS_QUERY_TIMEOUT_SECONDS),
        )
    return [
        _ExceptionMatch(
            example_index=example_index,
            fingerprint=fingerprint,
            occurrences=occurrences,
            exception_list=exception_list,
        )
        for example_index, fingerprint, occurrences, exception_list in response.results or []
        if fingerprint
    ]


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
    example_index: int, matches: list[_ExceptionMatch], issues: dict[str, MissingSymbolsIssue]
) -> list[MissingSymbolsIssue]:
    # Merged issues own several fingerprints, so their counts add up.
    occurrences: dict[UUID, int] = {}
    by_id: dict[UUID, MissingSymbolsIssue] = {}
    for match in matches:
        issue = issues.get(match.fingerprint)
        if match.example_index != example_index or issue is None:
            continue
        occurrences[issue.id] = occurrences.get(issue.id, 0) + match.occurrences
        by_id[issue.id] = issue
    ranked = sorted(occurrences, key=lambda issue_id: -occurrences[issue_id])[:ISSUES_PER_EXAMPLE]
    return [
        MissingSymbolsIssue(
            id=issue_id,
            name=by_id[issue_id].name,
            description=by_id[issue_id].description,
            occurrences=occurrences[issue_id],
        )
        for issue_id in ranked
    ]


def _parsed_example(
    group: _ExampleGroup, matches: list[_ExceptionMatch], example_index: int
) -> _ParsedException | None:
    """The exception that holds the example's frames, from its most frequent fingerprint."""
    raw_ids = set(group.raw_ids)
    for match in matches:
        if match.example_index != example_index or not match.exception_list:
            continue
        try:
            exceptions = json.loads(match.exception_list)
        except ValueError:
            continue
        if not isinstance(exceptions, list):
            continue
        for exception in exceptions:
            frames = ((exception or {}).get("stacktrace") or {}).get("frames") or []
            if any(frame.get("raw_id") in raw_ids for frame in frames):
                return _ParsedException(
                    type=exception.get("type"), value=exception.get("value"), frames=frames[-FRAMES_PER_EXCEPTION:]
                )
    return None


def _missing_raw_ids(team_id: int, raw_ids: list[str | None]) -> set[str]:
    wanted = {raw_id for raw_id in raw_ids if raw_id}
    if not wanted:
        return set()
    return set(
        ErrorTrackingStackFrame.objects.using(frames_database())
        .filter(MISSING_SYMBOLS, team_id=team_id, raw_id__in=wanted)
        .values_list("raw_id", flat=True)
    )


def _example_exception(example: _ParsedException, missing_raw_ids: set[str]) -> MissingSymbolsExampleException:
    return MissingSymbolsExampleException(
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
