from dataclasses import dataclass

from posthog.schema import ActionsNode, Breakdown, ExperimentEventExposureConfig, MultipleVariantHandling

from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models.team.team import Team

from products.experiments.backend.hogql_queries.cuped_config import CupedQueryConfig


@dataclass(frozen=True)
class ExperimentQueryContext:
    """Experiment-level invariants shared across query construction.

    This is a transitional and organizational object: it carries the
    experiment-scoped parameters that the builder receives at construction
    time so future extracted modules can take a single, stable input
    instead of threading each parameter individually.
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


@dataclass(frozen=True)
class ExperimentPrecomputationContext:
    """Explicit precomputation inputs supplied at build time.

    Replaces post-construction mutation of the builder's job-id attributes.
    The builder is needed to generate the precompute queries before any job
    IDs exist (chicken-and-egg), so job IDs can only be supplied once they
    are known, at the build call.
    """

    exposure_job_ids: list[str] | None = None
    metric_events_job_ids: list[str] | None = None
