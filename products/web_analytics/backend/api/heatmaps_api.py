from datetime import date, datetime, timedelta
from json import JSONDecodeError, loads
from typing import Any, List, Literal, cast  # noqa: UP035

from django.core.exceptions import FieldError
from django.db.models import Q
from django.http import HttpResponse

import structlog
import posthoganalytics
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema, extend_schema_field
from prometheus_client import Counter
from rest_framework import request, response, serializers, status, viewsets

from posthog.schema import DateRange, HogQLFilters, HogQLQueryResponse, ProductKey

from posthog.hogql import ast
from posthog.hogql.ast import Constant
from posthog.hogql.base import Expr
from posthog.hogql.constants import MAX_SELECT_HEATMAPS_LIMIT, LimitContext
from posthog.hogql.context import HogQLContext
from posthog.hogql.filters import replace_filters
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.api.utils import action
from posthog.auth import ExportRendererAuthentication
from posthog.clickhouse.query_tagging import Feature, tag_queries
from posthog.helpers.impersonation import is_impersonated
from posthog.models import Team, User
from posthog.models.activity_logging.activity_log import Detail, log_activity
from posthog.rate_limit import (
    AIBurstRateThrottle,
    AISustainedRateThrottle,
    ClickHouseBurstRateThrottle,
    ClickHouseSustainedRateThrottle,
)
from posthog.security.url_validation import is_url_allowed
from posthog.utils import relative_date_parse_with_delta_mapping

from products.cohorts.backend.models.cohort import Cohort
from products.web_analytics.backend.api.heatmaps_utils import DEFAULT_TARGET_WIDTHS, MAX_TARGET_WIDTHS
from products.web_analytics.backend.models import HeatmapSnapshot, SavedHeatmap
from products.web_analytics.backend.tasks.heatmap_screenshot import generate_heatmap_screenshot

STALE_PROCESSING_THRESHOLD = timedelta(minutes=10)

HEATMAPS_COHORT_FILTER_FLAG = "heatmaps-cohort-filter"

logger = structlog.get_logger(__name__)

HEATMAP_CONTENT_REQUESTS = Counter(
    "heatmap_screenshot_content_requests",
    "Heatmap screenshot content endpoint responses",
    labelnames=["outcome"],
)


def _heatmaps_cohort_filter_enabled(user: User, team: Team) -> bool:
    distinct_id = getattr(user, "distinct_id", None)
    if not distinct_id:
        return False
    try:
        return bool(
            posthoganalytics.feature_enabled(
                HEATMAPS_COHORT_FILTER_FLAG,
                str(distinct_id),
                groups={"organization": str(team.organization_id), "project": str(team.id)},
                group_properties={
                    "organization": {"id": str(team.organization_id)},
                    "project": {"id": str(team.id)},
                },
                send_feature_flag_events=False,
            )
        )
    except Exception:
        return False


DEFAULT_QUERY = """
            select pointer_target_fixed, pointer_relative_x, client_y, {aggregation_count}
            from (
                     select
                        distinct_id,
                        pointer_target_fixed,
                        round((x / viewport_width), 2) as pointer_relative_x,
                        y * scale_factor as client_y
                     from heatmaps
                     where {predicates}
                )
            group by `pointer_target_fixed`, pointer_relative_x, client_y
            order by cnt desc
            limit {limit}
            offset {offset}
            """

SCROLL_DEPTH_QUERY = """
SELECT
    bucket,
    cnt as bucket_count,
    sum(cnt) OVER (ORDER BY bucket DESC) AS cumulative_count
FROM (
    SELECT
        intDiv(scroll_y, 100) * 100 as bucket,
        {aggregation_count} as cnt
    FROM (
        SELECT
           distinct_id, (y + viewport_height) * scale_factor as scroll_y
        FROM heatmaps
        WHERE {predicates}
    )
    GROUP BY bucket
)
ORDER BY bucket
"""

EVENTS_QUERY = """
SELECT
    session_id,
    distinct_id,
    timestamp,
    round((x / viewport_width), 2) as pointer_relative_x,
    y * scale_factor as pointer_y,
    current_url,
    type
FROM heatmaps
WHERE {predicates}
ORDER BY timestamp DESC
LIMIT {limit}
OFFSET {offset}
"""

# Above/below-the-fold summary for positional (non-scrolldepth) interactions. Fixed-position
# elements move with the viewport so they're never "below the fold" — excluded from both the
# numerator and the denominator. `y` and `viewport_height` are stored in the same scaled units,
# so `y > viewport_height` means the interaction sat below the user's initial viewport.
FOLD_SUMMARY_QUERY = """
SELECT
    countIf(NOT pointer_target_fixed) AS total,
    countIf(y > viewport_height AND NOT pointer_target_fixed) AS below_fold,
    round(quantile(0.5)(viewport_height * scale_factor)) AS median_viewport_height
FROM heatmaps
WHERE {predicates}
"""


def parse_fold_summary_row(row: Any) -> dict[str, Any]:
    """Shape a single FOLD_SUMMARY_QUERY result row (or None for an empty result) into the
    fold-summary payload. Shared so every caller applies the same NaN coercion and pct math."""
    total = int(row[0]) if row else 0
    below = int(row[1]) if row else 0
    # quantile over an empty set returns NaN (which is != itself); coerce to None.
    raw_median = row[2] if row else None
    median = int(raw_median) if raw_median is not None and raw_median == raw_median else None
    return {
        "total_count": total,
        "below_fold_count": below,
        "pct_below_fold": round(100 * below / total, 1) if total else 0.0,
        "median_viewport_height": median,
    }


