from dataclasses import fields
from typing import Any

from django.db.models import BooleanField, Case, Exists, OuterRef, Prefetch, Q, Value, When

from posthog.models import TaggedItem
from posthog.models.team.team import Team
from posthog.models.utils import strict_fetch
from posthog.paging import Page, PageRequest
from posthog.queryset_paging import select_page

from products.experiments.backend.experiment_service import ExperimentService
from products.experiments.backend.facade.contracts import ExperimentListFilters, ListAccess
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

# Heavy JSON columns the list view never renders. Deferred for the list action so large
# pages don't pay to read/decode detail-only data; the full serializer still loads them
# for retrieve/update. None of these are touched by the list filters or status derivation.
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

_RELATIONS = ("team", "feature_flag", "created_by", "exposure_cohort", "holdout__created_by")


def _flag_evaluation_contexts_prefetch() -> Prefetch:
    return Prefetch(
        "feature_flag__flag_evaluation_contexts",
        queryset=FeatureFlagEvaluationContext.objects.select_related("evaluation_context"),
    )


def _tags_prefetch() -> Prefetch:
    return Prefetch("tagged_items", queryset=TaggedItem.objects.select_related("tag"), to_attr="prefetched_tags")


def _list_is_legacy_annotation() -> Case:
    """DB-side `is_legacy` for the list endpoint, mirroring ``experiment_has_legacy_metrics`` in SQL.

    The list serializer omits metrics, so it can't compute legacy-ness in Python without
    re-reading the deferred JSON columns (one query per row). Instead we annotate the flag in the
    single list query: a JSONB containment check on the inline metrics plus an ``EXISTS`` over the
    saved metrics. The metric columns are referenced only in the predicate, so they stay out of the
    SELECT output and the response — the deferral still holds.
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


def _query_params(filters: ExperimentListFilters | None) -> dict[str, str]:
    if filters is None:
        return {}
    values = ((field.name, getattr(filters, field.name)) for field in fields(filters))
    return {name: value for name, value in values if value is not None}


def get_detail(
    *, team: Team, experiment_id: int, include_deleted: bool, lookup: ExperimentListFilters | None
) -> Experiment | None:
    queryset = (
        Experiment.objects.filter(team__project_id=team.project_id, pk=experiment_id)
        .select_related(*_RELATIONS)
        .prefetch_related(
            _flag_evaluation_contexts_prefetch(),
            Prefetch(
                # order_by("id") keeps saved metrics in insertion order — select_related below adds
                # joins that would otherwise leave the row order unspecified.
                "experimenttosavedmetric_set",
                queryset=ExperimentToSavedMetric.objects.select_related("saved_metric", "experiment__team").order_by(
                    "id"
                ),
            ),
            _tags_prefetch(),
        )
    )
    queryset = ExperimentService(team=team, user=None).filter_experiments_queryset(
        queryset, action="retrieve", query_params=_query_params(lookup), include_deleted=include_deleted
    )
    return strict_fetch(queryset).first()


def list_page(
    *, team: Team, filters: ExperimentListFilters, access: ListAccess | None, page: PageRequest
) -> Page[Experiment]:
    queryset = (
        Experiment.objects.filter(team__project_id=team.project_id)
        .select_related(*_RELATIONS)
        .prefetch_related(_flag_evaluation_contexts_prefetch(), _tags_prefetch())
        .defer(*LIST_DEFERRED_FIELDS)
        .annotate(is_legacy_annotation=_list_is_legacy_annotation())
    )
    queryset = ExperimentService(team=team, user=None).filter_experiments_queryset(
        visible_to(queryset, access), action="list", query_params=_query_params(filters)
    )
    return select_page(strict_fetch(queryset), page)


def _with_split_percent(variants: list) -> list:
    # Add split_percent to outside representation for each variant to simplify frontend logic. The internal representation only uses rollout_percentage to avoid redundancy, but the frontend needs split_percent to display the variant splits in the UI and to support editing the splits in a user-friendly way (editing rollout_percentage directly would be more complex since it's not variant-specific and needs to be inferred from the variants' split_percent values).
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
    # The JSON column can legally hold a non-dict on legacy rows (see migration 0026); the flag
    # is the source of truth for the keys below, so a malformed blob is simply dropped.
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

    The flag is the source of truth for every key in ``FEATURE_FLAG_CONFIG_KEYS`` — `parameters`
    is a deprecated compatibility surface (see the experiment model's `parameters` comment).
    Reading these keys from the flag instead of the stored column lets us stop persisting the
    `parameters` mirror without changing the API response. It also keeps read-modify-write
    echoes safe: legacy rows still carry stale copies in the column until the backfill strips
    them, and a client that spreads a GET response into a save must echo the flag's live
    config, not stale values the update path would then sync onto the flag. The loaders read the
    linked flag with the experiment, so this adds no queries.
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
