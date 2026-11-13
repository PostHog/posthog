"""Serializers for the setup context, the project facts that decide how to configure a new experiment.

ExperimentHealthInputsProjectSerializer is here because it renders the same facts for the health check
inputs, from the same section serializers."""

from typing import Annotated, Any

from drf_spectacular.utils import extend_schema_field
from pydantic import (
    Field as PydanticField,
    RootModel as PydanticRootModel,
    ValidationError as PydanticValidationError,
)
from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from posthog.schema import (
    AnyPropertyFilterDiscriminated,
    EventPropertyFilter,
    MultipleVariantHandling,
    PersonPropertyFilter,
    PropertyOperator,
)

from products.experiments.backend.setup_context import (
    DEFAULT_LIST_LIMIT,
    MAX_LIST_LIMIT,
    MAX_PROPERTY_FILTERS,
    PreviousExperimentState,
    SdkLibCategory,
    SetupContextSectionStatus,
)


class _ExperimentSetupPropertyFilterList(PydanticRootModel):
    """Event or person property filters that narrow which events are counted."""

    root: Annotated[list[EventPropertyFilter | PersonPropertyFilter], PydanticField(max_length=MAX_PROPERTY_FILTERS)]


@extend_schema_field(_ExperimentSetupPropertyFilterList)  # type: ignore[arg-type]
class ExperimentSetupPropertyFiltersField(serializers.JSONField):
    pass


class _ExperimentSetupStoredPropertyFilterList(PydanticRootModel):
    """Property filters as an experiment stored them. Any filter type can appear, cohorts included."""

    root: list[AnyPropertyFilterDiscriminated]


@extend_schema_field(_ExperimentSetupStoredPropertyFilterList)  # type: ignore[arg-type]
class ExperimentSetupStoredPropertyFiltersField(serializers.JSONField):
    pass


# `property_to_expr` raises NotImplementedError for this operator. Rejecting it here answers the
# caller with a 400 rather than failing the section that reads the filters.
_UNSUPPORTED_SETUP_CONTEXT_OPERATORS: frozenset[PropertyOperator] = frozenset({PropertyOperator.FLAG_EVALUATES_TO})


def _validated_setup_context_property_filters(value: Any) -> list[dict[str, Any]]:
    """Parse the filters the way the query builder will, so a shape it cannot read fails as a 400."""
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValidationError("Pass a list of event or person property filters.")
    try:
        parsed = _ExperimentSetupPropertyFilterList.model_validate(value)
    except PydanticValidationError as error:
        first_error = error.errors()[0]
        if first_error.get("type") == "too_long":
            raise ValidationError(f"Pass at most {MAX_PROPERTY_FILTERS} filters.")
        raise ValidationError(
            "Each filter needs type 'event' or 'person', a key, an operator and a value. "
            f"{first_error.get('msg', 'Check the filter shape.')}"
        )
    used_operators = {property_filter.operator for property_filter in parsed.root if property_filter.operator}
    unsupported = sorted(operator.value for operator in used_operators & _UNSUPPORTED_SETUP_CONTEXT_OPERATORS)
    if unsupported:
        raise ValidationError(f"These operators cannot be read here: {', '.join(unsupported)}.")
    return [property_filter.model_dump(exclude_none=True) for property_filter in parsed.root]