class HeatmapsRequestSerializer(serializers.Serializer):
    viewport_width_min = serializers.IntegerField(
        required=False,
        help_text="Only include interactions captured at a viewport at least this wide, in CSS pixels. "
        "Use with viewport_width_max to isolate a device class (e.g. 360-768 for mobile).",
    )
    viewport_width_max = serializers.IntegerField(
        required=False,
        help_text="Only include interactions captured at a viewport at most this wide, in CSS pixels.",
    )
    type = serializers.CharField(
        required=False,
        default="click",
        help_text="The interaction type to return. One of: 'click' (default), 'rageclick', 'mousemove', "
        "or 'scrolldepth'. Scrolldepth returns scroll buckets instead of x/y coordinates.",
    )
    date_from = serializers.CharField(
        required=False,
        default="-7d",
        help_text="Start of the window. Relative (e.g. '-7d', '-30d', '-1mStart') or an absolute 'YYYY-MM-DD' date. "
        "Defaults to '-7d'. Heatmap data is retained for 90 days.",
    )
    date_to = serializers.CharField(
        required=False,
        help_text="End of the window, inclusive. Relative or absolute 'YYYY-MM-DD'. Defaults to today.",
    )
    url_exact = serializers.CharField(
        required=False,
        help_text="Match a single page by exact URL (trailing slash is ignored). Mutually exclusive with url_pattern.",
    )
    url_pattern = serializers.CharField(
        required=False,
        help_text="Match pages by regex against the full current_url (anchored automatically). Use this to aggregate "
        "across query strings or path segments. Mutually exclusive with url_exact.",
    )
    aggregation = serializers.ChoiceField(
        required=False,
        choices=["unique_visitors", "total_count"],
        help_text="How to aggregate counts: 'total_count' (every interaction, default) or 'unique_visitors' "
        "(distinct people).",
        default="total_count",
    )
    filter_test_accounts = serializers.BooleanField(
        required=False,
        default=None,
        allow_null=True,
        help_text="When true, exclude sessions from internal/test accounts using the project's test-account filters.",
    )
    hide_zero_coordinates = serializers.BooleanField(
        required=False,
        default=True,
        help_text="When true (default), drop interactions recorded at the (0, 0) origin, which are usually noise.",
    )
    cohort_ids = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        help_text="JSON array of cohort IDs (e.g. '[123, 456]') to restrict results to people in those cohorts. "
        "Feature-flagged; ignored when the cohort filter is not enabled for the caller.",
    )
    limit = serializers.IntegerField(
        required=False,
        default=500,
        min_value=0,
        max_value=MAX_SELECT_HEATMAPS_LIMIT,
        help_text="Maximum number of coordinate points to return, ordered hottest-first by count. Defaults to 500. "
        "Pass 0 to fetch the full set (every coordinate) needed to render a complete heatmap overlay. "
        "Ignored for the 'scrolldepth' type, which always returns every bucket.",
    )
    offset = serializers.IntegerField(
        required=False,
        default=0,
        min_value=0,
        max_value=MAX_SELECT_HEATMAPS_LIMIT,
        help_text="Number of hottest-first points to skip, for paging through cooler coordinates. "
        "Ignored for the 'scrolldepth' type.",
    )

    def validate_cohort_ids(self, value: str | None) -> list[int]:
        if value is None or value == "":
            return []
        try:
            cohort_ids = loads(value)
        except JSONDecodeError:
            raise serializers.ValidationError("cohort_ids must be valid JSON")
        if not isinstance(cohort_ids, list) or not all(isinstance(cid, int) for cid in cohort_ids):
            raise serializers.ValidationError("cohort_ids must be a JSON array of integers")
        if not cohort_ids:
            return []
        team_cohort_ids = set(
            Cohort.objects.filter(
                id__in=cohort_ids,
                team__project_id=self.context["team"].project_id,
                deleted=False,
            ).values_list("id", flat=True)
        )
        missing = [cid for cid in cohort_ids if cid not in team_cohort_ids]
        if missing:
            raise serializers.ValidationError(f"Cohort(s) not found or deleted: {missing}")
        return cohort_ids

    def validate_date(self, value, label: Literal["date_from", "date_to"]) -> date:
        try:
            if isinstance(value, str):
                parsed_date, _, _ = relative_date_parse_with_delta_mapping(value, self.context["team"].timezone_info)
                return parsed_date.date()
            if isinstance(value, datetime):
                return value.date()
            if isinstance(value, date):
                return value
            else:
                raise serializers.ValidationError(f"Invalid {label} provided: {value}")
        except Exception:
            raise serializers.ValidationError(f"Error parsing provided {label}: {value}")

    def validate_date_from(self, value) -> date:
        return self.validate_date(value, "date_from")

    def validate_date_to(self, value) -> date:
        return self.validate_date(value, "date_to")

    def validate_url_pattern(self, value: str | None) -> str | None:
        if value is None:
            return None

        validated_value = value

        # we insist on the pattern being anchored
        if not value.startswith("^"):
            validated_value = f"^{value}"
        if not value.endswith("$"):
            validated_value = f"{validated_value}$"

        # KLUDGE: we allow API callers to send something that isn't really `re2` syntax used in match()
        # KLUDGE: so if it has * but not .* then we expect at least one character to match, so we use .+ instead
        # KLUDGE: this means we don't support valid regex since we can't support matching aaaaa with a*
        # KLUDGE: but you could send a+ and it would match aaaaa
        validated_value = "".join(
            [
                f".+" if c == "*" and i > 0 and validated_value[i - 1] != "." else c
                for i, c in enumerate(validated_value)
            ]
        )

        return validated_value

    def validate(self, values) -> dict:
        url_exact = values.get("url_exact", None)
        url_pattern = values.get("url_pattern", None)
        if isinstance(url_exact, str) and isinstance(url_pattern, str):
            if url_exact == url_pattern:
                values.pop("url_pattern")
            else:
                values.pop("url_exact")

        if values.get("filter_test_accounts") and not isinstance(values.get("filter_test_accounts"), bool):
            raise serializers.ValidationError("filter_test_accounts must be a boolean")

        return values


