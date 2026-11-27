from collections.abc import Collection, Mapping, Sequence
from dataclasses import asdict, fields
from typing import Any

from django.db.models import BooleanField, Case, Exists, OuterRef, Prefetch, Q, QuerySet, Value, When
from django.utils import timezone

from rest_framework.exceptions import ValidationError

from posthog.api.cohort import CohortSerializer
from posthog.api.tagged_item import BulkTagActivityContext, apply_bulk_tag_changes, replace_tags_on_object
from posthog.models import TaggedItem
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.models.utils import strict_fetch
from posthog.paging import Page, PageRequest
from posthog.queryset_paging import select_page

from products.experiments.backend.experiment_service import ExperimentService
from products.experiments.backend.facade.contracts import (
    ExperimentListFilters,
    ExperimentNotFound,
    ExperimentUpdate,
    ListAccess,
)
from products.experiments.backend.hogql_queries.exposure_query_logic import (
    EXPERIMENT_EXPOSURE_EVENT,
    resolve_default_exposure_event,
)
from products.experiments.backend.logic.list_access import visible_to
from products.experiments.backend.models.experiment import (
    LEGACY_METRIC_KINDS,
    Experiment,
    ExperimentSavedMetric,
    ExperimentToSavedMetric,
    get_experiment_rule,
)
from products.feature_flags.backend.facade.config import ConfigFormatError
from products.feature_flags.backend.facade.filters import stored_payloads
from products.feature_flags.backend.facade.rules import ExperimentRuleError
from products.feature_flags.backend.models.evaluation_context import FeatureFlagEvaluationContext

# Heavy JSON columns that the list does not return. The list filters, the status and the list mapper must not read them.
LIST_DEFERRED_FIELDS = (
    "metrics",
    "metrics_secondary",
    "secondary_metrics",
    "exposure_criteria",
    "stats_config",
    "scheduling_config",
    "filters",
    "primary_metrics_ordered_uuids",
    "secondary_metrics_ordered_uuids",
)


def _list_is_legacy_annotation() -> Case:
    """``experiment_has_legacy_metrics`` in SQL, for the list, which defers the metric columns.

    A read of those columns in Python costs one query per row. The predicate reads them inside the list query,
    and they stay out of the SELECT, so the deferral still holds.
    """
    inline_legacy = Q()
    for kind in LEGACY_METRIC_KINDS:
        inline_legacy |= Q(metrics__contains=[{"kind": kind}]) | Q(metrics_secondary__contains=[{"kind": kind}])
    saved_legacy = Exists(
        ExperimentToSavedMetric.objects.filter(
            experiment=OuterRef("pk"),
            saved_metric__query__kind__in=LEGACY_METRIC_KINDS,
        )
    )
    return Case(
        When(inline_legacy | saved_legacy, then=Value(True)),
        default=Value(False),
        output_field=BooleanField(),
    )


def _query_params(values: Mapping[str, str | None]) -> dict[str, str]:
    return {name: value for name, value in values.items() if value is not None}


def _experiments(team: Team) -> QuerySet[Experiment]:
    return (
        Experiment.objects.filter(team__project_id=team.project_id)
        .select_related("feature_flag", "created_by", "holdout__created_by")
        .prefetch_related(
            Prefetch(
                "feature_flag__flag_evaluation_contexts",
                queryset=FeatureFlagEvaluationContext.objects.select_related("evaluation_context"),
            ),
            Prefetch("tagged_items", queryset=TaggedItem.objects.select_related("tag"), to_attr="prefetched_tags"),
        )
    )


def get_detail(*, team: Team, experiment_id: int, include_deleted: bool) -> Experiment | None:
    queryset = (
        _experiments(team)
        .filter(pk=experiment_id)
        .select_related("team")
        .prefetch_related(
            Prefetch(
                "experimenttosavedmetric_set", queryset=ExperimentToSavedMetric.objects.select_related("saved_metric")
            )
        )
    )
    queryset = ExperimentService(team=team, user=None).filter_experiments_queryset(
        queryset, action="retrieve", include_deleted=include_deleted
    )
    return strict_fetch(queryset).first()


def get_handle(*, team: Team, experiment_id: int) -> Experiment | None:
    """The live experiment of the project with the id, with only the columns that `ExperimentHandle` reads."""
    return (
        Experiment.objects.filter(team__project_id=team.project_id, pk=experiment_id)
        .exclude(deleted=True)
        .select_related("feature_flag")
        .only(
            "id",
            "team_id",
            "created_by_id",
            "holdout_id",
            "flag_cleanup_task_id",
            "exposure_criteria",
            "feature_flag__created_by_id",
        )
        .first()
    )


def _one_in_project(team: Team, experiment_id: int, *, include_deleted: bool) -> QuerySet[Experiment]:
    queryset = Experiment.objects.filter(team__project_id=team.project_id, pk=experiment_id)
    return queryset if include_deleted else queryset.exclude(deleted=True)