class ExperimentSetupContextInputSerializer(serializers.Serializer):
    """What the caller plans to test. Every field is optional; a section that needs a missing input
    comes back with status 'skipped'."""

    target_event = serializers.CharField(
        required=False,
        allow_null=True,
        max_length=400,
        help_text=(
            "Event that marks a visit to the surface under test, for example '$pageview' or '$screen'. Needed "
            "for target_surface and for the baseline in candidate_metric."
        ),
    )
    target_url_contains = serializers.CharField(
        required=False,
        allow_null=True,
        max_length=1000,
        help_text=(
            "Only counts target events whose $current_url contains this text, ignoring case. Needs target_event "
            "to be '$pageview'."
        ),
    )
    target_properties = ExperimentSetupPropertyFiltersField(
        required=False,
        allow_null=True,
        help_text=(
            "Event or person property filters that narrow the target event, for example an exact $host and "
            f"$pathname for one page. At most {MAX_PROPERTY_FILTERS} filters, and each needs type 'event' or "
            "'person'. Needs target_event. Combines with target_url_contains."
        ),
    )
    metric_event = serializers.CharField(
        required=False,
        allow_null=True,
        max_length=400,
        help_text=(
            "Event of the candidate primary metric. With target_event, candidate_metric returns a baseline. "
            "Without it, candidate_metric returns only the event's volume. Also marks the shared metrics that "
            "count this event."
        ),
    )
    metric_properties = ExperimentSetupPropertyFiltersField(
        required=False,
        allow_null=True,
        help_text=(
            "Event or person property filters that narrow the metric event, for the metric that counts only some "
            f"of its occurrences. At most {MAX_PROPERTY_FILTERS} filters, and each needs type 'event' or "
            "'person'. Needs metric_event."
        ),
    )
    previous_experiments_limit = serializers.IntegerField(
        required=False,
        default=DEFAULT_LIST_LIMIT,
        min_value=1,
        max_value=MAX_LIST_LIMIT,
        help_text=(
            f"How many experiments to return, most recently launched first, then drafts, 1 to {MAX_LIST_LIMIT}."
        ),
    )
    shared_metrics_limit = serializers.IntegerField(
        required=False,
        default=DEFAULT_LIST_LIMIT,
        min_value=1,
        max_value=MAX_LIST_LIMIT,
        help_text=f"How many shared metrics to return, most reused first, 1 to {MAX_LIST_LIMIT}.",
    )

    def validate_target_properties(self, value: Any) -> list[dict[str, Any]]:
        return _validated_setup_context_property_filters(value)

    def validate_metric_properties(self, value: Any) -> list[dict[str, Any]]:
        return _validated_setup_context_property_filters(value)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if attrs.get("target_url_contains") and attrs.get("target_event") != "$pageview":
            raise ValidationError(
                {"target_url_contains": "Set target_event to '$pageview' to filter by URL, or remove this field."}
            )
        for filters_field, event_field in [
            ("target_properties", "target_event"),
            ("metric_properties", "metric_event"),
        ]:
            if attrs.get(filters_field) and not attrs.get(event_field):
                raise ValidationError(
                    {filters_field: f"Pass {event_field} as well, or remove this field. The filters narrow it."}
                )
        if attrs.get("metric_event") and attrs.get("metric_event") == attrs.get("target_event"):
            raise ValidationError(
                {
                    "metric_event": (
                        "Pick a metric_event other than target_event. The same event on both sides makes every "
                        "person a converter, so the conversion rate is always 1."
                    )
                }
            )
        return attrs


def _section_status_field() -> serializers.ChoiceField:
    return serializers.ChoiceField(
        choices=SetupContextSectionStatus.choices,
        help_text=(
            "'ok' when data holds the section. 'skipped' when an input the section needs was not passed. "
            "'timed_out' when the query was too expensive to finish. 'error' when the read failed. Every "
            "status other than 'ok' leaves data null, and the other sections are still valid."
        ),
    )


class ExperimentSetupTeamDefaultsSerializer(serializers.Serializer):
    stats_method = serializers.CharField(
        allow_null=True, help_text="Default statistical method for new experiments: 'bayesian' or 'frequentist'."
    )
    confidence_level = serializers.FloatField(
        allow_null=True, help_text="Default confidence level for new experiments, for example 0.95. Null when unset."
    )
    minimum_detectable_effect = serializers.IntegerField(
        allow_null=True,
        help_text=(
            "The team's default minimum detectable effect, as a percentage. Null when the team has not set one; "
            "product_default_minimum_detectable_effect applies then."
        ),
    )
    product_default_minimum_detectable_effect = serializers.IntegerField(
        help_text="The minimum detectable effect, as a percentage, that applies when the team has no default."
    )
    product_default_stats_method = serializers.CharField(
        help_text="The statistical method that applies when the team has no default."
    )
    product_default_confidence_level = serializers.FloatField(
        help_text="The confidence level that applies when the team has no default. Both methods use the same one."
    )
    only_count_matured_users = serializers.BooleanField(
        help_text="Default for counting only users whose metric window has fully passed."
    )
    cuped_enabled = serializers.BooleanField(help_text="Default for CUPED variance reduction on new experiments.")
    sequential_testing_enabled = serializers.BooleanField(
        help_text="Default for sequential testing. Applies only to the frequentist method."
    )
    flags_persistence_default = serializers.BooleanField(
        help_text=(
            "Default for persisting flag values across authentication steps on new flags. It becomes the flag's "
            "ensure_experience_continuity."
        )
    )
    test_account_filter_count = serializers.IntegerField(
        help_text="How many filters the team uses to identify internal and test users."
    )
    new_experiments_filter_test_accounts = serializers.BooleanField(
        help_text=(
            "A new experiment filters test accounts this way unless its own exposure criteria say otherwise. It "
            "does not follow the project's insight default."
        )
    )
    default_exposure_event = serializers.CharField(
        help_text=(
            "The exposure event a new experiment launched now counts by default: '$experiment_exposure' or "
            "'$feature_flag_called'."
        )
    )