class HeatmapResponseItemSerializer(serializers.Serializer):
    count = serializers.IntegerField(required=True)
    pointer_y = serializers.IntegerField(required=True)
    pointer_relative_x = serializers.FloatField(required=True)
    pointer_target_fixed = serializers.BooleanField(required=True)


class HeatmapFoldSummarySerializer(serializers.Serializer):
    total_count = serializers.IntegerField(
        help_text="Number of non-fixed interactions of this type on the page in the window (the population the "
        "above/below-the-fold split applies to; fixed-position elements are excluded since they're always on screen)."
    )
    below_fold_count = serializers.IntegerField(
        help_text="How many of those interactions happened below the user's initial viewport — i.e. they had to "
        "scroll to reach them."
    )
    pct_below_fold = serializers.FloatField(
        help_text="Percentage of non-fixed interactions that were below the initial viewport (0-100). A high value "
        "means engaged content sits off the first screen and is a candidate to move up."
    )
    median_viewport_height = serializers.IntegerField(
        allow_null=True,
        help_text="Median viewport height in CSS pixels across the matched interactions — the typical fold line to "
        "recommend against. Null when there are no interactions.",
    )


class HeatmapsResponseSerializer(serializers.Serializer):
    results = HeatmapResponseItemSerializer(many=True)
    fold = HeatmapFoldSummarySerializer(
        required=False,
        allow_null=True,
        help_text="Above/below-the-fold summary for the returned interactions. Present for "
        "click/rageclick/mousemove; omitted for scrolldepth.",
    )
    has_more = serializers.BooleanField(
        required=False,
        default=False,
        help_text="True when more coordinate points exist beyond the returned page. Raise 'limit' or page with "
        "'offset' to fetch them. Always false for scrolldepth, which returns every bucket.",
    )


class HeatmapScrollDepthResponseItemSerializer(serializers.Serializer):
    cumulative_count = serializers.IntegerField(required=True)
    bucket_count = serializers.IntegerField(required=True)
    scroll_depth_bucket = serializers.IntegerField(required=True)


class HeatmapsScrollDepthResponseSerializer(serializers.Serializer):
    results = HeatmapScrollDepthResponseItemSerializer(many=True)


class HeatmapEventsRequestSerializer(HeatmapsRequestSerializer):
    points = serializers.CharField(
        required=True,
        help_text='JSON array of the heatmap coordinates to drill into, e.g. \'[{"x": 0.5, "y": 100}]\'. '
        "Each point needs 'x' (relative x, 0..1) and 'y' (absolute client-y pixels) matching values returned "
        "by the heatmaps list endpoint; an optional 'target_fixed' boolean matches fixed-position elements. "
        "Returns the individual session interactions behind those spots.",
    )
    limit = serializers.IntegerField(
        required=False, default=50, min_value=1, max_value=100, help_text="Maximum interactions to return (1-100)."
    )
    offset = serializers.IntegerField(
        required=False, default=0, min_value=0, help_text="Number of interactions to skip, for pagination."
    )

    def validate_points(self, value: str) -> list[dict]:
        try:
            points = loads(value)
            if not isinstance(points, list) or len(points) == 0:
                raise serializers.ValidationError("points must be a non-empty array")
            for point in points:
                if not isinstance(point, dict) or "x" not in point or "y" not in point:
                    raise serializers.ValidationError("each point must have x and y")
            return points
        except JSONDecodeError:
            raise serializers.ValidationError("points must be valid JSON")


class HeatmapEventItemSerializer(serializers.Serializer):
    session_id = serializers.CharField(required=False, allow_null=True)
    distinct_id = serializers.CharField(required=True)
    timestamp = serializers.DateTimeField(required=True)
    pointer_relative_x = serializers.FloatField(required=True)
    pointer_y = serializers.IntegerField(required=True)
    current_url = serializers.CharField(required=True)
    type = serializers.CharField(required=True)


class HeatmapEventsResponseSerializer(serializers.Serializer):
    results = HeatmapEventItemSerializer(many=True)
    total_count = serializers.IntegerField(required=True)
    has_more = serializers.BooleanField(required=True)


class HeatmapViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    authentication_classes = [ExportRendererAuthentication]
    scope_object = "heatmap"
    scope_object_read_actions = ["list", "retrieve", "events"]

    throttle_classes = [ClickHouseBurstRateThrottle, ClickHouseSustainedRateThrottle]
    serializer_class = HeatmapsResponseSerializer
    # list() returns a bespoke aggregated payload, not a paged queryset — opt out of the
    # project-global LimitOffsetPagination so the schema doesn't advertise a Paginated
    # envelope or phantom limit/offset params the endpoint ignores.
    pagination_class = None

    @extend_schema(
        parameters=[HeatmapsRequestSerializer],
        responses={200: HeatmapsResponseSerializer},
        description="Aggregated heatmap interactions for a page. For type 'click'/'rageclick'/'mousemove' each result "
        "is a point with relative x, absolute client-y, and a count. For type 'scrolldepth' the response is "
        "scroll-depth buckets instead (cumulative reach down the page).",
    )
    def list(self, request: request.Request, *args: Any, **kwargs: Any) -> response.Response:
        request_serializer = HeatmapsRequestSerializer(data=request.query_params, context={"team": self.team})
        request_serializer.is_valid(raise_exception=True)

        aggregation = request_serializer.validated_data.pop("aggregation")
        hide_zero_coordinates = request_serializer.validated_data.pop("hide_zero_coordinates", True)
        limit = request_serializer.validated_data.pop("limit")
        offset = request_serializer.validated_data.pop("offset")
        if request_serializer.validated_data.get("cohort_ids") and not _heatmaps_cohort_filter_enabled(
            cast(User, request.user), self.team
        ):
            request_serializer.validated_data.pop("cohort_ids")
        placeholders = self._build_placeholders(request_serializer.validated_data)
        is_scrolldepth_query = placeholders.get("type", None) == Constant(value="scrolldepth")

        raw_query = SCROLL_DEPTH_QUERY if is_scrolldepth_query else DEFAULT_QUERY

        aggregation_count = self._choose_aggregation(aggregation, is_scrolldepth_query)
        exprs = self._predicate_expressions(placeholders)

        if hide_zero_coordinates and not is_scrolldepth_query:
            exprs.append(parse_expr("NOT (x = 0 AND y = 0)"))

        if request_serializer.validated_data.get("filter_test_accounts") is True:
            date_from: date = request_serializer.validated_data["date_from"]
            date_to: date | None = request_serializer.validated_data.get("date_to", None)
            exprs.append(self._build_test_accounts_filter(date_from, date_to))

        unbounded = limit == 0
        query_placeholders: dict[str, Expr] = {
            "aggregation_count": aggregation_count,
            "predicates": ast.And(exprs=exprs),
        }
        if not is_scrolldepth_query:
            # Unbounded fetches everything up to the hard cap; otherwise fetch one extra row so we can
            # report has_more without a second count query.
            fetch_limit = MAX_SELECT_HEATMAPS_LIMIT if unbounded else limit + 1
            query_placeholders["limit"] = Constant(value=fetch_limit)
            query_placeholders["offset"] = Constant(value=offset)

        stmt = parse_select(raw_query, query_placeholders)
        context = HogQLContext(team_id=self.team.pk, limit_top_select=False)
        tag_queries(product=ProductKey.HEATMAPS, feature=Feature.QUERY)
        results = execute_hogql_query(query=stmt, team=self.team, limit_context=LimitContext.HEATMAPS, context=context)

        if is_scrolldepth_query:
            return self._return_scroll_depth_response(results)

        has_more = not unbounded and len(results.results or []) > limit
        if not unbounded:
            results.results = (results.results or [])[:limit]

        fold = self._compute_fold_summary(exprs)
        return self._return_heatmap_coordinates_response(results, fold, has_more)

    def _compute_fold_summary(self, exprs: List[ast.Expr]) -> dict[str, Any]:  # noqa: UP006
        stmt = parse_select(FOLD_SUMMARY_QUERY, {"predicates": ast.And(exprs=exprs)})
        context = HogQLContext(team_id=self.team.pk, limit_top_select=False)
        result = execute_hogql_query(query=stmt, team=self.team, limit_context=LimitContext.HEATMAPS, context=context)
        row = result.results[0] if result.results else None
        return parse_fold_summary_row(row)

    def _choose_aggregation(self, aggregation, is_scrolldepth_query):
        aggregation_value = "count(*) as cnt" if aggregation == "total_count" else "count(distinct distinct_id) as cnt"
        if is_scrolldepth_query:
            aggregation_value = "count(*)" if aggregation == "total_count" else "count(distinct distinct_id)"
        aggregation_count = parse_expr(aggregation_value)
        return aggregation_count

    def _build_test_accounts_filter(self, date_from: date, date_to: date | None) -> ast.CompareOperation:
        # The heatmap predicate treats date_to as an inclusive day via `timestamp <= {date_to} + interval 1 day`.
        # HogQLFilters instead emits a strict `timestamp < date_to`, so when date_from and date_to land on the same
        # day this events subquery collapses to an impossible range and returns no sessions. Add a day so the
        # events subquery covers the same date window as the main heatmap query.
        events_date_to = (date_to or date.today()) + timedelta(days=1)
        events_select = replace_filters(
            parse_select(
                "SELECT distinct $session_id FROM events where notEmpty($session_id) AND {filters}", placeholders={}
            ),
            HogQLFilters(
                filterTestAccounts=True,
                dateRange=DateRange(
                    date_from=date_from.strftime("%Y-%m-%d"),
                    date_to=events_date_to.strftime("%Y-%m-%d"),
                ),
            ),
            self.team,
        )
        return ast.CompareOperation(
            op=ast.CompareOperationOp.In,
            left=ast.Field(chain=["session_id"]),
            right=events_select,
        )

    @staticmethod
    def _build_placeholders(validated_data: dict[str, Any]) -> dict[str, Expr]:
        placeholders: dict[str, Expr] = {}
        for key, value in validated_data.items():
            if key == "cohort_ids":
                if value:
                    placeholders[key] = ast.Array(exprs=[Constant(value=cid) for cid in value])
                continue
            placeholders[key] = Constant(value=value)
        placeholders.setdefault("date_to", Constant(value=date.today().strftime("%Y-%m-%d")))
        return placeholders

    @staticmethod
    def _predicate_expressions(placeholders: dict[str, Expr]) -> List[ast.Expr]:  # noqa: UP006
        predicate_expressions: list[ast.Expr] = []

        predicate_mapping: dict[str, str] = {
            # should always have values
            "date_from": "timestamp >= {date_from}",
            "type": "`type` = {type}",
            # optional
            "date_to": "timestamp <= {date_to} + interval 1 day",
            "viewport_width_min": "viewport_width >= round({viewport_width_min} / 16)",
            "viewport_width_max": "viewport_width <= round({viewport_width_max} / 16)",
            "url_exact": "trimRight(current_url, '/') = trimRight({url_exact}, '/')",
            "url_pattern": "match(current_url, {url_pattern})",
        }

        for predicate_key in placeholders.keys():
            # we e.g. don't want to add the filter_test_accounts predicate here
            if predicate_key in predicate_mapping:
                predicate_expressions.append(
                    parse_expr(predicate_mapping[predicate_key], {predicate_key: placeholders[predicate_key]})
                )

        cohort_ids_expr = placeholders.get("cohort_ids")
        if isinstance(cohort_ids_expr, ast.Array):
            for cohort_id_expr in cohort_ids_expr.exprs:
                predicate_expressions.append(
                    parse_expr(
                        "distinct_id IN (SELECT distinct_id FROM person_distinct_ids "
                        "WHERE person_id IN COHORT {cohort_id})",
                        {"cohort_id": cohort_id_expr},
                    )
                )

        if len(predicate_expressions) == 0:
            raise serializers.ValidationError("must always generate some filter conditions")

        return predicate_expressions

    @staticmethod
    def _return_heatmap_coordinates_response(
        query_response: HogQLQueryResponse, fold: dict[str, Any], has_more: bool
    ) -> response.Response:
        data = [
            {
                "pointer_target_fixed": item[0],
                "pointer_relative_x": item[1],
                "pointer_y": item[2],
                "count": item[3],
            }
            for item in query_response.results or []
        ]

        response_serializer = HeatmapsResponseSerializer(data={"results": data, "fold": fold, "has_more": has_more})
        response_serializer.is_valid(raise_exception=True)

        resp = response.Response(response_serializer.data, status=status.HTTP_200_OK)
        resp["Cache-Control"] = "max-age=30"
        resp["Vary"] = "Accept, Accept-Encoding, Query-String"
        return resp

    @staticmethod
    def _return_scroll_depth_response(query_response: HogQLQueryResponse) -> response.Response:
        data = [
            {
                "scroll_depth_bucket": item[0],
                "bucket_count": item[1],
                "cumulative_count": item[2],
            }
            for item in query_response.results or []
        ]

        response_serializer = HeatmapsScrollDepthResponseSerializer(data={"results": data})
        response_serializer.is_valid(raise_exception=True)

        resp = response.Response(response_serializer.data, status=status.HTTP_200_OK)
        resp["Cache-Control"] = "max-age=30"
        resp["Vary"] = "Accept, Accept-Encoding, Query-String"
        return resp

    @extend_schema(
        parameters=[HeatmapEventsRequestSerializer],
        responses={200: HeatmapEventsResponseSerializer},
        description="Drill into the individual session interactions behind one or more heatmap coordinates. "
        "Pass the 'points' you want to inspect (from the heatmaps list response) to get the underlying "
        "per-session events, so you can jump to the session recordings that produced a hotspot.",
    )
    @action(methods=["GET"], detail=False)
    def events(self, request: request.Request, *args: Any, **kwargs: Any) -> response.Response:
        request_serializer = HeatmapEventsRequestSerializer(data=request.query_params, context={"team": self.team})
        request_serializer.is_valid(raise_exception=True)

        validated_data = request_serializer.validated_data
        limit = validated_data.pop("limit")
        offset = validated_data.pop("offset")
        points = validated_data.pop("points")
        validated_data.pop("aggregation", None)
        validated_data.pop("hide_zero_coordinates", None)
        if validated_data.get("cohort_ids") and not _heatmaps_cohort_filter_enabled(
            cast(User, request.user), self.team
        ):
            validated_data.pop("cohort_ids")

        placeholders = self._build_placeholders(validated_data)

        exprs = self._predicate_expressions(placeholders)

        # Build OR condition for each exact point
        # Each point must match the exact aggregation grouping used in DEFAULT_QUERY
        point_conditions: list[ast.Expr] = []
        for point in points:
            x_rounded = round(float(point["x"]), 2)
            y_int = int(point["y"])
            target_fixed = bool(point.get("target_fixed", False))
            point_expr = ast.And(
                exprs=[
                    parse_expr("round((x / viewport_width), 2) = {x}", {"x": Constant(value=x_rounded)}),
                    parse_expr("y * scale_factor = {y}", {"y": Constant(value=y_int)}),
                    parse_expr("pointer_target_fixed = {fixed}", {"fixed": Constant(value=target_fixed)}),
                ]
            )
            point_conditions.append(point_expr)

        # Combine all point conditions with OR
        if len(point_conditions) == 1:
            exprs.append(point_conditions[0])
        else:
            exprs.append(ast.Or(exprs=point_conditions))

        if validated_data.get("filter_test_accounts") is True:
            date_from: date = validated_data["date_from"]
            date_to: date | None = validated_data.get("date_to", None)
            exprs.append(self._build_test_accounts_filter(date_from, date_to))

        # First get total count
        count_stmt = parse_select(
            "SELECT count() FROM heatmaps WHERE {predicates}",
            {"predicates": ast.And(exprs=exprs)},
        )
        context = HogQLContext(team_id=self.team.pk, limit_top_select=False)
        tag_queries(product=ProductKey.HEATMAPS, feature=Feature.QUERY)
        count_result = execute_hogql_query(
            query=count_stmt, team=self.team, limit_context=LimitContext.HEATMAPS, context=context
        )
        total_count = count_result.results[0][0] if count_result.results else 0

        # Then get events with limit and offset
        stmt = parse_select(
            EVENTS_QUERY,
            {"predicates": ast.And(exprs=exprs), "limit": Constant(value=limit), "offset": Constant(value=offset)},
        )
        results = execute_hogql_query(query=stmt, team=self.team, limit_context=LimitContext.HEATMAPS, context=context)

        data = [
            {
                "session_id": item[0] if item[0] else None,
                "distinct_id": item[1],
                "timestamp": item[2],
                "pointer_relative_x": item[3],
                "pointer_y": item[4],
                "current_url": item[5],
                "type": item[6],
            }
            for item in results.results or []
        ]

        response_serializer = HeatmapEventsResponseSerializer(
            data={"results": data, "total_count": total_count, "has_more": total_count > offset + limit}
        )
        response_serializer.is_valid(raise_exception=True)

        return response.Response(response_serializer.data, status=status.HTTP_200_OK)


