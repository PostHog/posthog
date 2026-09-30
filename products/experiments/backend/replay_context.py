"""Experiment context for replay surfaces.

The companion to :mod:`replay_linkage`: where the linkage resolves who is exposed, this module
answers what a replay surface says and decides about the experiment itself. It carries the
per-session variant lookup, the flag's rollout shares, the prompt-facing description of the
experiment, and the lifecycle read. Everything here is reachable through
``products.experiments.backend.facade.replay``, so consumers outside this product never import
the Experiment model.
"""

from collections.abc import Collection

from rest_framework.exceptions import ValidationError

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.models.team.team import Team

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.experiments.backend.facade.contracts import (
    ExperimentPromptContext,
    ExperimentStatus,
    ExperimentVariantPromptContext,
)
from products.experiments.backend.metric_utils import get_default_metric_title
from products.experiments.backend.models.experiment import Experiment
from products.experiments.backend.replay_linkage import (
    EXPERIMENT_HAS_NO_FLAG_MESSAGE,
    ExperimentExposureLinkage,
    _requestable_variant_keys,
    exposed_persons_select,
)


def accessible_experiment_ids(
    access: UserAccessControl | None, team_id: int, *, experiment_ids: Collection[int] | None = None
) -> set[int]:
    """The experiments the caller may view, filtered by object-level access (not just team).

    With `experiment_ids`, the subset of those ids; with None, every experiment of the team.
    `access` is None only outside request context, where there is no viewer to gate on, so
    nothing is filtered out then. Soft-deleted experiments stay in: a deleted experiment's
    historical data keeps the access level the experiment had, rather than opening up.
    """
    queryset = Experiment.objects.filter(team_id=team_id)
    if experiment_ids is not None:
        if not experiment_ids:
            return set()
        queryset = queryset.filter(id__in=experiment_ids)
    if access is not None:
        queryset = access.filter_queryset_by_access_level(queryset)
    return set(queryset.values_list("id", flat=True))


def _live_experiment(team: Team, experiment_id: int) -> Experiment | None:
    return Experiment.objects.filter(id=experiment_id, team=team, deleted=False).select_related("feature_flag").first()


def session_variant(linkage: ExperimentExposureLinkage, distinct_id: str) -> str | None:
    """The variant the experiment's analysis attributes to this distinct id's person, or None.

    None means the person is not cleanly exposed within the linkage's requested variants:
    never exposed, exposed only to a variant outside the requested set, or set aside as
    multiple-variant under "exclude" handling. The attribution follows the experiment's
    ``multiple_variant_handling``, because it reads the same population the analysis buckets.

    Runs a ClickHouse query, so call it from a run path, never while building an AST.
    """
    candidate = parse_select(
        "SELECT {distinct_id} AS distinct_id",
        placeholders={"distinct_id": ast.Constant(value=distinct_id)},
    )
    assert isinstance(candidate, ast.SelectQuery)
    select = exposed_persons_select(linkage, include_multiple_variant=False, candidate_distinct_ids=candidate)
    # Under a "break" timeout profile a timed-out scan returns partial rows, which would read as a
    # complete attribution (or as "unexposed"); a timeout must fail the lookup instead.
    settings = HogQLGlobalSettings(
        timeout_overflow_mode="throw",
        max_memory_usage=linkage.live_scan_max_memory_bytes,
    )
    response = execute_hogql_query(select, team=linkage.context.team, settings=settings)
    rows = response.results or []
    if not rows:
        return None
    columns = response.columns or []
    variant = rows[0][columns.index("variant")]
    return str(variant) if variant is not None else None


def variant_rollout_shares(team: Team, *, experiment_id: int) -> dict[str, float]:
    """Each requestable variant's share of the flag's rollout, as a 0..1 fraction.

    Shares come from the flag's variant percentages, so together with any excluded variants
    they sum to 1. Raises ValidationError, matching :func:`resolve_exposure_linkage`, for an
    unknown or deleted experiment and for one with no flag.
    """
    experiment = _live_experiment(team, experiment_id)
    if experiment is None:
        raise ValidationError(f"Experiment {experiment_id} doesn't exist in this environment.")
    flag = getattr(experiment, "feature_flag", None)
    if flag is None:
        raise ValidationError(EXPERIMENT_HAS_NO_FLAG_MESSAGE)
    requestable = set(_requestable_variant_keys(experiment))
    return {
        definition["key"]: (definition.get("rollout_percentage") or 0) / 100
        for definition in flag.variants
        if definition.get("key") in requestable
    }


def experiment_prompt_context(team: Team, *, experiment_id: int) -> ExperimentPromptContext | None:
    """The experiment as an LLM prompt describes it, or None for an unknown or deleted
    experiment or one with no flag."""
    experiment = _live_experiment(team, experiment_id)
    if experiment is None:
        return None
    flag = getattr(experiment, "feature_flag", None)
    if flag is None:
        return None
    requestable = set(_requestable_variant_keys(experiment))
    variants = tuple(
        ExperimentVariantPromptContext(
            key=definition["key"],
            description=definition.get("name") or "",
            rollout_percentage=float(definition.get("rollout_percentage") or 0),
        )
        for definition in flag.variants
        if definition.get("key") in requestable
    )
    # Saved metrics live on a junction table, classified primary/secondary by the link's
    # metadata.type, so reading experiment.metrics alone would drop them from the prompt.
    saved_primary_names = tuple(
        link.saved_metric.name
        for link in experiment.experimenttosavedmetric_set.select_related("saved_metric").all()
        if (link.metadata or {}).get("type", "primary") == "primary"
    )
    primary_metric_names = (
        tuple(
            metric.get("name") or get_default_metric_title(metric)
            for metric in experiment.metrics or []
            if isinstance(metric, dict)
        )
        + saved_primary_names
    )
    return ExperimentPromptContext(
        id=experiment.pk,
        name=experiment.name,
        description=experiment.description or "",
        feature_flag_key=experiment.get_feature_flag_key(),
        variants=variants,
        primary_metric_names=primary_metric_names,
    )


def experiment_status(team: Team, *, experiment_id: int) -> ExperimentStatus | None:
    """The experiment's lifecycle read, or None for an unknown or deleted experiment."""
    experiment = _live_experiment(team, experiment_id)
    if experiment is None:
        return None
    planned = (experiment.running_time_calculation or {}).get("recommended_running_time")
    return ExperimentStatus(
        status=experiment.status_label,
        start_date=experiment.start_date,
        end_date=experiment.end_date,
        archived=experiment.archived,
        planned_duration_days=(
            float(planned) if isinstance(planned, int | float) and not isinstance(planned, bool) else None
        ),
    )
