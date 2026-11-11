from dataclasses import dataclass
from datetime import UTC, datetime

from posthog.schema import ActionsNode, Breakdown, ExperimentEventExposureConfig, MultipleVariantHandling

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr

from posthog.dataclasses import frozen
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models.team.team import Team

from products.experiments.backend.hogql_queries.cuped_config import CupedQueryConfig


@dataclass(frozen=True)
class ExperimentQueryContext:
    """Experiment-level invariants shared across query construction.

    The query builder and the modules it delegates to, such as the exposure
    query builder, take this one object instead of each parameter.
    """

    team: Team
    feature_flag_key: str
    exposure_config: ExperimentEventExposureConfig | ActionsNode
    filter_test_accounts: bool
    multiple_variant_handling: MultipleVariantHandling
    variants: tuple[str, ...]
    date_range_query: QueryDateRange
    entity_key: str
    breakdowns: tuple[Breakdown, ...]
    only_count_matured_users: bool
    cuped_config: CupedQueryConfig
    # Whether the preaggregated tables follow person merges for a person-aggregated experiment: a
    # build stores the distinct_id of each row, and a read resolves each row to its current person.
    # The caller evaluates it once per query, so that every build and read of the query agree.
    resolve_precomputed_persons: bool
    # When set, an entity only counts as exposed once it emits this event at/after its first
    # default exposure event, and that activation event's timestamp becomes the exposure time.
    activation_config: ExperimentEventExposureConfig | ActionsNode | None = None
    # Whether an exposure on $feature_flag_called also reads its $experiment_exposure copy. It is
    # False for a metric that reads $feature_flag_called: the call and its copy share a timestamp,
    # so one of them would be the exposure and the other a conversion.
    read_exposure_copies: bool = True

    def precomputed_entity_id_sql(self) -> str:
        """
        The entity that a row of an experiment preaggregated table belongs to, for a read that
        aliases the table as `t`.

        A group-aggregated read uses `entity_id`, which holds the group key. A person-aggregated
        read uses the person stored in `entity_id` at build time, cast back to the UUID that the
        downstream joins expect. With merge resolution on, it uses the table's `person_id`
        instead, which follows a later identify or merge. Two rows that were built for different
        persons and now belong to one person then count as one entity, as they do on the events scan.
        """
        if self.entity_key != "person_id":
            return "t.entity_id"
        return "t.person_id" if self.resolve_precomputed_persons else "toUUID(t.entity_id)"

    def precompute_distinct_id_column_sql(self, distinct_id_sql: str) -> str:
        """
        The SELECT column that makes a build store `distinct_id_sql` as the distinct_id of each
        row. It is written to follow the last column of a build template.

        A read resolves a row to its current person through this distinct_id, so a build stores
        it only when the read does that. Otherwise the result is empty and the template stays
        byte for byte the same. The job hash includes the source position of each node, so a
        template that changes matches no cached job.
        """
        if self.entity_key != "person_id" or not self.resolve_precomputed_persons:
            return ""
        return f",\n                {distinct_id_sql} AS distinct_id"


@dataclass(frozen=True)
class ExperimentPrecomputationContext:
    """Precomputation inputs supplied at build time, not at construction.

    The builder generates the precompute queries before any job IDs exist,
    so the caller can supply the job IDs only at the build call.
    """

    exposure_job_ids: list[str] | None = None
    # Funnel, mean and retention metrics have one metric-events build. A ratio
    # metric has one per side, and each read CTE filters on its own jobs.
    metric_events_job_ids: list[str] | None = None
    numerator_job_ids: list[str] | None = None
    denominator_job_ids: list[str] | None = None


@frozen
class MaturityGate:
    """Excludes entities whose maturity window has not ended when the query is built.

    Every maturity filter of one build uses this gate, so they all compare against
    the same cutoff. ``computed_at`` is the only time input.
    """

    enabled: bool
    computed_at: datetime

    @classmethod
    def of(cls, context: ExperimentQueryContext, *, computed_at: datetime) -> "MaturityGate":
        return cls(enabled=context.only_count_matured_users, computed_at=computed_at)

    def condition(self, anchor: ast.Expr, window_seconds: int) -> ast.Expr | None:
        """``anchor + window <= cutoff``, or None when maturity filtering is off or the window is empty.

        ``anchor`` is the per-entity timestamp that the window starts from, for example
        ``min(timestamp)`` of the exposure events.
        """
        if not self.enabled or window_seconds == 0:
            return None
        return parse_expr(
            "{anchor} + toIntervalSecond({window_seconds}) <= toDateTime({cutoff}, 'UTC')",
            placeholders={
                "anchor": anchor,
                "window_seconds": ast.Constant(value=window_seconds),
                "cutoff": ast.Constant(value=self.computed_at.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S")),
            },
        )