class ExperimentSetupSdkLibSerializer(serializers.Serializer):
    lib = serializers.CharField(allow_null=True, help_text="The $lib value of the SDK, for example 'web'.")
    category = serializers.ChoiceField(
        choices=SdkLibCategory.choices,
        help_text="'web' for the JavaScript web SDK, 'mobile', 'server', or 'other' for libraries not classified.",
    )
    calls = serializers.IntegerField(help_text="Multivariate flag calls this SDK sent in the window.")
    distinct_ids = serializers.IntegerField(help_text="Distinct ids that sent those calls.")
    device_id_share = serializers.FloatField(
        help_text="Share of calls that carry a $device_id. 0 when this SDK never sends one, as server SDKs don't."
    )
    locally_evaluated_share = serializers.FloatField(
        allow_null=True,
        help_text=(
            "Share of calls evaluated locally in the SDK instead of by the flags service. Null when no call from "
            "this SDK reported it, as the web SDK doesn't."
        ),
    )
    anonymous_share = serializers.FloatField(
        allow_null=True,
        help_text=(
            "Share of distinct ids that were anonymous, among those that report whether they are identified. "
            "Null when no call from this SDK reported it."
        ),
    )


class ExperimentSetupLibActivitySerializer(serializers.Serializer):
    lib = serializers.CharField(allow_null=True, help_text="The $lib value of the SDK, for example 'web'.")
    category = serializers.ChoiceField(
        choices=SdkLibCategory.choices, help_text="'web', 'mobile', 'server', or 'other'."
    )
    events = serializers.IntegerField(help_text="Events this SDK sent in the window, of any kind.")
    distinct_ids = serializers.IntegerField(help_text="Distinct ids that sent those events.")


class ExperimentSetupSdkProfileSerializer(serializers.Serializer):
    window_days = serializers.IntegerField(help_text="Days of flag calls read, ending now.")
    source_event = serializers.CharField(
        help_text=(
            "The event read: '$experiment_exposure' when the project receives it, otherwise "
            "'$feature_flag_called'. Only one is read, because one copies the other, and only multivariate "
            "responses count either way. This says what the project's events carry today, so it can differ from "
            "team_defaults.default_exposure_event, which says what a new experiment would count."
        )
    )
    computed_at = serializers.DateTimeField(help_text="When the numbers were computed. They are cached for hours.")
    libs = ExperimentSetupSdkLibSerializer(many=True, help_text="One row per SDK, most calls first.")
    libs_truncated = serializers.BooleanField(help_text="True when more SDKs sent flag calls than libs lists.")
    flags_seen = serializers.IntegerField(help_text="Distinct multivariate flag keys called in the window.")
    flags_evaluated_on_server_and_web = serializers.IntegerField(
        help_text="How many of those flag keys were called by both a server SDK and the web SDK."
    )
    evaluated_on_server_and_web = serializers.BooleanField(
        help_text=(
            "True when at least one flag key was called by both a server SDK and the web SDK. The same flag "
            "decided on the server and read in the browser can bucket one user into two variants."
        )
    )
    libs_on_any_event = ExperimentSetupLibActivitySerializer(
        many=True,
        allow_null=True,
        help_text=(
            "Up to 10 SDKs seen on any event over the last day, most events first. Set only when libs is empty, "
            "so a project creating its first experiment still says which platforms it sends from. Null when flag "
            "calls exist, and null when this extra read timed out."
        ),
    )
    libs_on_any_event_truncated = serializers.BooleanField(
        help_text="True when more SDKs sent events than libs_on_any_event lists. False when it is null."
    )


