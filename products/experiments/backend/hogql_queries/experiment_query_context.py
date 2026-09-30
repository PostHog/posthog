from dataclasses import dataclass

from posthog.schema import ActionsNode, Breakdown, ExperimentEventExposureConfig, MultipleVariantHandling

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
