from collections.abc import Mapping
from dataclasses import asdict
from typing import Any

from django.db.models import BooleanField, Case, Exists, OuterRef, Prefetch, Q, QuerySet, Value, When
from django.utils import timezone

from posthog.models import TaggedItem
from posthog.models.team.team import Team
from posthog.models.utils import strict_fetch
from posthog.paging import Page, PageRequest
from posthog.queryset_paging import select_page

from products.experiments.backend.experiment_service import ExperimentService
from products.experiments.backend.facade.contracts import ExperimentListFilters, ListAccess
from products.experiments.backend.hogql_queries.exposure_query_logic import (
    EXPERIMENT_EXPOSURE_EVENT,
    resolve_default_exposure_event,
)
from products.experiments.backend.logic.saved_metrics import visible_to
from products.experiments.backend.models.experiment import (
    LEGACY_METRIC_KINDS,
    Experiment,
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


def list_page(
    *, team: Team, filters: ExperimentListFilters, access: ListAccess | None, page: PageRequest
) -> Page[Experiment]:
    rows = _experiments(team).defer(*LIST_DEFERRED_FIELDS).annotate(is_legacy_annotation=_list_is_legacy_annotation())
    queryset = ExperimentService(team=team, user=None).filter_experiments_queryset(
        visible_to(rows, access), action="list", query_params=_query_params(asdict(filters))
    )
    return select_page(strict_fetch(queryset), page)


def resolved_exposure_event(experiment: Experiment) -> str:
    # A rule-linked experiment counts the $experiment_exposure events of its rule, whatever the rollout says.
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
