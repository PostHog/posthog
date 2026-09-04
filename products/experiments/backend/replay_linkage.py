"""Person-scoped exposure linkage for replay surfaces.

Resolves an experiment's exposed population to one row per distinct id, carrying the person's
first exposure time, so recordings queries can show sessions of exposed persons. Built on the
same ExposureQueryBuilder the analysis queries use, which keeps exposure criteria, activation
events, and multiple-variant handling consistent with what the experiment's results count.

Linking by person and first exposure time, instead of requiring an exposure event inside the
session, is what keeps server-fired exposure events linkable: they carry no usable
``$session_id`` (none at all, or a context-generated one that matches no recording), but the
person's other distinct ids do appear on recordings. Expanding the exposed persons through
``raw_person_distinct_ids`` also covers cross-device sessions and anonymous pre-identify ids.

The work splits in two, because recordings queries build their AST separately from running it:

- :func:`resolve_exposure_linkage` validates the experiment and decides how the exposed
  population will be read. On teams with experiment precomputation enabled it resolves
  preaggregation job ids through the same ``ensure_precomputed`` path the analysis queries
  use, which reads and writes job state and can run ClickHouse inserts synchronously. That
  is runner work, so callers must invoke it from their run path, never while building an AST.
- :func:`exposed_distinct_ids_select` is pure AST construction from a resolved linkage.

The exposure scan window is deliberately the full experiment window, unbounded. Narrowing it
would change who counts as exposed relative to the analysis. The expensive cases are handled
instead: precomputing teams read the preaggregated table (converging in TTL-capped chunks for
long-running experiments), activation-mode exposures always resolve with a live scan because
they have no preaggregated form (carrying an explicit memory budget on precomputing teams),
and where neither the preaggregated read nor an affordable live scan is available the query
is refused with a ValidationError rather than left to time out.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from django.contrib.auth.models import AnonymousUser

import structlog
from rest_framework.exceptions import ValidationError

from posthog.schema import IntervalType

from posthog.hogql import ast
from posthog.hogql.parser import parse_select

from posthog.clickhouse.query_tagging import tag_queries, tags_context
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models.team.extensions import get_or_create_team_extension
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.synthetic_user import SyntheticUser

from products.access_control.backend.facade.user_access_control import UserAccessControl, UserAccessControlError
from products.analytics_platform.backend.lazy_computation.lazy_computation_executor import (
    LazyComputationTable,
    ensure_precomputed,
)
from products.experiments.backend.hogql_queries.base_query_utils import experiment_window, experiment_window_end
from products.experiments.backend.hogql_queries.cuped_config import CupedQueryConfig
from products.experiments.backend.hogql_queries.experiment_exposure_query_builder import ExposureQueryBuilder
from products.experiments.backend.hogql_queries.experiment_query_builder import get_exposure_config_params_for_builder
from products.experiments.backend.hogql_queries.experiment_query_context import ExperimentQueryContext
from products.experiments.backend.hogql_queries.experiment_query_runner import (
    experiment_has_min_runtime_for_precomputation,
    experiment_precompute_ttl_schedule,
    has_uncalculated_cohorts,
)
from products.experiments.backend.hogql_queries.exposure_query_logic import get_entity_key, has_activation_config
from products.experiments.backend.models.experiment import Experiment
from products.experiments.backend.models.team_experiments_config import TeamExperimentsConfig

logger = structlog.get_logger(__name__)

EXPOSURES_STILL_COMPUTING_MESSAGE = (
    "Exposed users for this experiment are still being computed. Try again in a few minutes."
)
COHORT_NOT_CALCULATED_MESSAGE = (
    "This experiment's exposure criteria reference a cohort that hasn't finished calculating. "
    "Try again when the cohort is ready."
)
# Sized an order of magnitude above the peak observed on the largest precompute-enabled team
# (#83514), so it fires only for a scan far outside anything measured, and below the cluster's
# default per-query limit, so the kill renders as the standard memory-limit error before the
# scan becomes cluster-level pressure.
ACTIVATION_LIVE_SCAN_MAX_MEMORY_BYTES = 4 * 1024**3


def validate_experiment_exposure_access(
    team: Team, user: User | AnonymousUser | SyntheticUser | None, experiment_id: int
) -> bool:
    """Refuse the ``experiment_exposure`` filter for viewers denied the experiment it names.

    The filter reveals experiment data through replay surfaces (which recordings belong to
    exposed persons, and to which variant), but recordings endpoints only enforce replay-level
    access — so the experiment's own object-level check must run here, matching what the
    experiment surfaces enforce for the same information.

    Refuses userless callers outright: a background job's output can reach viewers this check
    never evaluated (the playlist counting task caches match counts that any playlist viewer
    can read), so running the filter without a viewer can leak experiment data to viewers the
    experiment denies. A background consumer must supply the principal on whose behalf it
    runs, or not use the filter. Service-token principals and anonymous shared-link viewers
    are non-User principals outside object-level RBAC and pass; they are gated by API scope
    plus project membership, and by the sharing publish gate, respectively. An unknown
    experiment also passes, because there is no object to protect and
    :func:`resolve_exposure_linkage` reports it as a ValidationError.

    Returns True, or raises UserAccessControlError (the query-runner access contract).
    """
    if user is None:
        raise UserAccessControlError("experiment", "viewer", resource_id=str(experiment_id))
    if not isinstance(user, User):
        return True
    experiment = Experiment.objects.filter(id=experiment_id, team=team, deleted=False).first()
    if experiment is None:
        return True
    if not UserAccessControl(user=user, team=team).check_access_level_for_object(experiment, required_level="viewer"):
        raise UserAccessControlError("experiment", "viewer", resource_id=str(experiment_id))
    return True


@dataclass(frozen=True, kw_only=True)
class ExperimentExposureLinkage:
    """A validated experiment-exposure filter, resolved to how its population will be read.

    Opaque to callers outside this product: obtained from :func:`resolve_exposure_linkage`
    and handed back to :func:`exposed_distinct_ids_select`.
    """

    context: ExperimentQueryContext
    requested_variants: list[str]
    # Set = read the preaggregated exposures written by these jobs. None = live events scan.
    preaggregation_job_ids: list[str] | None
    # max_memory_usage ceiling the synchronous recordings-list run must apply when the live
    # scan needs explicit bounding instead of relying on cluster defaults. It bounds the whole
    # embedding query, so a kill renders as the platform's generic memory-limit error rather
    # than anything exposure-specific. Composition callers that execute the linkage's AST
    # through their own async or batch pipelines run under those pipelines' limits and may
    # ignore it.
    live_scan_max_memory_bytes: int | None = None
    # True when the exposure criteria apply the team's test-account filters, so the exposed
    # population is already test-filtered at the person level. Queries that restrict their rows
    # to this population can skip re-applying the same filters to their own rows.
    population_filters_test_accounts: bool = False


def resolve_exposure_linkage(team: Team, *, experiment_id: int, variant: str | None) -> ExperimentExposureLinkage:
    """Validate the experiment and resolve how its exposed population will be read.

    Raises ValidationError for experiments the linkage can't answer for: unknown or draft
    experiments, group-aggregated ones (whose exposed entities are groups rather than
    persons and so never match a recording's distinct id), unknown variants, and
    experiments whose exposures can be resolved neither from the preaggregated table nor
    with a live scan the team can afford.
    """
    try:
        experiment = Experiment.objects.get(id=experiment_id, team=team, deleted=False)
    except Experiment.DoesNotExist:
        raise ValidationError(f"Experiment {experiment_id} doesn't exist in this environment.")

    flag = getattr(experiment, "feature_flag", None)
    if flag is None:
        raise ValidationError("This experiment has no feature flag, so exposures can't be resolved.")
    if experiment.start_date is None:
        raise ValidationError("This experiment hasn't launched, so it has no exposed sessions yet.")
    if (flag.filters or {}).get("aggregation_group_type_index") is not None:
        raise ValidationError(
            "This experiment aggregates by group, so its exposures can't be matched to persons' recordings."
        )

    excluded_variants = set(experiment.excluded_variants or [])
    variant_keys = [
        variant_definition["key"]
        for variant_definition in flag.variants or []
        if variant_definition.get("key") and variant_definition["key"] not in excluded_variants
    ]
    if not variant_keys:
        raise ValidationError("This experiment's feature flag defines no variants.")
    if variant is not None:
        if variant not in variant_keys:
            raise ValidationError(f"'{variant}' is not a variant of this experiment.")
        requested_variants = [variant]
    else:
        requested_variants = variant_keys

    exposure_params = get_exposure_config_params_for_builder(experiment.exposure_criteria, team, experiment.start_date)
    date_range_query = QueryDateRange(
        date_range=experiment_window(experiment, team, as_of=experiment.end_date or datetime.now(UTC)),
        team=team,
        interval=IntervalType.DAY,
        now=datetime.now(UTC),
    )
    context = ExperimentQueryContext(
        team=team,
        feature_flag_key=flag.key_without_tombstone(),
        exposure_config=exposure_params.exposure_config,
        filter_test_accounts=exposure_params.filter_test_accounts,
        multiple_variant_handling=exposure_params.multiple_variant_handling,
        # The full variant list, not the requested one: variant attribution and multiple-variant
        # detection must see every variant, or a person exposed to two variants would pass as
        # cleanly exposed to the requested one. Narrowing happens in the WHERE below instead.
        variants=tuple(variant_keys),
        date_range_query=date_range_query,
        entity_key=get_entity_key(None),
        breakdowns=(),
        only_count_matured_users=False,
        cuped_config=CupedQueryConfig(),
        activation_config=exposure_params.activation_config,
    )
    read = _resolve_exposure_read(team, experiment, context)
    return ExperimentExposureLinkage(
        context=context,
        requested_variants=requested_variants,
        preaggregation_job_ids=read.preaggregation_job_ids,
        live_scan_max_memory_bytes=read.live_scan_max_memory_bytes,
        population_filters_test_accounts=exposure_params.filter_test_accounts,
    )


@dataclass(frozen=True, kw_only=True)
class _ExposureRead:
    preaggregation_job_ids: list[str] | None
    live_scan_max_memory_bytes: int | None


def _resolve_exposure_read(team: Team, experiment: Experiment, context: ExperimentQueryContext) -> _ExposureRead:
    """How the exposed population will be read: preaggregation job ids, or a live scan.

    The eligibility gates mirror the exposures-chart runner's, but the fallback posture
    inverts: the analysis can always fall back to a direct scan, because it runs through
    the async query pipeline with generous limits, while this linkage runs inside a
    synchronous recordings-list GET. Precomputation being enabled is the team-level
    marker for the teams where the full-window live scan is a real cost, so on them a
    transiently unavailable preaggregated read (still computing, cohort mid-calculation)
    is refused instead of silently attempting the scan that precomputation exists to
    avoid. Activation mode is the exception: it has no preaggregated form at all, and
    its live scan stays affordable because its memory is bounded by the exposed
    population, so it scans live under an explicit memory budget rather than being
    permanently refused.
    """
    config = get_or_create_team_extension(team, TeamExperimentsConfig)
    # Below the minimum runtime the analysis skips precomputation too: the scan window is
    # hours wide (cheap on any team), and the current-day cache TTL would hide exposures
    # from the tab for up to 15 minutes right when users watch it most.
    if not config.experiment_precomputation_enabled or not experiment_has_min_runtime_for_precomputation(
        experiment.start_date, experiment.end_date
    ):
        tag_queries(experiment_exposures_path="direct_scan")
        return _ExposureRead(preaggregation_job_ids=None, live_scan_max_memory_bytes=None)

    if has_uncalculated_cohorts(team, experiment.exposure_criteria):
        # Both reads below see the cohort's partially-inserted membership: a precompute build
        # would freeze the torn snapshot for the frozen-band TTL, and the activation live scan
        # would silently undercount. Transient, so the error says to retry.
        raise ValidationError(COHORT_NOT_CALCULATED_MESSAGE)

    if has_activation_config(experiment.exposure_criteria):
        # The flag-to-activation ordering crosses the per-day cache buckets, so activation
        # exposures have no preaggregated form. Their live scan stays affordable even on the
        # largest teams, because it is bounded by the experiment window's activation events
        # and the distinct-id expansion's memory scales with the exposed population, so they
        # scan live instead of being refused. The ceiling keeps the scan explicitly bounded:
        # one that outgrows it is killed with the standard memory-limit error instead of
        # pressuring the cluster.
        tag_queries(experiment_exposures_path="direct_scan_activation")
        return _ExposureRead(
            preaggregation_job_ids=None,
            live_scan_max_memory_bytes=ACTIVATION_LIVE_SCAN_MAX_MEMORY_BYTES,
        )

    query_string, placeholders = ExposureQueryBuilder(context=context).precomputation_query()
    assert experiment.start_date is not None
    try:
        with tags_context(experiment_query_surface="precompute_build", experiment_precompute_table="exposures"):
            result = ensure_precomputed(
                team=team,
                insert_query=query_string,
                time_range_start=experiment.start_date,
                time_range_end=experiment_window_end(experiment, experiment.end_date or datetime.now(UTC)),
                ttl_seconds=experiment_precompute_ttl_schedule(team.timezone),
                table=LazyComputationTable.EXPERIMENT_EXPOSURES_PREAGGREGATED,
                placeholders=placeholders,
                sentinel_placeholders={"experiment_date_to"},
                spill_to_disk=True,
            )
    except Exception:
        logger.exception("exposure_lazy_computation_failed", experiment_id=experiment.id)
        raise ValidationError(EXPOSURES_STILL_COMPUTING_MESSAGE)
    if not result.ready:
        # Cold long-running experiments converge across successive requests: each ensure
        # call persists the chunk jobs it completed, so retrying eventually succeeds.
        logger.warning("exposure_lazy_computation_not_ready", experiment_id=experiment.id)
        raise ValidationError(EXPOSURES_STILL_COMPUTING_MESSAGE)

    tag_queries(experiment_exposures_path="precomputed")
    return _ExposureRead(
        preaggregation_job_ids=[str(job_id) for job_id in result.job_ids],
        live_scan_max_memory_bytes=None,
    )


def exposed_distinct_ids_select(linkage: ExperimentExposureLinkage) -> ast.SelectQuery:
    """One row per exposed distinct id: (distinct_id, first_exposure_time).

    Pure AST construction; :func:`resolve_exposure_linkage` carries the validation and the
    precompute decision, so callers can build query ASTs without side effects.
    """
    exposure_select = ExposureQueryBuilder(
        context=linkage.context,
        preaggregation_job_ids=linkage.preaggregation_job_ids,
    ).select_query()

    # The distinct-id expansion must not aggregate the team's whole mapping table: its memory
    # scales with the team's total distinct ids rather than with the exposed population, which
    # OOMs the recordings request on the largest teams. So a prefilter first nominates the
    # distinct ids that ever mapped to an exposed person (a row-level scan, no aggregation
    # state), and argMax then resolves the latest mapping over every version row of those
    # candidates only. Filtering rows by person_id directly instead would resurrect stale
    # mappings: a distinct id reassigned away from an exposed person keeps its old rows, and
    # argMax over just those would report the old person as current. The prefilter is a
    # superset (it ignores variant and reassignment), and the join keeps only candidates whose
    # latest person really is exposed.
    #
    # The WHERE on variant also drops entities attributed MULTIPLE_VARIANT_KEY under "exclude"
    # handling, matching who the analysis counts. Both join sides are pre-grouped, so each
    # distinct id carries exactly one exposure row and min() merely satisfies the GROUP BY.
    query = parse_select(
        """
        SELECT
            pdi.distinct_id AS distinct_id,
            min(exposures.first_exposure_time) AS first_exposure_time
        FROM (
            SELECT
                distinct_id,
                argMax(person_id, version) AS person_id,
                argMax(is_deleted, version) AS is_deleted
            FROM raw_person_distinct_ids
            WHERE team_id = {team_id}
                AND distinct_id IN (
                    SELECT distinct_id
                    FROM raw_person_distinct_ids
                    WHERE team_id = {prefilter_team_id}
                        AND person_id IN (SELECT entity_id FROM exposures)
                )
            GROUP BY distinct_id
            HAVING is_deleted = 0
        ) AS pdi
        INNER JOIN exposures ON exposures.entity_id = pdi.person_id
        WHERE exposures.variant IN {requested_variants}
        GROUP BY pdi.distinct_id
        """,
        placeholders={
            "team_id": ast.Constant(value=linkage.context.team.pk),
            "prefilter_team_id": ast.Constant(value=linkage.context.team.pk),
            "requested_variants": ast.Constant(value=linkage.requested_variants),
        },
    )
    assert isinstance(query, ast.SelectQuery)
    # Both the prefilter and the join read the exposed population, and ClickHouse substitutes a
    # plain CTE at each reference rather than computing it once, so a bare `WITH` would scan the
    # exposure source twice. MATERIALIZED computes it once and reuses the result, which keeps the
    # live path to a single events scan and holds only the exposed rows in memory.
    query.ctes = {"exposures": ast.CTE(name="exposures", expr=exposure_select, cte_type="subquery", materialized=True)}
    return query
