import re
import textwrap
from collections.abc import Collection, Sequence
from datetime import timedelta
from functools import cached_property
from typing import Any, cast
from uuid import UUID

from django.db import transaction
from django.db.models import Exists, OuterRef
from django.utils import timezone

import structlog

from posthog.hogql.escape_sql import escape_hogql_identifier

from posthog.helpers.dashboard_templates import create_from_template
from posthog.models.group_type_mapping import get_group_types_for_project
from posthog.models.user import User

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.dashboards.backend.facade.api import unknown_dashboard_ids
from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_templates import DashboardTemplate
from products.replay_vision.backend.models.replay_observation import ObservationStatus, ReplayObservation
from products.replay_vision.backend.models.replay_scanner import ReplayScanner, ScannerType
from products.replay_vision.backend.queries.scanner_candidate_query import OBSERVATION_EVENT_NAME

logger = structlog.get_logger(__name__)

# Enough rows that every tile renders a real chart on the day the dashboard is created.
DASHBOARD_SUGGESTION_MIN_OBSERVATIONS = 20

DASHBOARD_NAME_PREFIX = "Replay Vision: "
DASHBOARD_DAYS = 30
DASHBOARD_DATE_FROM = f"-{DASHBOARD_DAYS}d"

_TILE_HEIGHT = 5
# How far back "first seen" looks for a freeform category, so the tile does not scan the scanner's whole history.
_FREEFORM_FIRST_SEEN_LOOKBACK = "1 YEAR"

# `{scanner_id}` is substituted by `_sql_node` rather than bound through HogQL `values`, because `values` turns
# `{filters}` into a HogVM global and the dashboard date filter stops applying. The id is a server UUID, so it is safe
# to inline.
_SCANNER_MATCH = f"event = '{OBSERVATION_EVENT_NAME}' AND properties.scanner_id = '{{scanner_id}}'"
_SCANNER_WHERE = f"{_SCANNER_MATCH} AND {{filters}}"
_YES_SQL = "properties.scanner_output_verdict = 'yes'"
_FREEFORM_EXPR = "JSONExtract(ifNull(properties.scanner_output_tags_freeform, '[]'), 'Array(String)')"
_TAGS_EXPR = (
    f"arrayConcat(JSONExtract(ifNull(properties.scanner_output_tags, '[]'), 'Array(String)'), {_FREEFORM_EXPR})"
)


def live_dashboard_ids(team_id: int, scanners: Sequence[ReplayScanner]) -> dict[UUID, int]:
    """Linked dashboards that still exist, by scanner. A scanner whose dashboard the user deleted is left out."""
    linked = {scanner.id: cast(int, scanner.dashboard_id) for scanner in scanners if scanner.dashboard_id is not None}
    if not linked:
        return {}
    gone = set(unknown_dashboard_ids(list(linked.values()), team_id=team_id))
    return {scanner_id: dashboard_id for scanner_id, dashboard_id in linked.items() if dashboard_id not in gone}


def scanners_ready_for_dashboard(team_id: int, scanner_ids: Collection[UUID]) -> set[UUID]:
    """The scanners with at least `DASHBOARD_SUGGESTION_MIN_OBSERVATIONS` succeeded observations inside the
    dashboard's default date range, so the dashboard the offer creates opens with data in it."""
    if not scanner_ids:
        return set()
    window_start = timezone.now() - timedelta(days=DASHBOARD_DAYS)
    # An offset probe stops at the threshold row, so a scanner with millions of observations costs the same as one with 20.
    threshold_row = (
        ReplayObservation.objects.filter(
            scanner_id=OuterRef("pk"), status=ObservationStatus.SUCCEEDED, completed_at__gte=window_start
        )
        .order_by()
        .values("pk")[DASHBOARD_SUGGESTION_MIN_OBSERVATIONS - 1 : DASHBOARD_SUGGESTION_MIN_OBSERVATIONS]
    )
    return set(
        ReplayScanner.objects.filter(team_id=team_id, id__in=scanner_ids)
        .filter(Exists(threshold_row))
        .values_list("id", flat=True)
    )