def get_update_target(*, team: Team, experiment_id: int, include_deleted: bool) -> Experiment | None:
    """The experiment of the project with the id and its flag, which is all that `ExperimentUpdateTarget` reads.
    A deleted experiment counts only with `include_deleted`."""
    return strict_fetch(
        _one_in_project(team, experiment_id, include_deleted=include_deleted).select_related("feature_flag")
    ).first()


def get_for_action(*, team: Team, experiment_id: int, include_deleted: bool = False) -> Experiment:
    """The experiment of the project with the id, with the joins and prefetches of the experiment viewset's queryset,
    which the `ExperimentService` methods of its detail actions read. A deleted experiment counts only with
    `include_deleted`.

    Raises ExperimentNotFound when the project has no such experiment.
    """
    experiment = (
        _one_in_project(team, experiment_id, include_deleted=include_deleted)
        .select_related("team", "feature_flag", "created_by", "exposure_cohort", "holdout__created_by")
        .prefetch_related(
            Prefetch(
                "feature_flag__flag_evaluation_contexts",
                queryset=FeatureFlagEvaluationContext.objects.select_related("evaluation_context"),
            ),
            # order_by("id") keeps the shared metrics in insertion order, because the select_related joins would
            # otherwise leave the row order unspecified.
            Prefetch(
                "experimenttosavedmetric_set",
                queryset=ExperimentToSavedMetric.objects.select_related("saved_metric", "experiment__team").order_by(
                    "id"
                ),
            ),
        )
        .first()
    )
    if experiment is None:
        raise ExperimentNotFound()
    return experiment


def linked_saved_metric_ids(experiment_id: int) -> list[int]:
    return list(ExperimentSavedMetric.objects.filter(experiments=experiment_id).values_list("id", flat=True))


def create_exposure_cohort(
    experiment: Experiment, *, team: Team, user: User, serializer_context: dict[str, Any]
) -> dict[str, Any]:
    """Create the exposure cohort of the experiment, and return it as the cohort API shows it."""
    cohort = ExperimentService(team=team, user=user).create_exposure_cohort(
        experiment, serializer_context=serializer_context
    )
    return CohortSerializer(
        cohort, context={"request": serializer_context["request"], "team": serializer_context["team"]}
    ).data


def replace_tags(*, team: Team, experiment_id: int, tags: list[str]) -> None:
    replace_tags_on_object(tags, _one_in_project(team, experiment_id, include_deleted=True).get())


# The service refuses a folder on an update and names the field in the error, so it gets the request field name.
_UPDATE_DATA_KEYS = {"create_in_folder": "_create_in_folder"}
_NOT_UPDATE_DATA = frozenset({"allow_unknown_events", "feature_flag_config", "tags", "feature_flag_rule_id"})


def apply_update(
    *,
    team: Team,
    user: User,
    experiment_id: int,
    update: ExperimentUpdate,
    include_deleted: bool,
    serializer_context: dict[str, Any],
) -> None:
    experiment = get_for_action(team=team, experiment_id=experiment_id, include_deleted=include_deleted)
    # The rule is chosen on create. A client that sends back what it read changes nothing.
    if "feature_flag_rule_id" in update.fields_set and update.feature_flag_rule_id != experiment.feature_flag_rule_id:
        raise ValidationError("feature_flag_rule_id cannot change after the experiment is created.")
    # In the declaration order of the contract, which is the order of the validated data of the serializer.
    update_data = {
        _UPDATE_DATA_KEYS.get(field.name, field.name): getattr(update, field.name)
        for field in fields(update)
        if field.name in update.fields_set and field.name not in _NOT_UPDATE_DATA
    }
    updated = ExperimentService(team=team, user=user).update_experiment(
        experiment,
        update_data,
        feature_flag_config=update.feature_flag_config,
        serializer_context=serializer_context,
        allow_unknown_events=update.allow_unknown_events,
        deprecated_flag_config_changed=update.deprecated_flag_config_changed,
    )
    if update.tags is not None:
        replace_tags_on_object(update.tags, updated)


def list_page(
    *, team: Team, filters: ExperimentListFilters, access: ListAccess | None, page: PageRequest
) -> Page[Experiment]:
    rows = _experiments(team).defer(*LIST_DEFERRED_FIELDS).annotate(is_legacy_annotation=_list_is_legacy_annotation())
    return select_page(strict_fetch(_apply_list_filters(team, visible_to(rows, access), filters)), page)


def _apply_list_filters(team: Team, rows: QuerySet[Experiment], filters: ExperimentListFilters) -> QuerySet[Experiment]:
    return ExperimentService(team=team, user=None).filter_experiments_queryset(
        rows, action="list", query_params=_query_params(asdict(filters))
    )


_REF_FIELDS = ("id", "team_id", "created_by_id")


def list_refs(*, team: Team, filters: ExperimentListFilters) -> QuerySet[Experiment]:
    """Every experiment that the list shows for the filters, in the order of the list, with the columns of a ref."""
    rows = Experiment.objects.filter(team__project_id=team.project_id)
    return strict_fetch(_apply_list_filters(team, rows, filters).only(*_REF_FIELDS))


def _live_among(team: Team, experiment_ids: Collection[int]) -> QuerySet[Experiment]:
    experiments = Experiment.objects.filter(team__project_id=team.project_id, pk__in=list(experiment_ids))
    return experiments.exclude(deleted=True)