class ExperimentSetupLibReachSerializer(serializers.Serializer):
    lib = serializers.CharField(allow_null=True, help_text="The $lib value that sent the target events.")
    category = serializers.ChoiceField(
        choices=SdkLibCategory.choices, help_text="'web', 'mobile', 'server', or 'other'."
    )
    unique_persons = serializers.IntegerField(help_text="Persons who sent the target event from this SDK.")
    anonymous_share = serializers.FloatField(
        allow_null=True,
        help_text=(
            "Among this SDK's distinct ids that report whether they are identified, the share that was "
            "anonymous. Null when no target event from this SDK reported it."
        ),
    )
    device_id_share = serializers.FloatField(
        help_text="Share of this SDK's target events that carry a $device_id. 0 when it never sends one."
    )


class ExperimentSetupTargetSurfaceSerializer(serializers.Serializer):
    window_days = serializers.IntegerField(help_text="Days of target events read, ending now.")
    source_event = serializers.CharField(help_text="The target event that was counted.")
    target_url_contains = serializers.CharField(allow_null=True, help_text="The URL filter that was applied, or null.")
    target_properties = ExperimentSetupPropertyFiltersField(
        help_text="The property filters that were applied to the target event. Empty when none were passed."
    )
    computed_at = serializers.DateTimeField(help_text="When the numbers were computed. They are cached for an hour.")
    test_accounts_filtered = serializers.BooleanField(
        help_text=(
            "Whether test accounts were left out. It follows the default a new experiment gets, so the counts "
            "match the population that experiment analyzes. False when the project defines no test-account filters."
        )
    )
    unique_persons = serializers.IntegerField(help_text="Persons who sent the target event in the window.")
    exposures_per_day_estimate = serializers.FloatField(
        help_text=(
            "unique_persons divided by window_days. Pass it as exposure_rate_per_day to "
            "experiment-calculate-running-time, scaled by the share of traffic the experiment will include."
        )
    )
    libs = ExperimentSetupLibReachSerializer(many=True, help_text="Up to 5 SDKs, most persons reached first.")
    libs_truncated = serializers.BooleanField(help_text="True when more SDKs sent target events than libs lists.")
    anonymous_share = serializers.FloatField(
        allow_null=True,
        help_text=(
            "Among all distinct ids that report whether they are identified, whichever SDK they came from, the "
            "share that was anonymous. Null when no target event reported it."
        ),
    )
    device_id_share = serializers.FloatField(
        allow_null=True,
        help_text="Share of all target events that carry a $device_id. Null when there were no target events.",
    )


class ExperimentSetupFunnelBaselineSerializer(serializers.Serializer):
    number_of_samples = serializers.IntegerField(help_text="Persons who reached the target.")
    sum = serializers.FloatField(help_text="Persons who converted.")
    step_counts = serializers.ListField(
        child=serializers.FloatField(), help_text="One entry: the persons who converted."
    )


class ExperimentSetupMeanCountBaselineSerializer(serializers.Serializer):
    number_of_samples = serializers.IntegerField(help_text="Persons who reached the target.")
    sum = serializers.FloatField(help_text="Metric events those persons sent in the whole window.")
    sum_squares = serializers.FloatField(help_text="Sum over persons of their metric event count squared.")