def create_scanner_dashboard(scanner: ReplayScanner, user: User) -> tuple[Dashboard, bool]:
    """Create the scanner's dashboard and link it, or return the live one already linked.

    Returns (dashboard, created). The scanner row lock serializes two clicks on the same scanner,
    so that one scanner never gets two dashboards.
    """
    # Built before the lock because it reads group types, which can call personhog.
    template = build_scanner_dashboard_template(scanner)
    with transaction.atomic():
        locked = ReplayScanner.objects.select_for_update().get(pk=scanner.pk, team_id=scanner.team_id)
        if locked.dashboard_id is not None:
            # The default manager hides soft-deleted dashboards, so a deleted one falls through to a new dashboard.
            existing = Dashboard.objects.filter(team_id=locked.team_id, pk=locked.dashboard_id).first()
            if existing is not None:
                return existing, False
        dashboard = Dashboard.objects.create(
            team_id=locked.team_id,
            name=_dashboard_name(locked),
            created_by=user,
            creation_mode=Dashboard.CreationMode.TEMPLATE,
        )
        create_from_template(
            dashboard, template, user, user_access_control=UserAccessControl(user=user, team=scanner.team)
        )
        # A queryset update so that linking a dashboard is not logged or treated as a scanner config edit.
        ReplayScanner.objects.filter(pk=locked.pk).update(dashboard_id=dashboard.id)
    scanner.dashboard_id = dashboard.id
    return dashboard, True


def _dashboard_name(scanner: ReplayScanner) -> str:
    return f"{DASHBOARD_NAME_PREFIX}{scanner.name}"[:400]


def build_scanner_dashboard_template(scanner: ReplayScanner) -> DashboardTemplate:
    builder = _TileBuilder(scanner)
    builder.add_shared_tiles()
    builder.add_type_tiles()
    builder.add_latest_sessions_tile()
    return DashboardTemplate(
        template_name=_dashboard_name(scanner),
        dashboard_description=(
            f"What the '{scanner.name}' scanner finds in your session recordings, and who it affects. "
            "Charts count observations on the day the scanner ran, not the day of the recording."
        ),
        dashboard_filters={"date_from": DASHBOARD_DATE_FROM},
        tiles=builder.tiles,
        tags=["replay-vision"],
    )