def refs_among(*, team: Team, experiment_ids: Collection[int]) -> QuerySet[Experiment]:
    """The live experiments of the project among the ids, archived ones included, newest first, with the columns of a
    ref."""
    return strict_fetch(_live_among(team, experiment_ids).order_by("-created_at").only(*_REF_FIELDS))


def change_tags(
    *,
    team: Team,
    user: User,
    was_impersonated: bool,
    experiment_ids: Sequence[int],
    tag_action: str,
    tags: Sequence[str],
) -> list[dict[str, Any]]:
    # apply_bulk_tag_changes reads the current tags itself, inside its transaction, so no tag prefetch here.
    experiments = strict_fetch(_live_among(team, experiment_ids).only("id", "team_id", "name"))
    by_id = {experiment.id: experiment for experiment in experiments}
    return apply_bulk_tag_changes(
        [by_id[experiment_id] for experiment_id in experiment_ids if experiment_id in by_id],
        tag_action,
        list(tags),
        activity_context=BulkTagActivityContext(
            scope="Experiment", user=user, was_impersonated=was_impersonated, activity="updated"
        ),
    )


def resolved_exposure_event(experiment: Experiment) -> str:
    # A rule-linked experiment counts the $experiment_exposure events of its rule, whatever the cutoff says.
    if experiment.is_rule_linked:
        return EXPERIMENT_EXPOSURE_EVENT
    # A draft has no start_date, so the setup UI shows the event that the draft would count if it launched now.
    return resolve_default_exposure_event(experiment.start_date or timezone.now())


def _with_split_percent(variants: list) -> list:
    # The frontend shows and edits the split of each variant as split_percent, a copy of its rollout_percentage.
    return [
        {**variant, "split_percent": variant["rollout_percentage"]}
        if isinstance(variant, dict) and "rollout_percentage" in variant
        else variant
        for variant in variants
    ]


def projected_parameters(experiment: Experiment) -> dict[str, Any]:
    """The `parameters` that the experiment API returns: the stored parameters, with the flag config keys
    taken from the flag, or from the rule of a rule-linked experiment."""
    stored = experiment.parameters
    # Legacy rows can hold a non-dict (see migration 0026). The flag or rule supplies the keys below, so drop it.
    parameters = dict(stored) if isinstance(stored, dict) else {}
    if experiment.is_rule_linked:
        _project_rule_config(parameters, experiment)
    else:
        _project_feature_flag_config(parameters, experiment)
    return parameters


def _project_rule_config(parameters: dict[str, Any], experiment: Experiment) -> None:
    """The `parameters` projection of a rule-linked experiment, in the same keys as
    `_project_feature_flag_config`, so a client reads the variants and the rollout of the rule the
    way it reads them from a flag.

    A rule that cannot be read, such as one a draft's flag no longer has, projects no variants:
    the read must still return the experiment.
    """
    for key in ("aggregation_group_type_index", "rollout_percentage", "feature_flag_payloads"):
        parameters.pop(key, None)
    try:
        rule = get_experiment_rule(experiment)
    except (ExperimentRuleError, ConfigFormatError):
        parameters["feature_flag_variants"] = []
    else:
        parameters["feature_flag_variants"] = _with_split_percent(rule.variants)
        if rule.assign_variant_by is not None:
            parameters["aggregation_group_type_index"] = rule.assign_variant_by
        if rule.rollout_percentage is not None:
            parameters["rollout_percentage"] = rule.rollout_percentage
    flag = experiment.feature_flag
    if flag.ensure_experience_continuity is not None:
        parameters["ensure_experience_continuity"] = flag.ensure_experience_continuity
    else:
        parameters.pop("ensure_experience_continuity", None)


def _project_feature_flag_config(parameters: dict[str, Any], experiment: Experiment) -> None:
    """Source feature-flag config in the deprecated `parameters` projection from the linked flag.

    The flag is the source of truth for every key in ``FEATURE_FLAG_CONFIG_KEYS``. Legacy rows can carry stale
    copies in the column. A client that spreads a GET response into a save must echo the live config of the flag,
    because the update path syncs those values onto the flag.
    """
    flag = experiment.feature_flag
    parameters["feature_flag_variants"] = _with_split_percent(flag.variants)

    if flag.aggregation_group_type_index is not None:
        parameters["aggregation_group_type_index"] = flag.aggregation_group_type_index
    else:
        parameters.pop("aggregation_group_type_index", None)

    conditions = flag.conditions
    if conditions and conditions[0].get("rollout_percentage") is not None:
        parameters["rollout_percentage"] = conditions[0]["rollout_percentage"]
    else:
        parameters.pop("rollout_percentage", None)

    payloads = stored_payloads(flag.get_filters())
    if payloads:
        parameters["feature_flag_payloads"] = payloads
    else:
        parameters.pop("feature_flag_payloads", None)

    if flag.ensure_experience_continuity is not None:
        parameters["ensure_experience_continuity"] = flag.ensure_experience_continuity
    else:
        parameters.pop("ensure_experience_continuity", None)
