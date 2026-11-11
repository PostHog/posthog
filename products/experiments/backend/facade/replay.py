"""Replay linkage capability for callers outside the experiments product.

The linkage crosses the boundary as the `ExperimentExposureLinkage` contract. The functions here map the internal
resolution to that contract and back, so callers never hold the internal query context.
"""

from datetime import datetime

from posthog.hogql import ast

from posthog.models.team.team import Team

from products.experiments.backend import replay_context, replay_linkage
from products.experiments.backend.facade.contracts import (
    ExperimentExposureLinkage,
    InSessionExposureSemantics,
    SessionAttribution,
)
from products.experiments.backend.models.experiment import Experiment
from products.experiments.backend.replay_context import (
    accessible_experiment_ids,
    experiment_prompt_context,
    experiment_status,
    launched_experiment_ids,
    variant_rollout_shares,
)
from products.experiments.backend.replay_linkage import (
    ACTIVATION_LIVE_SCAN_MAX_MEMORY_BYTES,
    COHORT_NOT_CALCULATED_MESSAGE,
    EXPOSURES_STILL_COMPUTING_MESSAGE,
    IN_SESSION_EVIDENCE_SCAN_MAX_MEMORY_BYTES,
    targetable_experiments,
    validate_draft_experiment_scope,
    validate_experiment_exposure_access,
)

__all__ = [
    "ACTIVATION_LIVE_SCAN_MAX_MEMORY_BYTES",
    "COHORT_NOT_CALCULATED_MESSAGE",
    "EXPOSURES_STILL_COMPUTING_MESSAGE",
    "IN_SESSION_EVIDENCE_SCAN_MAX_MEMORY_BYTES",
    "accessible_experiment_ids",
    "experiment_prompt_context",
    "experiment_status",
    "launched_experiment_ids",
    "exposed_distinct_ids_select",
    "exposed_persons_select",
    "exposed_session_ids_select",
    "resolve_exposure_linkage",
    "resolve_in_session_exposure_semantics",
    "session_attribution",
    "session_variant",
    "targetable_experiments",
    "validate_draft_experiment_scope",
    "validate_experiment_exposure_access",
    "variant_rollout_shares",
]


def resolve_exposure_linkage(
    team: Team,
    *,
    experiment_id: int,
    variant: str | None = None,
    variants: list[str] | None = None,
    in_session: bool = False,
) -> ExperimentExposureLinkage:
    """Validate the experiment and resolve how its exposed population will be read.

    Raises the same ValidationError as `replay_linkage.resolve_exposure_linkage`, for the experiments it can't
    answer for.
    """
    linkage = replay_linkage.resolve_exposure_linkage(
        team, experiment_id=experiment_id, variant=variant, variants=variants, in_session=in_session
    )
    return ExperimentExposureLinkage(
        requested_variants=tuple(linkage.requested_variants),
        live_scan_max_memory_bytes=linkage.live_scan_max_memory_bytes,
        population_filters_test_accounts=linkage.population_filters_test_accounts,
        in_session=linkage.session_exposure is not None,
        _resolution=linkage,
    )


def _resolved(linkage: ExperimentExposureLinkage) -> replay_linkage.ExperimentExposureLinkage:
    resolution = linkage._resolution
    if not isinstance(resolution, replay_linkage.ExperimentExposureLinkage):
        raise TypeError("Pass a linkage from resolve_exposure_linkage.")
    return resolution


def exposed_distinct_ids_select(
    linkage: ExperimentExposureLinkage, *, candidate_distinct_ids: ast.SelectQuery | None = None
) -> ast.SelectQuery:
    """One row per exposed distinct id: (distinct_id, first_exposure_time). See
    `replay_linkage.exposed_distinct_ids_select` for the `candidate_distinct_ids` contract."""
    return replay_linkage.exposed_distinct_ids_select(_resolved(linkage), candidate_distinct_ids=candidate_distinct_ids)


def exposed_persons_select(
    linkage: ExperimentExposureLinkage,
    *,
    include_multiple_variant: bool,
    candidate_distinct_ids: ast.SelectQuery | None = None,
) -> ast.SelectQuery:
    """One row per exposed distinct id, with the person and the attributed variant projected:
    (distinct_id, person_id, variant, first_exposure_time). See `replay_linkage.exposed_persons_select`."""
    return replay_linkage.exposed_persons_select(
        _resolved(linkage),
        include_multiple_variant=include_multiple_variant,
        candidate_distinct_ids=candidate_distinct_ids,
    )


def exposed_session_ids_select(
    linkage: ExperimentExposureLinkage,
    *,
    clamp_date_from: datetime | None = None,
    clamp_date_to: datetime | None = None,
) -> ast.SelectQuery:
    """Distinct ids of sessions carrying in-session exposure evidence. The linkage must have been resolved with
    `in_session=True`. See `replay_linkage.exposed_session_ids_select`."""
    return replay_linkage.exposed_session_ids_select(
        _resolved(linkage), clamp_date_from=clamp_date_from, clamp_date_to=clamp_date_to
    )


def session_attribution(linkage: ExperimentExposureLinkage, distinct_id: str) -> SessionAttribution | None:
    """The attribution the experiment's analysis gives this distinct id's person, or None. Runs a ClickHouse query.
    See `replay_context.session_attribution`."""
    return replay_context.session_attribution(_resolved(linkage), distinct_id)


def session_variant(linkage: ExperimentExposureLinkage, distinct_id: str) -> str | None:
    """The variant half of `session_attribution`, for callers that need no exposure time."""
    return replay_context.session_variant(_resolved(linkage), distinct_id)


def resolve_in_session_exposure_semantics(*, team_id: int, experiment_id: int) -> InSessionExposureSemantics | None:
    """Resolve whether the in-session narrowing can answer for this experiment, and how. Postgres reads only.

    None for an unknown or deleted experiment.
    """
    experiment = (
        Experiment.objects.filter(id=experiment_id, team_id=team_id, deleted=False)
        .select_related("team", "feature_flag")
        .first()
    )
    if experiment is None:
        return None
    semantics = replay_linkage.resolve_in_session_exposure_semantics(experiment.team, experiment)
    return InSessionExposureSemantics(
        unavailable_reason=semantics.unavailable_reason,
        uses_stamped_fallback=semantics.uses_stamped_fallback,
    )