class ExperimentSetupCandidateMetricSerializer(serializers.Serializer):
    window_days = serializers.IntegerField(help_text="Days of events read, ending now.")
    source_event = serializers.CharField(help_text="The metric event that was counted.")
    metric_properties = ExperimentSetupPropertyFiltersField(
        help_text="The property filters that were applied to the metric event. Empty when none were passed."
    )
    target_event = serializers.CharField(
        allow_null=True, help_text="The target event the baseline starts from, or null when none was passed."
    )
    computed_at = serializers.DateTimeField(help_text="When the numbers were computed. They are cached for an hour.")
    test_accounts_filtered = serializers.BooleanField(
        help_text=(
            "Whether test accounts were left out. It follows the default a new experiment gets, so the baseline "
            "matches the population that experiment analyzes. False when the project defines no test-account "
            "filters."
        )
    )
    persons_reached = serializers.IntegerField(
        allow_null=True, help_text="Persons who sent the target event. Null without target_event."
    )
    persons_converted = serializers.IntegerField(
        allow_null=True,
        help_text="Persons who sent the metric event at or after their first target event. Null without target_event.",
    )
    conversion_rate = serializers.FloatField(
        allow_null=True, help_text="persons_converted divided by persons_reached. Null without target_event."
    )
    funnel_baseline_stats = ExperimentSetupFunnelBaselineSerializer(
        allow_null=True,
        help_text=(
            "Pass as baseline_stats to experiment-calculate-running-time with metric_type 'funnel'. Null without "
            "target_event."
        ),
    )
    mean_count_baseline_stats = ExperimentSetupMeanCountBaselineSerializer(
        allow_null=True,
        help_text=(
            "Pass as baseline_stats to experiment-calculate-running-time with metric_type 'mean_count'. It counts "
            "metric events in the whole window, not only after the first target event, so it can overstate the "
            "baseline. Null without target_event."
        ),
    )
    note = serializers.CharField(allow_null=True, help_text="What the mean count baseline counts.")
    event_volume = serializers.IntegerField(
        allow_null=True,
        help_text=(
            "Metric events in the window, with metric_properties applied. 0 means the event did not occur under "
            "those filters, so check the event name before you trust a conversion_rate of 0."
        ),
    )
    unique_persons = serializers.IntegerField(
        allow_null=True, help_text="Persons who sent the metric event, with metric_properties applied."
    )


class ExperimentSetupOutcomeSerializer(serializers.Serializer):
    metric_type = serializers.CharField(
        help_text=(
            "metric_type of the metric this outcome describes: 'funnel', 'mean', 'ratio', 'retention' or 'quantile'."
        )
    )
    metric_samples = serializers.IntegerField(
        allow_null=True,
        help_text=(
            "Units the result counted across all variants. What a unit is depends on metric_type, so read "
            "analyzed_exposures where you need exposures. Null when the result stores no sample counts."
        ),
    )
    analyzed_exposures = serializers.IntegerField(
        allow_null=True,
        help_text=(
            "metric_samples, but only where the metric type makes it the analyzed population: 'funnel' and "
            "'mean'. Users seen in several variants are left out under the default handling, so it can be lower "
            "than exposures. Null for 'retention', whose samples are the units that did the start event, and for "
            "'ratio', whose samples are not exposures either. Also null when the result stores no sample counts, "
            "which is not the same as analyzing nobody."
        ),
    )
    control_baseline_value = serializers.FloatField(
        allow_null=True,
        help_text=(
            "What control measured: a conversion rate for 'funnel', an average per unit for 'mean'. Compare it "
            "with the rate on the surface itself to see whether the exposure was diluted by users who never "
            "reached the surface. Null for other metric types and when control analyzed no units."
        ),
    )
    any_variant_significant = serializers.BooleanField(
        help_text="Whether any variant was significant on that metric in that result."
    )
    result_completed_at = serializers.DateTimeField(allow_null=True, help_text="When that result was computed.")
    result_data_through = serializers.DateTimeField(
        allow_null=True,
        help_text=(
            "The last moment the result covers. A backfill writes an older day with a recent completed_at, so "
            "this says how current the numbers are."
        ),
    )


