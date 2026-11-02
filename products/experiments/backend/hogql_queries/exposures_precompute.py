"""
Exposures precomputation for one experiment query: whether the query can read
from experiment_exposures_preaggregated, and the lazy-computation build that fills it.

The gates that every experiment query shares live in precompute_policy; this module
composes them with the build limits and runs the build.
"""

from datetime import datetime
from typing import Any, Optional

from rest_framework.exceptions import ValidationError

from posthog.schema import PrecomputationMode

from posthog.dataclasses import frozen
from posthog.models.team.team import Team

from products.analytics_platform.backend.lazy_computation.lazy_computation_executor import (
    LazyComputationResult,
    LazyComputationTable,
    ensure_precomputed,
)
from products.experiments.backend.facade.enums import PrecomputeSkipReason
from products.experiments.backend.hogql_queries.experiment_query_builder import ExperimentQueryBuilder
from products.experiments.backend.hogql_queries.precompute_policy import (
    BLOCKING_PRECOMPUTE_SKIP_REASONS,
    experiment_precompute_ttl_schedule,
    team_precompute_skip_reason,
)
from products.experiments.backend.models.experiment import Experiment
from products.experiments.backend.models.team_experiments_config import TeamExperimentsConfig


@frozen
class ExposuresPrecompute:
    """The exposures precompute decisions and builds for one experiment query."""

    team: Team
    team_experiments_config: TeamExperimentsConfig
    experiment: Experiment
    window_start: Optional[datetime]
    window_end: datetime
    exposure_criteria: Any
    cohort_filter_sources: tuple[Any, ...]
    precomputation_mode: Optional[PrecomputationMode]
    is_data_warehouse_query: bool
    group_type_index: Optional[int]

    def ensure_precomputed(self, builder: ExperimentQueryBuilder) -> LazyComputationResult:
        if not self.window_start:
            raise ValidationError("Experiment must have a start date for lazy computation")

        query_string, placeholders = builder.get_exposure_query_for_precomputation()
        return ensure_precomputed(
            team=self.team,
            insert_query=query_string,
            time_range_start=self.window_start,
            time_range_end=self.window_end,
            ttl_seconds=experiment_precompute_ttl_schedule(self.team.timezone),
            table=LazyComputationTable.EXPERIMENT_EXPOSURES_PREAGGREGATED,
            placeholders=placeholders,
            sentinel_placeholders={"experiment_date_to"},
            end_is_data_horizon=True,
            # High-volume teams' builds OOM even at capped window widths; spilling the
            # GROUP BY to disk degrades gracefully instead of failing the build.
            spill_to_disk=True,
        )

    @property
    def applicable(self) -> bool:
        # The PRECOMPUTED mode skips the policy gates, but no mode makes these builds work.
        # The precomputed table doesn't include the join keys needed to link exposures to
        # data warehouse tables. A group-aggregated build INSERT references $group_N, which
        # the INSERT ... SELECT analysis path can't resolve (MATERIALIZED on sharded_events),
        # so every build fails with UNKNOWN_IDENTIFIER.
        if self.is_data_warehouse_query or self.group_type_index is not None:
            return False
        return self.ineligibility_reason() not in BLOCKING_PRECOMPUTE_SKIP_REASONS

    def ineligibility_reason(self) -> Optional[PrecomputeSkipReason]:
        """Why precompute was not used, for the query-performance UI. None when it was attempted."""
        if self.precomputation_mode == PrecomputationMode.PRECOMPUTED:
            return None
        if self.precomputation_mode == PrecomputationMode.DIRECT:
            return PrecomputeSkipReason.OVERRIDE_DIRECT

        blocked = team_precompute_skip_reason(
            self.team,
            self.team_experiments_config,
            self.experiment,
            self.exposure_criteria,
            *self.cohort_filter_sources,
        )
        if blocked is not None:
            return blocked

        if self.is_data_warehouse_query:
            return PrecomputeSkipReason.DATA_WAREHOUSE
        if self.group_type_index is not None:
            return PrecomputeSkipReason.GROUP_AGGREGATION
        return None  # precompute was attempted; a direct path means the build failed / wasn't ready