class LegacyHeatmapViewSet(HeatmapViewSet):
    param_derived_from_user_current_team = "team_id"


# Heatmap Screenshot functionality


class HeatmapSnapshotMetadataSerializer(serializers.Serializer):
    width = serializers.IntegerField(help_text="Viewport width (CSS pixels) this screenshot was rendered at.")
    has_content = serializers.BooleanField(
        help_text="Whether the rendered image for this width is ready to fetch from the content endpoint."
    )


class HeatmapScreenshotResponseSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)
    snapshots = serializers.SerializerMethodField(
        help_text="Per-width render metadata. Fetch the actual image bytes for a width from the content endpoint."
    )

    class Meta:
        model = SavedHeatmap
        fields = [
            "id",
            "short_id",
            "name",
            "url",
            "data_url",
            "target_widths",
            "type",
            "status",
            "has_content",
            "snapshots",
            "deleted",
            "block_consent_modals",
            "created_by",
            "created_at",
            "updated_at",
            "exception",
        ]
        read_only_fields = [
            "id",
            "short_id",
            "status",
            "has_content",
            "created_by",
            "created_at",
            "updated_at",
            "exception",
        ]
        extra_kwargs = {
            "short_id": {"help_text": "Short, URL-safe identifier used as the lookup key for saved-heatmap routes."},
            "name": {"help_text": "Human-readable label for the saved heatmap."},
            "url": {"help_text": "The page URL this saved heatmap renders and overlays data on."},
            "data_url": {"help_text": "URL whose heatmap data is overlaid on the screenshot (defaults to 'url')."},
            "target_widths": {"help_text": "Viewport widths (CSS pixels) the screenshot is rendered at."},
            "type": {"help_text": "Render mode: 'screenshot', 'iframe', or 'recording'."},
            "status": {"help_text": "Screenshot generation status: 'processing', 'completed', or 'failed'."},
            "has_content": {"help_text": "Whether at least one rendered image is ready to fetch."},
            "deleted": {"help_text": "Soft-delete flag; deleted heatmaps are hidden from the list."},
            "block_consent_modals": {
                "help_text": "Whether the headless browser dismisses cookie/consent banners before capturing "
                "the screenshot. Only applies to 'screenshot' heatmaps."
            },
            "exception": {"help_text": "Error detail when screenshot generation failed, otherwise null."},
        }

    @extend_schema_field(HeatmapSnapshotMetadataSerializer(many=True))
    def get_snapshots(self, obj: SavedHeatmap) -> list[dict]:
        # Expose metadata of generated snapshots (width + readiness)
        snaps = []
        for snap in obj.snapshots.all():
            snaps.append(
                {
                    "width": snap.width,
                    "has_content": bool(snap.content or snap.content_location),
                }
            )
        snaps.sort(key=lambda s: s["width"])
        return snaps


class HeatmapScreenshotViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    # Screenshot exports render the heatmap in a headless browser, which authenticates
    # via an EXPORT_RENDERER JWT. Without opting into ExportRendererAuthentication here,
    # the exporter's `fetch(heatmap_url, Authorization: Bearer ...)` call in
    # frontend/src/exporter/exporterViewLogic.ts:50-52 gets rejected, the background
    # image never loads, and the exported PNG renders an `<img alt="Heatmap">` placeholder.
    authentication_classes = [ExportRendererAuthentication]
    scope_object = "heatmap"
    scope_object_read_actions = ["list", "retrieve", "content"]
    throttle_classes = [ClickHouseBurstRateThrottle, ClickHouseSustainedRateThrottle]
    serializer_class = HeatmapScreenshotResponseSerializer
    queryset = SavedHeatmap.objects.all()

    def safely_get_queryset(self, queryset):
        return queryset.filter(team=self.team)

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="width",
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Viewport width (CSS pixels) to fetch. Defaults to 1024. If no exact render exists for "
                "this width the closest available one is returned.",
            )
        ],
        responses={
            (200, "image/jpeg"): OpenApiTypes.BINARY,
            202: HeatmapScreenshotResponseSerializer,
        },
        description="Fetch the rendered screenshot image (JPEG bytes) for a saved heatmap at a given viewport width. "
        "Returns 202 with the saved-heatmap metadata while the screenshot is still being generated.",
    )
    @action(methods=["GET"], detail=True)
    def content(self, request: request.Request, *args: Any, **kwargs: Any) -> HttpResponse:
        screenshot = self.get_object()

        def _finish(resp: HttpResponse, outcome: str, **attrs: Any) -> HttpResponse:
            HEATMAP_CONTENT_REQUESTS.labels(outcome=outcome).inc()
            if outcome in ("not_found", "bad_request", "not_implemented"):
                log = logger.warning if outcome in ("bad_request", "not_implemented") else logger.info
                log(
                    "heatmap_screenshot.content_request",
                    screenshot_id=str(screenshot.id),
                    team_id=screenshot.team_id,
                    outcome=outcome,
                    status_code=resp.status_code,
                    **attrs,
                )
            return resp

        if screenshot.deleted:
            return _finish(response.Response(status=status.HTTP_404_NOT_FOUND), "not_found")

        try:
            requested_width = int(request.query_params.get("width", 1024))
        except (ValueError, TypeError):
            return _finish(
                response.Response(
                    {"error": "Invalid width parameter, must be an integer"}, status=status.HTTP_400_BAD_REQUEST
                ),
                "bad_request",
            )

        snapshot = screenshot.snapshots.filter(width=requested_width).first()

        if not snapshot:
            all_snaps = list(screenshot.snapshots.all())
            if all_snaps:
                snapshot = min(all_snaps, key=lambda s: abs(s.width - requested_width))

        if not snapshot:
            response_serializer = HeatmapScreenshotResponseSerializer(screenshot)
            return _finish(
                response.Response(response_serializer.data, status=status.HTTP_202_ACCEPTED),
                "generating",
            )

        if snapshot.content:
            http_response = HttpResponse(snapshot.content, content_type="image/jpeg")
            http_response["Content-Disposition"] = (
                f'attachment; filename="screenshot-{screenshot.id}-{snapshot.width}.jpg"'
            )
            return _finish(http_response, "served")
        elif snapshot.content_location:
            response_serializer = HeatmapScreenshotResponseSerializer(screenshot)
            return _finish(
                response.Response(
                    {**response_serializer.data, "error": "Content location not implemented yet"},
                    status=status.HTTP_501_NOT_IMPLEMENTED,
                ),
                "not_implemented",
                requested_width=requested_width,
                served_width=snapshot.width,
            )
        else:
            response_serializer = HeatmapScreenshotResponseSerializer(screenshot)
            return _finish(
                response.Response(response_serializer.data, status=status.HTTP_202_ACCEPTED),
                "generating",
            )


