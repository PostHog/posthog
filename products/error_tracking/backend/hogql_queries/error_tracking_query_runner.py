import uuid
import datetime
from typing import Any
from zoneinfo import ZoneInfo

import structlog
from rest_framework.exceptions import ValidationError

from posthog.schema import (
    CachedErrorTrackingQueryResponse,
    ErrorTrackingIssueStatus,
    ErrorTrackingPhantomFingerprintIssueState,
    ErrorTrackingQuery,
    ErrorTrackingQueryResponse,
)

from posthog.hogql import ast
from posthog.hogql.constants import LimitContext
from posthog.hogql.context import HogQLContext

from posthog.hogql_queries.insights.paginators import HogQLHasMorePaginator
from posthog.hogql_queries.query_runner import AnalyticsQueryRunner
from posthog.models.filters.mixins.utils import cached_property
from posthog.utils import relative_date_parse

from products.error_tracking.backend.hogql_queries.error_tracking_query_runner_v1 import ErrorTrackingQueryV1Builder
from products.error_tracking.backend.hogql_queries.error_tracking_query_runner_v2 import ErrorTrackingQueryV2Builder
from products.error_tracking.backend.hogql_queries.error_tracking_query_runner_v3 import ErrorTrackingQueryV3Builder

logger = structlog.get_logger(__name__)

MAX_FINGERPRINT_PHANTOMS = 500
_VALID_STATUSES = {s.value for s in ErrorTrackingIssueStatus}


def _coerce_first_seen(value: Any) -> str:
    """Normalize an ISO-ish timestamp into a form ClickHouse's `toDateTime64(..., 3, 'UTC')`
    can parse (no trailing `Z`, space separator, microsecond precision preserved).
    """
    if isinstance(value, datetime.datetime):
        dt = value
    else:
        s = str(value).strip()
        # `fromisoformat` in Py3.12 handles trailing `Z` via `'Z' -> '+00:00'` shim below.
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            dt = datetime.datetime.fromisoformat(s)
        except ValueError:
            raise ValidationError(f"Invalid first_seen in phantom fingerprint row: {value!r}")
    if dt.tzinfo is not None:
        dt = dt.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
    return dt.strftime("%Y-%m-%d %H:%M:%S.%f")