class ExperimentSetupPreviousExperimentSerializer(serializers.Serializer):
    id = serializers.IntegerField(help_text="Experiment id.")
    name = serializers.CharField(help_text="Experiment name.")
    state = serializers.ChoiceField(
        choices=PreviousExperimentState.choices,
        help_text=(
            "'draft', 'running', 'paused' (running with its flag turned off), 'exposure_frozen' (running with "
            "enrollment closed to the already-exposed users) or 'stopped'."
        ),
    )
    created_at = serializers.DateTimeField(help_text="When the experiment was created.")
    start_date = serializers.DateTimeField(allow_null=True, help_text="When it launched. Null for drafts.")
    end_date = serializers.DateTimeField(allow_null=True, help_text="When it ended. Null unless stopped.")
    conclusion = serializers.CharField(
        allow_null=True, help_text="The recorded conclusion, for example 'won' or 'inconclusive', or null."
    )
    feature_flag_key = serializers.CharField(help_text="Key of the feature flag the experiment runs on.")
    variant_count = serializers.IntegerField(help_text="Variants on the flag, control included.")
    split_even = serializers.BooleanField(
        allow_null=True,
        help_text=(
            "Whether variants split traffic evenly, read from the flag as it stands now. 34/33/33 counts as "
            "even. Null on a boolean flag, which has no variants, and null when serving_single_variant is set."
        ),
    )
    serving_single_variant = serializers.CharField(
        allow_null=True,
        help_text=(
            "The one variant the flag now serves to everyone it matches, or null. Shipping a variant rewrites "
            "the flag this way, so the split the experiment ran with cannot be read from the flag any more. "
            "Only a launched experiment can be shipped, so a draft at 100/0 reports its split as it stands."
        ),
    )
    rollout_percentage = serializers.FloatField(
        allow_null=True,
        help_text="Rollout percentage of the flag's first release condition, read from the flag as it stands now.",
    )
    multiple_variant_handling = serializers.ChoiceField(
        choices=[handling.value for handling in MultipleVariantHandling],
        help_text="How users seen in several variants are analyzed, with the default resolved.",
    )
    multiple_variant_handling_set = serializers.BooleanField(
        help_text="Whether the experiment sets multiple_variant_handling itself instead of using the default."
    )
    ensure_experience_continuity = serializers.BooleanField(
        help_text=(
            "Whether the flag keeps a user's variant across authentication steps, read from the flag as it stands now."
        )
    )
    bucketing_identifier = serializers.CharField(
        help_text=(
            "What the flag buckets users on: 'distinct_id' (default) or 'device_id'. Read from the flag as it "
            "stands now."
        )
    )
    evaluation_runtime = serializers.CharField(
        help_text=("Where the flag may be evaluated: 'server', 'client' or 'all'. Read from the flag as it stands now.")
    )
    group_aggregation = serializers.BooleanField(help_text="Whether the flag buckets groups instead of persons.")
    custom_exposure_event = serializers.CharField(
        allow_null=True,
        help_text=(
            "An exposure event other than the default one, or null. A default event narrowed by "
            "exposure_property_filters is still the default event, so it stays null here."
        ),
    )
    custom_exposure_action_id = serializers.IntegerField(
        allow_null=True, help_text="Action used as the custom exposure, or null."
    )
    exposure_property_filters = ExperimentSetupStoredPropertyFiltersField(
        help_text=(
            "Property filters the exposure is narrowed by, whichever event it counts. An experiment that counts "
            "exposure only where $pathname is '/' is the precedent for a new test on that page. Any filter type "
            "can appear, cohorts included. Empty when the exposure is not narrowed."
        ),
    )
    activation_event = serializers.CharField(
        allow_null=True,
        help_text=(
            "Event a user must send after their first exposure event before they count as exposed, or null. "
            "This is activation mode, which sits on top of the default exposure event."
        ),
    )
    activation_action_id = serializers.IntegerField(
        allow_null=True, help_text="Action used for activation instead of an event, or null."
    )
    filter_test_accounts = serializers.BooleanField(help_text="Whether exposures leave out test accounts.")
    primary_metric_count = serializers.IntegerField(help_text="Primary metrics, shared ones included.")
    secondary_metric_count = serializers.IntegerField(help_text="Secondary metrics, shared ones included.")
    shared_metric_count = serializers.IntegerField(help_text="Shared metrics attached to the experiment.")
    primary_metric_types = serializers.ListField(
        child=serializers.CharField(),
        help_text=(
            "metric_type of each primary metric, for example 'mean', 'funnel', 'ratio', 'retention' or 'quantile'."
        ),
    )
    primary_metric_events = serializers.ListField(
        child=serializers.CharField(), help_text="Event names the primary metrics count."
    )
    primary_metric_action_ids = serializers.ListField(
        child=serializers.IntegerField(), help_text="Actions the primary metrics count."
    )
    minimum_detectable_effect = serializers.FloatField(
        allow_null=True, help_text="Minimum detectable effect saved from the running time calculator, or null."
    )
    stats_method = serializers.CharField(help_text="'bayesian' or 'frequentist'.")
    has_holdout = serializers.BooleanField(help_text="Whether the experiment uses a holdout group.")
    outcome = ExperimentSetupOutcomeSerializer(
        allow_null=True,
        help_text=(
            "From the completed result that covers the latest data under the experiment's current configuration. "
            "A funnel or a mean primary metric is chosen over a retention or a ratio one, because only its samples "
            "are the analyzed population. Null when no result exists for that configuration, for example after a "
            "relaunch or a settings edit until the results are recalculated, and for older metric definitions that "
            "results are never stored for."
        ),
    )


