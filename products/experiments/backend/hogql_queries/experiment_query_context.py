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
    # When set, an entity only counts as exposed once it emits this event at/after its first
    # default exposure event, and that activation event's timestamp becomes the exposure time.
    activation_config: ExperimentEventExposureConfig | ActionsNode | None = None


@dataclass(frozen=True)
class ExperimentPrecomputationContext:
    """Precomputation inputs supplied at build time, not at construction.

    The builder generates the precompute queries before any job IDs exist,
    so the caller can supply the job IDs only at the build call.
    """

    exposure_job_ids: list[str] | None = None
    metric_events_job_ids: list[str] | None = None


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