_URL_PATTERN_CHARS = set("*+?^${}()|[]\\")


class SavedHeatmapRequestSerializer(serializers.ModelSerializer):
    widths = serializers.ListField(
        child=serializers.IntegerField(min_value=100, max_value=3000),
        required=False,
        allow_empty=False,
        max_length=MAX_TARGET_WIDTHS,
        help_text=(
            "Viewport widths (px, 100-3000) to render the heatmap screenshot at — one render per width. "
            f"Defaults to {DEFAULT_TARGET_WIDTHS} when omitted. At most {MAX_TARGET_WIDTHS} widths."
        ),
    )

    def validate_url(self, value: str) -> str:
        if any(c in _URL_PATTERN_CHARS for c in value):
            raise serializers.ValidationError("Wildcards are not allowed in the page URL.")
        ok, err = is_url_allowed(value)
        if not ok:
            raise serializers.ValidationError(err or "URL not allowed")
        return value

    class Meta:
        model = SavedHeatmap
        fields = ["name", "url", "data_url", "widths", "type", "deleted", "block_consent_modals"]
        extra_kwargs = {
            "name": {"required": False, "allow_null": True, "help_text": "Human-readable label for the saved heatmap."},
            "url": {
                "required": True,
                "help_text": "Exact page URL to render and overlay heatmap data on. Wildcards are not allowed.",
            },
            "data_url": {
                "required": False,
                "allow_null": True,
                "help_text": "URL whose heatmap data is overlaid on the screenshot. Defaults to 'url' when omitted.",
            },
            "type": {
                "required": False,
                "default": SavedHeatmap.Type.SCREENSHOT,
                "help_text": "Render mode: 'screenshot' (renders the page headlessly, default), 'iframe', "
                "or 'recording'. Only 'screenshot' generates image bytes.",
            },
            "deleted": {"required": False, "help_text": "Set true to soft-delete the saved heatmap."},
            "block_consent_modals": {
                "required": False,
                "help_text": "When true, ask the headless browser to dismiss cookie/consent banners before "
                "capturing the screenshot. Off by default: the blocker can stall the render on some sites and "
                "time out. Only applies to 'screenshot' heatmaps.",
            },
        }


class SavedHeatmapListQuerySerializer(serializers.Serializer):
    type = serializers.CharField(
        required=False, help_text="Filter by render mode: 'screenshot', 'iframe', or 'recording'."
    )
    status = serializers.CharField(
        required=False, help_text="Filter by generation status: 'processing', 'completed', or 'failed'."
    )
    search = serializers.CharField(required=False, help_text="Case-insensitive substring match on URL or name.")
    created_by = serializers.IntegerField(required=False, help_text="Filter by the creating user's ID.")
    order = serializers.CharField(
        required=False, help_text="Field to order by, e.g. '-updated_at' (default) or 'created_at'."
    )
    limit = serializers.IntegerField(required=False, default=100, help_text="Maximum saved heatmaps to return.")
    offset = serializers.IntegerField(required=False, default=0, help_text="Number to skip, for pagination.")


class SavedHeatmapListResponseSerializer(serializers.Serializer):
    results = HeatmapScreenshotResponseSerializer(many=True)
    count = serializers.IntegerField(help_text="Total number of saved heatmaps matching the filters.")