class ErrorTrackingQueryRunner(AnalyticsQueryRunner[ErrorTrackingQueryResponse]):
    query: ErrorTrackingQuery
    cached_response: CachedErrorTrackingQueryResponse
    paginator: HogQLHasMorePaginator
    date_from: datetime.datetime
    date_to: datetime.datetime

    CACHE_VERSION = 2

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.paginator = HogQLHasMorePaginator.from_limit_context(
            limit_context=LimitContext.QUERY,
            limit=self.query.limit if self.query.limit else None,
            offset=self.query.offset,
        )
        self.date_from = ErrorTrackingQueryRunner.parse_relative_date_from(self.query.dateRange.date_from)
        self.date_to = ErrorTrackingQueryRunner.parse_relative_date_to(self.query.dateRange.date_to)

        if self.query.withAggregations is None:
            self.query.withAggregations = True

        if self.query.withFirstEvent is None:
            self.query.withFirstEvent = True

        if self.query.withLastEvent is None:
            self.query.withLastEvent = False

    @cached_property
    def _builder(self) -> ErrorTrackingQueryV1Builder | ErrorTrackingQueryV2Builder | ErrorTrackingQueryV3Builder:
        if self.query.useQueryV3:
            return ErrorTrackingQueryV3Builder(self.query, self.date_from, self.date_to)
        if self.query.useQueryV2:
            return ErrorTrackingQueryV2Builder(self.query, self.date_from, self.date_to)
        return ErrorTrackingQueryV1Builder(self.query, self.team, self.date_from, self.date_to)

    def get_cache_payload(self) -> dict:
        payload = super().get_cache_payload()
        payload["error_tracking_cache_version"] = self.CACHE_VERSION
        return payload

    @classmethod
    def parse_relative_date_from(cls, date: str | None) -> datetime.datetime:
        if date == "all" or date is None:
            return datetime.datetime.now(tz=ZoneInfo("UTC")) - datetime.timedelta(days=365 * 4)
        return relative_date_parse(date, now=datetime.datetime.now(tz=ZoneInfo("UTC")), timezone_info=ZoneInfo("UTC"))

    @classmethod
    def parse_relative_date_to(cls, date: str | None) -> datetime.datetime:
        if not date:
            return datetime.datetime.now(tz=ZoneInfo("UTC"))
        if date == "all":
            raise ValueError("Invalid date range")
        return relative_date_parse(date, ZoneInfo("UTC"), increase=True)

    def to_query(self) -> ast.SelectQuery:
        return self._builder.build_query()

    @cached_property
    def _sanitized_fingerprint_phantoms(self) -> list[dict[str, Any]]:
        """Validate + sanitize client-supplied phantom fingerprint rows.

        team_id is always stamped from `self.team.id`, never trusted from the client.
        """
        raw = self.query.phantomFingerprintIssueStates or []
        if not raw:
            return []
        if len(raw) > MAX_FINGERPRINT_PHANTOMS:
            raise ValidationError(f"phantomFingerprintIssueStates exceeds limit of {MAX_FINGERPRINT_PHANTOMS} rows")

        sanitized: list[dict[str, Any]] = []
        for row in raw:
            if not isinstance(row, ErrorTrackingPhantomFingerprintIssueState):
                continue
            try:
                issue_uuid = uuid.UUID(row.issue_id)
            except (ValueError, TypeError, AttributeError):
                raise ValidationError(f"Invalid issue_id in phantom fingerprint row: {row.issue_id!r}")

            if row.issue_status not in _VALID_STATUSES:
                raise ValidationError(f"Invalid issue_status in phantom fingerprint row: {row.issue_status!r}")

            assigned_role_id = None
            if row.assigned_role_id is not None:
                try:
                    assigned_role_id = str(uuid.UUID(str(row.assigned_role_id)))
                except (ValueError, TypeError):
                    raise ValidationError(
                        f"Invalid assigned_role_id in phantom fingerprint row: {row.assigned_role_id!r}"
                    )

            sanitized.append(
                {
                    "team_id": self.team.id,
                    "fingerprint": str(row.fingerprint),
                    "issue_id": str(issue_uuid),
                    "issue_name": None if row.issue_name is None else str(row.issue_name),
                    "issue_description": None if row.issue_description is None else str(row.issue_description),
                    "issue_status": str(row.issue_status),
                    "assigned_user_id": None if row.assigned_user_id is None else int(row.assigned_user_id),
                    "assigned_role_id": assigned_role_id,
                    "first_seen": _coerce_first_seen(row.first_seen),
                    "is_deleted": int(row.is_deleted) if row.is_deleted is not None else 0,
                    "version": int(row.version),
                }
            )
        return sanitized

    def _hogql_context(self) -> HogQLContext:
        ctx = HogQLContext(team_id=self.team.pk, team=self.team, user=self.user, enable_select_queries=True)
        phantoms = self._sanitized_fingerprint_phantoms
        if phantoms:
            ctx.error_tracking_fingerprint_phantoms = phantoms
        return ctx

    def _calculate(self):
        phantoms = self._sanitized_fingerprint_phantoms
        if phantoms:
            logger.warning(
                "error_tracking_query_runner_phantoms_present",
                phantom_count=len(phantoms),
                phantom_sample=phantoms[:3],
                team_id=self.team.id,
                use_query_v3=bool(self.query.useQueryV3),
            )

        with self.timings.measure("error_tracking_query_hogql_execute"):
            try:
                query_result = self.paginator.execute_hogql_query(
                    query=self._builder.build_query(),
                    team=self.team,
                    query_type="ErrorTrackingQuery",
                    timings=self.timings,
                    modifiers=self.modifiers,
                    limit_context=self.limit_context,
                    filters=self._builder.hogql_filters(),
                    user=self.user,
                    context=self._hogql_context(),
                )
            except Exception as e:
                # Surface the real CH / HogQL error along with the generated SQL so
                # we can debug. Re-raise to keep default 500 behaviour.
                try:
                    from posthog.hogql.printer import print_ast
                    from posthog.hogql.query import create_default_modifiers_for_team

                    ctx = self._hogql_context()
                    ctx.enable_select_queries = True
                    debug_hogql = print_ast(
                        self._builder.build_query(),
                        context=ctx,
                        dialect="hogql",
                        modifiers=create_default_modifiers_for_team(self.team, self.modifiers),
                    )
                except Exception as print_err:
                    debug_hogql = f"<failed to print: {print_err!r}>"
                logger.exception(
                    "error_tracking_query_runner_failed",
                    error=repr(e),
                    phantom_count=len(phantoms),
                    hogql=debug_hogql[:10000],
                )
                raise

        columns: list[str] = query_result.columns or []

        return ErrorTrackingQueryResponse(
            columns=columns,
            results=self._builder.process_results(columns, query_result.results),
            timings=query_result.timings,
            hogql=query_result.hogql,
            modifiers=self.modifiers,
            **self.paginator.response_params(),
        )