class ExperimentSetupPreviousExperimentsSummarySerializer(serializers.Serializer):
    total = serializers.IntegerField(help_text="Experiments listed.")
    launched = serializers.IntegerField(help_text="Listed experiments that launched.")
    launched_without_results = serializers.IntegerField(help_text="Launched experiments with no completed result.")
    launched_with_unknown_analyzed_exposures = serializers.IntegerField(
        help_text=(
            "Launched experiments whose result says nothing about exposures: it stores no sample counts, or its "
            "metric is a retention or a ratio one, whose samples are not exposures."
        )
    )
    launched_with_zero_analyzed_exposures = serializers.IntegerField(
        help_text="Launched experiments whose latest result analyzed no one."
    )
    launched_with_under_100_analyzed_exposures = serializers.IntegerField(
        help_text="Launched experiments whose latest result analyzed fewer than 100 units, zero included."
    )
    using_device_id_bucketing = serializers.IntegerField(help_text="Experiments that bucket on device id.")
    using_persistence = serializers.IntegerField(
        help_text="Experiments that keep variants across authentication steps."
    )
    using_custom_exposure = serializers.IntegerField(help_text="Experiments with a custom exposure event or action.")
    using_exposure_property_filters = serializers.IntegerField(
        help_text="Experiments whose exposure is narrowed by property filters."
    )
    using_activation = serializers.IntegerField(help_text="Experiments that use an activation event or action.")
    using_uneven_split = serializers.IntegerField(
        help_text=(
            "Experiments whose variants split traffic unevenly. A flag that now serves one variant is left out, "
            "because its split no longer says what the experiment ran with."
        )
    )
    serving_single_variant = serializers.IntegerField(
        help_text=(
            "Launched experiments whose flag now serves one variant to everyone it matches, usually after shipping."
        )
    )


class ExperimentSetupPreviousExperimentsSerializer(serializers.Serializer):
    experiments = ExperimentSetupPreviousExperimentSerializer(
        many=True,
        help_text=(
            "Most recently launched first, then drafts. Archived experiments are included, deleted ones are not."
        ),
    )
    summary = ExperimentSetupPreviousExperimentsSummarySerializer(help_text="Counts over the listed experiments.")


class ExperimentSetupSharedMetricSerializer(serializers.Serializer):
    id = serializers.IntegerField(help_text="Shared metric id, to attach it instead of creating an inline metric.")
    name = serializers.CharField(help_text="Shared metric name.")
    metric_type = serializers.CharField(
        allow_null=True,
        help_text="'mean', 'funnel', 'ratio', 'retention' or 'quantile', or null for older metrics.",
    )
    events = serializers.ListField(child=serializers.CharField(), help_text="Event names the metric counts.")
    action_ids = serializers.ListField(child=serializers.IntegerField(), help_text="Actions the metric counts.")
    used_as_primary = serializers.IntegerField(help_text="Experiments that use it as a primary metric.")
    used_as_secondary = serializers.IntegerField(help_text="Experiments that use it as a secondary metric.")
    last_used_at = serializers.DateTimeField(
        allow_null=True, help_text="When it was last attached to an experiment, or null."
    )
    matches_metric_event = serializers.BooleanField(
        allow_null=True,
        help_text=(
            "Whether the metric counts metric_event, directly or through an action. Null when no metric_event "
            "was passed."
        ),
    )
    metric_event_roles = serializers.ListField(
        child=serializers.CharField(),
        allow_null=True,
        help_text=(
            "Where metric_event sits in the metric: 'funnel_step' and 'funnel_final_step' for a funnel, "
            "'mean_source', 'quantile_source', 'ratio_numerator', 'ratio_denominator', 'retention_start' or "
            "'retention_completion'. A metric that only starts from the event is a different precedent from one "
            "that converts on it. Empty when the metric does not count it, and null when no metric_event was "
            "passed."
        ),
    )