class SavedHeatmapViewSet(TeamAndOrgViewSetMixin, ForbidDestroyModel, viewsets.GenericViewSet):
    scope_object = "heatmap"
    throttle_classes = [ClickHouseBurstRateThrottle, ClickHouseSustainedRateThrottle]
    serializer_class = HeatmapScreenshotResponseSerializer
    queryset = SavedHeatmap.objects.all()
    lookup_field = "short_id"
    # list() returns its own {results, count} shape (paginated via the query serializer), so
    # opt out of the project-global LimitOffsetPagination to avoid a double-wrapped schema.
    pagination_class = None

    def get_throttles(self):
        if self.action == "create":
            # More restrictive rate limiting for expensive screenshot generation
            return [AIBurstRateThrottle(), AISustainedRateThrottle()]
        return super().get_throttles()

    def safely_get_queryset(self, queryset):
        return queryset.filter(team=self.team)

    @extend_schema(
        parameters=[SavedHeatmapListQuerySerializer],
        responses={200: SavedHeatmapListResponseSerializer},
        description="List saved heatmaps for the project. A saved heatmap pins a page URL and a set of viewport "
        "widths, and (for type 'screenshot') renders the page so heatmap data can be overlaid on it.",
    )
    def list(self, request: request.Request, *args: Any, **kwargs: Any) -> response.Response:
        query_serializer = SavedHeatmapListQuerySerializer(data=request.query_params)
        query_serializer.is_valid(raise_exception=True)
        params = query_serializer.validated_data

        qs = (
            self.safely_get_queryset(self.get_queryset())
            .filter(deleted=False)
            .select_related("created_by")
            .order_by("-updated_at")
        )

        if params.get("type"):
            qs = qs.filter(type=params["type"])
        if params.get("status"):
            qs = qs.filter(status=params["status"])
        if params.get("search"):
            qs = qs.filter(Q(url__icontains=params["search"]) | Q(name__icontains=params["search"]))
        if params.get("created_by"):
            qs = qs.filter(created_by_id=params["created_by"])
        if params.get("order"):
            try:
                qs = qs.order_by(params["order"])
            except FieldError:
                return response.Response(
                    {"error": f"Invalid order field: {params['order']}"}, status=status.HTTP_400_BAD_REQUEST
                )

        # Clamp at the boundary rather than via serializer min/max so the OpenAPI
        # contract (and generated clients) stay unchanged while the page stays bounded.
        limit = max(1, min(params["limit"], 500))
        offset = max(0, params["offset"])
        count = qs.count()
        results = qs[offset : offset + limit]

        data = HeatmapScreenshotResponseSerializer(results, many=True).data
        return response.Response({"results": data, "count": count}, status=status.HTTP_200_OK)

    @extend_schema(
        request=SavedHeatmapRequestSerializer,
        responses={201: HeatmapScreenshotResponseSerializer},
        description="Create a saved heatmap for a page URL. For type 'screenshot' (the default) this enqueues a "
        "headless render of the page at each target width; poll the saved heatmap or its content endpoint until "
        "status is 'completed'. Provide 'widths' to control which viewport widths are rendered.",
    )
    def create(self, request: request.Request, *args: Any, **kwargs: Any) -> response.Response:
        serializer = SavedHeatmapRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        name = serializer.validated_data.get("name")
        url = serializer.validated_data["url"]
        data_url = serializer.validated_data.get("data_url") or url
        widths = serializer.validated_data.get("widths", DEFAULT_TARGET_WIDTHS)
        heatmap_type = serializer.validated_data.get("type", SavedHeatmap.Type.SCREENSHOT)
        block_consent_modals = serializer.validated_data.get("block_consent_modals", False)

        screenshot = SavedHeatmap.objects.create(
            team=self.team,
            name=name,
            url=url,
            data_url=data_url,
            target_widths=widths,
            type=heatmap_type,
            block_consent_modals=block_consent_modals,
            created_by=cast(User, request.user),
            status=SavedHeatmap.Status.PROCESSING
            if heatmap_type == SavedHeatmap.Type.SCREENSHOT
            else SavedHeatmap.Status.COMPLETED,
        )

        log_activity(
            organization_id=cast(User, request.user).current_organization_id
            if hasattr(request.user, "current_organization_id")
            else None,
            team_id=self.team.id,
            user=cast(User, request.user),
            item_id=screenshot.short_id or str(screenshot.id),
            scope="Heatmap",
            activity="created",
            detail=Detail(name=screenshot.name or screenshot.url, short_id=screenshot.short_id, type=screenshot.type),
            was_impersonated=is_impersonated(request),
        )

        if heatmap_type == SavedHeatmap.Type.SCREENSHOT:
            generate_heatmap_screenshot.delay(screenshot.id)

        return response.Response(HeatmapScreenshotResponseSerializer(screenshot).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        responses={200: HeatmapScreenshotResponseSerializer},
        description="Get a single saved heatmap by its short_id, including per-width render status.",
    )
    def retrieve(self, request: request.Request, *args: Any, **kwargs: Any) -> response.Response:
        obj = self.get_object()

        if (
            obj.type == SavedHeatmap.Type.SCREENSHOT
            and obj.status == SavedHeatmap.Status.PROCESSING
            and obj.updated_at < datetime.now(tz=obj.updated_at.tzinfo) - STALE_PROCESSING_THRESHOLD
        ):
            self._regenerate(obj)

        return response.Response(HeatmapScreenshotResponseSerializer(obj).data, status=status.HTTP_200_OK)

    @extend_schema(
        request=None,
        responses={200: HeatmapScreenshotResponseSerializer, 400: OpenApiResponse(description="Not a screenshot")},
        description="Re-run screenshot generation for a saved heatmap of type 'screenshot'. Clears existing renders "
        "and re-renders at every target width; status returns to 'processing'.",
    )
    @action(methods=["POST"], detail=True, required_scopes=["heatmap:write"])
    def regenerate(self, request: request.Request, *args: Any, **kwargs: Any) -> response.Response:
        obj = self.get_object()
        if obj.type != SavedHeatmap.Type.SCREENSHOT:
            return response.Response(
                {"error": "Only screenshot heatmaps can be regenerated"}, status=status.HTTP_400_BAD_REQUEST
            )

        self._regenerate(obj)
        return response.Response(HeatmapScreenshotResponseSerializer(obj).data, status=status.HTTP_200_OK)

    def _regenerate(self, obj: SavedHeatmap) -> None:
        obj.status = SavedHeatmap.Status.PROCESSING
        obj.exception = None
        obj.save(update_fields=["status", "exception", "updated_at"])
        HeatmapSnapshot.objects.filter(heatmap=obj).delete()
        generate_heatmap_screenshot.delay(obj.id)

    @extend_schema(
        request=SavedHeatmapRequestSerializer,
        responses={200: HeatmapScreenshotResponseSerializer},
        description="Update a saved heatmap (e.g. rename, change widths, or soft-delete via 'deleted'). Changing the "
        "URL of a 'screenshot' heatmap triggers a re-render.",
    )
    def partial_update(self, request: request.Request, *args: Any, **kwargs: Any) -> response.Response:
        obj = self.get_object()
        old_url = obj.url
        old_block_consent_modals = obj.block_consent_modals
        serializer = SavedHeatmapRequestSerializer(obj, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        updated = serializer.save()

        render_input_changed = updated.url != old_url or updated.block_consent_modals != old_block_consent_modals
        if updated.type == SavedHeatmap.Type.SCREENSHOT and render_input_changed:
            self._regenerate(updated)

        log_activity(
            organization_id=cast(User, request.user).current_organization_id
            if hasattr(request.user, "current_organization_id")
            else None,
            team_id=self.team.id,
            user=cast(User, request.user),
            item_id=updated.short_id or str(updated.id),
            scope="Heatmap",
            activity="updated",
            detail=Detail(name=updated.name or updated.url, short_id=updated.short_id, type=updated.type),
            was_impersonated=is_impersonated(request),
        )
        return response.Response(HeatmapScreenshotResponseSerializer(updated).data, status=status.HTTP_200_OK)