class _TileBuilder:
    def __init__(self, scanner: ReplayScanner) -> None:
        self.scanner = scanner
        self.scanner_id = str(scanner.id)
        self.is_monitor = scanner.scanner_type == ScannerType.MONITOR
        self.tiles: list[dict[str, Any]] = []
        self._x = 0
        self._y = 0

    # Shared across every scanner type.

    def add_shared_tiles(self) -> None:
        hit_filter = self._hit_filter()
        people_name = "People with a yes verdict" if self.is_monitor else "People observed"
        self._trend(
            people_name,
            "Distinct people in recordings this scanner matched, per week.",
            series=[
                self._series(
                    people_name,
                    math="hogql",
                    math_hogql="count(DISTINCT properties.recording_distinct_id)",
                    extra=hit_filter,
                )
            ],
            display="ActionsBar",
        )
        if self._primary_group_type is None:
            return
        index, plural = self._primary_group_type
        self._trend(
            f"{plural.capitalize()} affected",
            f"Distinct {plural} with at least one matching recording, per week.",
            series=[
                self._series(
                    f"{plural.capitalize()} affected",
                    math="unique_group",
                    math_group_type_index=index,
                    extra=hit_filter,
                )
            ],
            display="ActionsBar",
        )
        self._account_table(
            f"Top {plural}",
            f"The {plural} with the most matching recordings.",
            columns={"recordings": "count()", "people": "count(DISTINCT properties.recording_distinct_id)"},
            sort="recordings DESC",
            where=f" AND {_YES_SQL}" if self.is_monitor else "",
        )

    def add_latest_sessions_tile(self) -> None:
        scanner_type = ScannerType(self.scanner.scanner_type)
        name, description, order = "Latest matching sessions", "The newest observations", "timestamp DESC"
        detail = "properties.scanner_output_reasoning"
        if scanner_type == ScannerType.CLASSIFIER:
            detail = f"arrayStringConcat({_TAGS_EXPR}, ', ')"
        elif scanner_type in (ScannerType.SUMMARIZER, ScannerType.EXPERIMENT):
            name, description = "Most notable sessions", "The most notable observations"
            order = "toFloat(properties.scanner_output_notability) DESC NULLS LAST"
            detail = "properties.scanner_output_title"
        score_column = (
            "toFloat(properties.scanner_output_score) AS score, " if scanner_type == ScannerType.SCORER else ""
        )
        where = f" AND {_YES_SQL}" if self.is_monitor else ""
        self._sql_table(
            name,
            f"{description}, with a link to each recording.",
            f"""
            SELECT timestamp AS observed_at, {score_column}{detail} AS finding,
                properties.recording_distinct_id AS person, recordingButton(properties.session_id) AS recording
            FROM events
            WHERE {_SCANNER_WHERE}{where}
            ORDER BY {order}
            LIMIT 50
            """,
            width=12,
        )

    # Per scanner type.

    def add_type_tiles(self) -> None:
        {
            ScannerType.MONITOR: self._monitor_tiles,
            ScannerType.CLASSIFIER: self._classifier_tiles,
            ScannerType.SCORER: self._scorer_tiles,
            ScannerType.SUMMARIZER: self._summarizer_tiles,
            ScannerType.EXPERIMENT: self._experiment_tiles,
        }[ScannerType(self.scanner.scanner_type)]()

    def _monitor_tiles(self) -> None:
        self._trend(
            "Yes rate",
            "Share of observed recordings with a yes verdict.",
            series=[
                self._series("Yes verdicts", extra=self._hit_filter()),
                self._series("All observations"),
            ],
            trends_filter={"formulaNodes": [{"formula": "A / B * 100", "custom_name": "Yes rate (%)"}]},
        )
        self._sql_chart(
            "Confidence of yes verdicts",
            "How sure the scanner was when it said yes. Many low-confidence verdicts can mean the prompt is vague.",
            f"""
            SELECT round(toFloat(properties.scanner_output_confidence), 1) AS confidence, count() AS verdicts
            FROM events
            WHERE {_SCANNER_WHERE} AND {_YES_SQL}
              AND properties.scanner_output_confidence IS NOT NULL
            GROUP BY confidence
            ORDER BY confidence
            """,
            x="confidence",
            y="verdicts",
        )

    def _classifier_tiles(self) -> None:
        self._trend(
            "Category share",
            "Each category's share of observations over time.",
            series=[self._series("Observations")],
            breakdown={"breakdown": f"arrayJoin({_TAGS_EXPR})", "breakdown_type": "hogql"},
            display="ActionsAreaGraph",
            trends_filter={"showPercentStackView": True},
        )
        self._sql_table(
            "Categories that appear together",
            "Pairs of categories assigned to the same recording.",
            f"""
            SELECT pair.1 AS first_category, pair.2 AS second_category, count() AS recordings
            FROM (SELECT {_TAGS_EXPR} AS tags FROM events WHERE {_SCANNER_WHERE})
            ARRAY JOIN arrayFilter(p -> p.1 < p.2, arrayFlatten(arrayMap(a -> arrayMap(b -> (a, b), tags), tags))) AS pair
            GROUP BY first_category, second_category
            ORDER BY recordings DESC
            LIMIT 20
            """,
        )
        # First seen looks back past the range, so a category the scanner has used for months sorts below one
        # it started using this week.
        self._sql_table(
            "Freeform categories",
            "Categories the scanner suggested outside your list, newest first. "
            "Frequent ones are candidates to add to the scanner.",
            f"""
            SELECT in_range.category AS category, in_range.recordings AS recordings, all_time.first_seen AS first_seen
            FROM (
                SELECT tag AS category, count() AS recordings
                FROM (SELECT {_FREEFORM_EXPR} AS tags FROM events WHERE {_SCANNER_WHERE})
                ARRAY JOIN tags AS tag
                GROUP BY category
            ) AS in_range
            LEFT JOIN (
                SELECT tag AS category, min(timestamp) AS first_seen
                FROM (
                    SELECT {_FREEFORM_EXPR} AS tags, timestamp
                    FROM events
                    WHERE {_SCANNER_MATCH} AND timestamp > now() - INTERVAL {_FREEFORM_FIRST_SEEN_LOOKBACK}
                )
                ARRAY JOIN tags AS tag
                GROUP BY category
            ) AS all_time ON in_range.category = all_time.category
            ORDER BY first_seen DESC
            LIMIT 20
            """,
        )

    def _scorer_tiles(self) -> None:
        self._sql_chart(
            "Score distribution",
            "How many recordings received each score.",
            f"""
            SELECT round(toFloat(properties.scanner_output_score), 1) AS score, count() AS recordings
            FROM events
            WHERE {_SCANNER_WHERE} AND properties.scanner_output_score IS NOT NULL
            GROUP BY score
            ORDER BY score
            """,
            x="score",
            y="recordings",
        )
        self._trend(
            "Score percentiles",
            "The 10th, 50th and 90th percentile score per week. The average hides the tail, these do not.",
            series=[
                self._series(
                    "10th percentile",
                    math="hogql",
                    math_hogql="quantile(0.1)(toFloat(properties.scanner_output_score))",
                ),
                self._series("Median", math="median", math_property="scanner_output_score"),
                self._series("90th percentile", math="p90", math_property="scanner_output_score"),
            ],
        )
        if self._primary_group_type is None:
            return
        plural = self._primary_group_type[1]
        self._account_table(
            f"Lowest scoring {plural}",
            f"The {plural} with the lowest average score, among those with at least 3 scored recordings.",
            columns={
                "average_score": "round(avg(toFloat(properties.scanner_output_score)), 2)",
                "recordings": "count()",
            },
            sort="average_score ASC",
            having="HAVING recordings >= 3",
        )

    def _summarizer_tiles(self) -> None:
        self._notability_distribution()
        self._trend(
            "Average chapters per recording",
            "A rough measure of how much happens in each session.",
            series=[self._series("Chapters", math="avg", math_property="scanner_output_chapter_count")],
        )

    def _experiment_tiles(self) -> None:
        self._trend(
            "Observations by variant",
            "Observed recordings per experiment variant, per week.",
            series=[self._series("Observations")],
            breakdown={"breakdown": "experiment_variant", "breakdown_type": "event"},
            display="ActionsBar",
        )
        self._trend(
            "Average notability by variant",
            "How notable the scanner found each variant's sessions over the date range. Higher means more unusual "
            "behavior.",
            series=[self._series("Notability", math="avg", math_property="scanner_output_notability")],
            breakdown={"breakdown": "experiment_variant", "breakdown_type": "event"},
            # One bar per variant: stacked weekly bars would add the variants' averages together.
            display="ActionsBarValue",
        )
        self._notability_distribution()

    def _notability_distribution(self) -> None:
        self._sql_chart(
            "Notability distribution",
            "How notable the scanner found each session, from 0 (routine) to 1 (unusual).",
            f"""
            SELECT round(toFloat(properties.scanner_output_notability), 1) AS notability, count() AS recordings
            FROM events
            WHERE {_SCANNER_WHERE} AND properties.scanner_output_notability IS NOT NULL
            GROUP BY notability
            ORDER BY notability
            """,
            x="notability",
            y="recordings",
        )

    # Helpers.

    def _hit_filter(self) -> list[dict[str, Any]]:
        if not self.is_monitor:
            return []
        return [{"type": "event", "key": "scanner_output_verdict", "operator": "exact", "value": "yes"}]

    @cached_property
    def _primary_group_type(self) -> tuple[int, str] | None:
        try:
            group_types = get_group_types_for_project(
                self.scanner.team.project_id, caller_tag="replay_vision/scanner_dashboard"
            )
        except Exception:
            # The account tiles are optional, so a failed lookup builds the dashboard without them.
            logger.warning("replay_vision.scanner_dashboard.group_types_lookup_failed", scanner_id=self.scanner_id)
            return None
        if not group_types:
            return None
        first = min(group_types, key=lambda mapping: mapping["group_type_index"])
        plural = str(first.get("name_plural") or _pluralize(first["group_type"])).lower()
        # The plural is user-edited and becomes a column alias, so keep only characters an identifier allows.
        return first["group_type_index"], re.sub(r"[^\w ]", "", plural).strip() or "accounts"

    def _series(self, name: str, *, extra: list[dict[str, Any]] | None = None, **math: Any) -> dict[str, Any]:
        return {
            "kind": "EventsNode",
            "event": OBSERVATION_EVENT_NAME,
            "name": name,
            "custom_name": name,
            "math": math.pop("math", "total"),
            **math,
            "properties": [
                {"type": "event", "key": "scanner_id", "operator": "exact", "value": self.scanner_id},
                *(extra or []),
            ],
        }

    def _trend(
        self,
        name: str,
        description: str,
        *,
        series: list[dict[str, Any]],
        display: str = "ActionsLineGraph",
        breakdown: dict[str, Any] | None = None,
        trends_filter: dict[str, Any] | None = None,
    ) -> None:
        source: dict[str, Any] = {
            "kind": "TrendsQuery",
            "series": series,
            # Weekly, because a scanner samples a few recordings a day and daily buckets are mostly noise.
            "interval": "week",
            "dateRange": {"date_from": DASHBOARD_DATE_FROM},
            "trendsFilter": {"display": display, **(trends_filter or {})},
        }
        if breakdown:
            source["breakdownFilter"] = breakdown
        self._add(name, description, {"kind": "InsightVizNode", "source": source})

    def _sql_chart(self, name: str, description: str, query: str, *, x: str, y: str) -> None:
        self._add(
            name,
            description,
            self._sql_node(
                query,
                display="ActionsBar",
                chartSettings={"xAxis": {"column": x}, "yAxis": [{"column": y}]},
            ),
        )

    def _sql_table(self, name: str, description: str, query: str, *, width: int = 6) -> None:
        self._add(name, description, self._sql_node(query), width=width)

    def _account_table(
        self,
        name: str,
        description: str,
        *,
        columns: dict[str, str],
        sort: str,
        where: str = "",
        having: str = "",
    ) -> None:
        """A table of the primary group type's accounts, labeled with each group's name when it has one.

        `columns` maps output column names to aggregate expressions, and `sort` is one of those names plus a direction.
        """
        assert self._primary_group_type is not None
        index, plural = self._primary_group_type
        aggregates = ", ".join(f"{expression} AS {column}" for column, expression in columns.items())
        # Rank on the events alone, then look up names for the 20 rows shown rather than joining every group.
        self._sql_table(
            name,
            description,
            f"""
            WITH ranked AS (
                SELECT $group_{index} AS group_key, {aggregates}
                FROM events
                WHERE {_SCANNER_WHERE}{where} AND notEmpty($group_{index})
                GROUP BY group_key
                {having}
                ORDER BY {sort}
                LIMIT 20
            )
            SELECT ifNull(nullIf(toString(named.name), ''), ranked.group_key) AS {escape_hogql_identifier(plural)},
                {", ".join(f"ranked.{column} AS {column}" for column in columns)}
            FROM ranked
            LEFT JOIN (
                SELECT key, properties.name AS name
                FROM groups
                WHERE index = {index} AND key IN (SELECT group_key FROM ranked)
            ) AS named ON named.key = ranked.group_key
            ORDER BY {sort}
            """,
        )

    def _sql_node(self, query: str, **settings: Any) -> dict[str, Any]:
        return {
            "kind": "DataVisualizationNode",
            "source": {
                "kind": "HogQLQuery",
                "query": textwrap.dedent(query).strip().replace("{scanner_id}", self.scanner_id),
                "filters": {"dateRange": {"date_from": DASHBOARD_DATE_FROM}},
            },
            **settings,
        }

    def _add(self, name: str, description: str, query: dict[str, Any], *, width: int = 6) -> None:
        # Explicit layouts keep the builder's order: tiles fill two columns, and a full-width tile starts a new row.
        if self._x + width > 12:
            self._x, self._y = 0, self._y + _TILE_HEIGHT
        self.tiles.append(
            {
                "type": "INSIGHT",
                "name": name,
                "description": description,
                "query": query,
                "layouts": {"sm": {"x": self._x, "y": self._y, "w": width, "h": _TILE_HEIGHT}},
                "color": None,
            }
        )
        self._x += width


def _pluralize(noun: str) -> str:
    if noun.endswith("y") and not noun.endswith(("ay", "ey", "oy", "uy")):
        return f"{noun[:-1]}ies"
    return f"{noun}es" if noun.endswith(("s", "x", "ch", "sh")) else f"{noun}s"