class ExperimentSetupSharedMetricsSerializer(serializers.Serializer):
    metric_event = serializers.CharField(allow_null=True, help_text="The metric_event that was matched, or null.")
    metric_event_match_truncated = serializers.BooleanField(
        help_text=(
            "True when the project has more shared metrics than the event match could read, so a match further "
            "down the list may be missing. Matching is capped for cost."
        )
    )
    metrics = ExperimentSetupSharedMetricSerializer(
        many=True,
        help_text=(
            "Metrics that match metric_event first, then most reused. A use counts when it is on an experiment "
            "you can open and that is not deleted, so the counts follow your access."
        ),
    )


class ExperimentSetupTeamDefaultsSectionSerializer(serializers.Serializer):
    status = _section_status_field()
    # The serializer metaclass moves declared fields off the class, so `data` doesn't replace Serializer.data.
    data = ExperimentSetupTeamDefaultsSerializer(allow_null=True, help_text="The team's experiment defaults.")  # type: ignore[assignment]


class ExperimentSetupSdkProfileSectionSerializer(serializers.Serializer):
    status = _section_status_field()
    data = ExperimentSetupSdkProfileSerializer(  # type: ignore[assignment]
        allow_null=True, help_text="Which SDKs send multivariate flag calls, across the whole project."
    )


class ExperimentSetupTargetSurfaceSectionSerializer(serializers.Serializer):
    status = _section_status_field()
    data = ExperimentSetupTargetSurfaceSerializer(  # type: ignore[assignment]
        allow_null=True, help_text="Traffic on the target surface. Skipped without target_event."
    )


class ExperimentSetupCandidateMetricSectionSerializer(serializers.Serializer):
    status = _section_status_field()
    data = ExperimentSetupCandidateMetricSerializer(  # type: ignore[assignment]
        allow_null=True, help_text="Baseline of the candidate metric. Skipped without metric_event."
    )


class ExperimentSetupPreviousExperimentsSectionSerializer(serializers.Serializer):
    status = _section_status_field()
    data = ExperimentSetupPreviousExperimentsSerializer(  # type: ignore[assignment]
        allow_null=True, help_text="How the project's recent experiments were set up and how they went."
    )


class ExperimentSetupSharedMetricsSectionSerializer(serializers.Serializer):
    status = _section_status_field()
    data = ExperimentSetupSharedMetricsSerializer(allow_null=True, help_text="Shared metrics the project reuses.")  # type: ignore[assignment]


class ExperimentSetupContextResponseSerializer(serializers.Serializer):
    """Facts about the project that decide how to configure a new experiment. Facts only, no
    recommendations."""

    team_defaults = ExperimentSetupTeamDefaultsSectionSerializer(help_text="The project's experiment defaults.")
    sdk_profile = ExperimentSetupSdkProfileSectionSerializer(
        help_text="Which SDKs call feature flags and where flags are evaluated."
    )
    target_surface = ExperimentSetupTargetSurfaceSectionSerializer(help_text="Traffic on the surface under test.")
    candidate_metric = ExperimentSetupCandidateMetricSectionSerializer(
        help_text="Traffic and baseline of the candidate primary metric."
    )
    previous_experiments = ExperimentSetupPreviousExperimentsSectionSerializer(
        help_text="Recent experiments in the project."
    )
    shared_metrics = ExperimentSetupSharedMetricsSectionSerializer(help_text="Most reused shared metrics.")


class ExperimentHealthInputsProjectSerializer(serializers.Serializer):
    team_defaults = ExperimentSetupTeamDefaultsSectionSerializer(help_text="The project's experiment defaults.")
    sdk_profile = ExperimentSetupSdkProfileSectionSerializer(
        help_text=(
            "Which SDKs call feature flags and where flags are evaluated, across the whole project. Skipped for a "
            "reader who may not query events."
        )
    )
