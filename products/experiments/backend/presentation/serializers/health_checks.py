"""Serializers for the health check findings of an experiment and the inputs the checks read."""

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from products.experiments.backend.facade.contracts import (
    ExperimentHealthCheckKey,
    ExperimentHealthCheckStatus,
    ExperimentHealthFindingActionKind,
    ExperimentHealthFindingCode,
    ExperimentHealthFindingSeverity,
    ExperimentHealthFlagChangeKind,
    ExperimentHealthInputsTrafficStatus,
    ExperimentHealthMetricCompileErrorKind,
    ExperimentHealthRuleSide,
    ExperimentHealthRuleTest,
    ExperimentHealthValueKey,
    HealthExposureInputsStatus,
)
from products.feature_flags.backend.models.feature_flag import FeatureFlag

from . import setup_context


@extend_schema_field(
    {
        "type": "object",
        "additionalProperties": {
            "oneOf": [{"type": "string"}, {"type": "number"}, {"type": "boolean"}],
            "nullable": True,
        },
    }
)
class ExperimentHealthEvidenceField(serializers.DictField):
    pass


@extend_schema_field(
    {
        "type": "object",
        "additionalProperties": {
            "oneOf": [{"type": "string"}, {"type": "number"}, {"type": "boolean"}],
            "nullable": True,
        },
    }
)
class ExperimentHealthCheckValuesField(serializers.DictField):
    pass


class ExperimentHealthFindingSerializer(serializers.Serializer):
    code = serializers.ChoiceField(
        choices=ExperimentHealthFindingCode.choices,
        help_text="Stable identifier of the problem. Each code has one meaning across every surface that reports it.",
    )
    subcode = serializers.CharField(
        allow_null=True,
        help_text=(
            "The case within the code, when a code covers several, for example "
            "'running_but_no_rollout' within 'flag_off_while_running'. Null when the code has one case."
        ),
    )
    reason = serializers.CharField(
        allow_null=True,
        help_text=(
            "A stable qualifier below the subcode: where a sample ratio mismatch is located ('library', 'page'), "
            "what leaves nobody exposed ('test_account_filter'), what made a metric reach a query limit "
            "('metric', 'exposure_criteria'), or why a check could not read what it needs ('no_history_access'). "
            "Null when the finding names none."
        ),
    )
    severity = serializers.ChoiceField(
        choices=ExperimentHealthFindingSeverity.choices,
        help_text="How much the problem affects the results: critical, warning, or info.",
    )
    title = serializers.CharField(help_text="One-line summary of the problem.")
    detail = serializers.CharField(help_text="What is wrong, what it does to the experiment, and how to fix it.")
    evidence = ExperimentHealthEvidenceField(
        help_text=(
            "The values behind the finding, such as the key of a shipped variant or the share of users "
            "exposed to multiple variants. The keys depend on the code."
        ),
    )
    actions = serializers.ListField(
        child=serializers.ChoiceField(choices=ExperimentHealthFindingActionKind.choices),
        help_text=(
            "The actions that fix the problem, in order of preference, for example 'open_feature_flag' "
            "or 'add_primary_metric'."
        ),
    )
    diagnostic_ref = serializers.CharField(
        allow_null=True,
        help_text=(
            "The id of the matching diagnostic in the diagnosing-experiment-health skill, for example 'A5'. "
            "Null when the skill has none."
        ),
    )
    check = serializers.ChoiceField(
        choices=ExperimentHealthCheckKey.choices,
        help_text=(
            "The key of the check in `checks` that reported the finding. A check can report several codes, so the "
            "code doesn't name the check."
        ),
    )


class ExperimentHealthRuleMinimumSerializer(serializers.Serializer):
    value = serializers.ChoiceField(
        choices=ExperimentHealthValueKey.choices,
        help_text="The key in `values` that must reach the threshold before the check judges.",
    )
    threshold = serializers.FloatField(
        help_text="The value that the key must reach. Below it, the check reports no finding."
    )


class ExperimentHealthCheckRuleSerializer(serializers.Serializer):
    value = serializers.ChoiceField(
        choices=ExperimentHealthValueKey.choices,
        help_text="The key in `values` that the check compares with the threshold.",
    )
    threshold = serializers.FloatField(help_text="The threshold, in the unit that the suffix of the key gives.")
    warns = serializers.ChoiceField(
        choices=ExperimentHealthRuleSide.choices,
        help_text=(
            "above: the check reports a finding when the value is above the threshold. below: when the value is "
            "below it. A value at the threshold passes."
        ),
    )
    test = serializers.ChoiceField(
        choices=ExperimentHealthRuleTest.choices,
        allow_null=True,
        help_text="The statistical test that computes the value, for example chi_squared. Null for a count or a share.",
    )
    minimum = ExperimentHealthRuleMinimumSerializer(
        allow_null=True,
        help_text="What the check needs before it judges. Null when the check judges from the first value.",
    )


class ExperimentHealthCheckResultSerializer(serializers.Serializer):
    key = serializers.ChoiceField(
        choices=ExperimentHealthCheckKey.choices,
        help_text=(
            "Stable identifier of the check. A check can report several finding codes, so the key is not a "
            "finding code."
        ),
    )
    name = serializers.CharField(help_text="The problem the check looks for, for example 'Metrics not set up'.")
    description = serializers.CharField(
        help_text=("What the check looks for and why it matters. The same for every experiment and every status.")
    )
    status = serializers.ChoiceField(
        choices=ExperimentHealthCheckStatus.choices,
        help_text=(
            "passed: the check found no problem. finding: the check reported a finding in `findings`. "
            "not_applicable: the check does not cover the experiment's current state, for example a check of the "
            "changes since launch on a draft. not_checked: the check covers the experiment, but it could not read "
            "an input or it failed, so a problem it looks for can be present without a finding."
        ),
    )
    reason = serializers.CharField(
        allow_null=True,
        help_text=(
            "Why the check did not look, for the statuses not_applicable and not_checked, for example "
            "'Runs after launch'. Null for passed and finding."
        ),
    )
    values = ExperimentHealthCheckValuesField(
        help_text=(
            "What the check read on the experiment, for every status, as numbers, strings, booleans or null. Empty "
            "when the check read nothing or shows nothing. The suffix of a key gives the unit: _count is a count, "
            "_percentage is on the 0-100 scale, _hours is hours and _at is an ISO 8601 time in UTC. A key without a "
            "suffix is a setting or a state. A key means the same thing in every check. `rule.value` names the key "
            "that decides."
        ),
    )
    rule = ExperimentHealthCheckRuleSerializer(
        allow_null=True,
        help_text=(
            "How the check decides. The same for every experiment and every status. Null for a check without a "
            "numeric rule."
        ),
    )
    rows = serializers.ListField(
        child=ExperimentHealthCheckValuesField(),
        help_text=(
            "What the check read per variant, metric or feature flag change, one object each, with the keys and "
            "units of `values`. For example, the significance check gives each variant's difference and the smallest "
            "difference its sample can detect. Empty when the check reads no such list."
        ),
    )


class ExperimentHealthReleaseConditionSerializer(serializers.Serializer):
    rollout_percentage = serializers.FloatField(
        help_text="The share of the users matching the condition set's filters who get the flag, from 0 to 100.",
    )
    property_count = serializers.IntegerField(
        help_text="The number of filters a user must match, such as properties and cohorts. 0 matches all users.",
    )
    aggregation_group_type_index = serializers.IntegerField(
        allow_null=True,
        help_text=(
            "The group type the condition set assigns variants by: its own, or the flag's when it sets none. Null when "
            "it assigns them by user."
        ),
    )


class ExperimentHealthSetupSerializer(serializers.Serializer):
    release_conditions = ExperimentHealthReleaseConditionSerializer(
        many=True,
        help_text=(
            "The flag's condition sets as stored, in the order the flag evaluates them. Whether a set can serve a "
            "request depends on the sets before it and on `early_exit`."
        ),
    )
    early_exit = serializers.BooleanField(
        help_text=(
            "Whether the flag stops at the first condition set whose filters match, also when its rollout leaves the "
            "user out. Otherwise such a user goes on to the next set."
        ),
    )
    bucketing_identifier = serializers.ChoiceField(
        choices=FeatureFlag.BUCKETING_IDENTIFIER_CHOICES,
        help_text="The flag's `bucketing_identifier`. Null on the flag reads as distinct_id.",
    )
    aggregation_group_type_index = serializers.IntegerField(
        allow_null=True,
        help_text=(
            "The flag's own group type, which the exposure counts and the results use. A condition set can override "
            "it. Null for users."
        ),
    )
    evaluation_runtime = serializers.ChoiceField(
        choices=FeatureFlag.EVALUATION_RUNTIME_CHOICES,
        help_text="The flag's `evaluation_runtime`. Null on the flag reads as all.",
    )
    evaluation_contexts = serializers.ListField(
        child=serializers.CharField(),
        help_text=(
            "The names of the flag's evaluation contexts. When PostHog evaluates the flag, an SDK that sends evaluation "
            "contexts gets it only when it sends one of these, and an SDK that sends none gets it. Empty when the flag "
            "has none."
        ),
    )
    ensure_experience_continuity = serializers.BooleanField(
        help_text="The flag's 'Persist flag across authentication steps' setting.",
    )


class ExperimentHealthSerializer(serializers.Serializer):
    findings = ExperimentHealthFindingSerializer(
        many=True,
        help_text=(
            "Problems that the health checks found in the experiment's configuration and its feature flag. "
            "Empty when no check found a problem. An empty list does not mean that every check ran: read `checks`."
        ),
    )
    checks = ExperimentHealthCheckResultSerializer(
        many=True,
        help_text=(
            "The result of each health check, in the order the checks run. The checks that read the exposure "
            "counts are not here: the exposure query returns them as `health_checks`."
        ),
    )
    setup = ExperimentHealthSetupSerializer(
        required=False,
        allow_null=True,
        help_text=(
            "The settings of the experiment's flag that decide which variant a user gets. Null when the experiment "
            "has no flag."
        ),
    )


class ExperimentHealthInputsVariantSerializer(serializers.Serializer):
    key = serializers.CharField(allow_null=True, help_text="The variant key. Null when the flag stores no string key.")
    rollout_percentage = serializers.FloatField(
        allow_null=True, help_text="The variant's share of the split, in percent. Null when the flag stores no number."
    )


class ExperimentHealthInputsReleaseConditionSerializer(serializers.Serializer):
    number = serializers.IntegerField(
        help_text="The condition's position in the flag, from 1, as the flag page labels it ('Set 2')."
    )
    rollout_percentage = serializers.FloatField(
        allow_null=True, help_text="The condition's rollout, in percent. Null when the flag stores no number."
    )
    property_count = serializers.IntegerField(
        allow_null=True, help_text="The number of property filters. Null when the flag stores no list."
    )
    reachable = serializers.BooleanField(
        help_text="Whether the condition can serve a request. A condition after one that matches everyone never does."
    )
    pinned_variant = serializers.CharField(
        allow_null=True,
        help_text=(
            "The variant that the condition's override serves. Null when the condition is not reachable, has no "
            "override, or its override names no variant of the flag."
        ),
    )


class ExperimentHealthInputsFlagSerializer(serializers.Serializer):
    active = serializers.BooleanField(help_text="Whether the flag is enabled.")
    deleted = serializers.BooleanField(help_text="Whether the flag is deleted.")
    release_conditions = ExperimentHealthInputsReleaseConditionSerializer(
        many=True, help_text="The flag's release conditions, in evaluation order."
    )
    variants = ExperimentHealthInputsVariantSerializer(many=True, help_text="The flag's variants and their split.")
    split_text = serializers.CharField(
        help_text="The split as text, in the form of a change's before and after, such as 'control 50%, test 50%'."
    )


_COUNTED_HELP = (
    "Whether the checks count this change: every change counts from the first change, of any kind, with an "
    "exposure before it, or an unknown answer. False for every change when not checked."
)

_FLAG_CHANGE_KIND_HELP = (
    "The kind of change. A bucketing change is a change of a setting that decides the variant draw."
)


class ExperimentHealthInputsFlagChangeSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=ExperimentHealthFlagChangeKind.choices, help_text=_FLAG_CHANGE_KIND_HELP)
    changed_at = serializers.DateTimeField(help_text="When the flag changed.")
    changed = serializers.CharField(help_text="What changed, as the staff view names it, such as 'Split' or 'Key'.")
    before = serializers.CharField(
        help_text="The value before the change as text, such as 'control 50%, test 50%' or 'device_id'. 'none' when unset."
    )
    after = serializers.CharField(help_text="The value after the change, in the same form.")
    counted = serializers.BooleanField(help_text=_COUNTED_HELP)


class ExperimentHealthInputsExposedBetweenSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=ExperimentHealthFlagChangeKind.choices, help_text=_FLAG_CHANGE_KIND_HELP)
    question = serializers.CharField(help_text="What was asked, as the staff view names it.")
    exposed = serializers.BooleanField(
        allow_null=True,
        help_text=(
            "Whether anyone was exposed between the first and the last counted change of this kind. Asked only when "
            "the last sets back what the first changed. Null when not asked or unknown."
        ),
    )


class ExperimentHealthInputsFlagHistorySerializer(serializers.Serializer):
    checked = serializers.BooleanField(
        help_text="Whether the changes were compared with the exposures. False when not_checked_reason is set."
    )
    not_checked_reason = serializers.CharField(
        allow_null=True,
        help_text=(
            "Why the changes were not compared with the exposures: 'no_history_access', 'no_query_access', "
            "'exposure_filters', 'exposure_action', 'exposure_criteria', 'too_many_saves' or "
            "'too_many_conditions'. Null when they were."
        ),
    )
    start_date = serializers.DateTimeField(
        help_text="The experiment's start date. The flag history counts changes from it, as the results count exposures from it."
    )
    team_timezone = serializers.CharField(help_text="The project's time zone, which the findings use for times.")
    changes = ExperimentHealthInputsFlagChangeSerializer(
        many=True,
        help_text=(
            "Every change since launch that can move exposed people, of every kind, in time order. A bucketing change "
            "is one per setting and save. A rollout change alone is no release-condition change. Empty for "
            "'no_history_access', which does not read them."
        ),
    )
    exposed_before_first = serializers.BooleanField(
        allow_null=True,
        help_text="Whether anyone was exposed before the first counted change. Null when unknown or not checked.",
    )
    exposed_between = ExperimentHealthInputsExposedBetweenSerializer(
        many=True, help_text="One entry for each kind of change with a counted change, in the order of the kinds."
    )


class ExperimentHealthInputsConditionSetPeopleSerializer(serializers.Serializer):
    condition_set = serializers.IntegerField(help_text="The number of the release condition, from 1.")
    people = serializers.IntegerField(help_text="The people whose latest call this condition served.")


class ExperimentHealthInputsConditionSetTrafficSerializer(serializers.Serializer):
    since = serializers.DateTimeField(
        help_text="The start of the window: the latest of launch, the flag's last save and 7 days ago."
    )
    team_timezone = serializers.CharField(help_text="The project's time zone, which the finding uses for times.")
    people_by_set = ExperimentHealthInputsConditionSetPeopleSerializer(
        many=True, help_text="People by the release condition that served their latest call of the flag's version."
    )
    calls = serializers.IntegerField(help_text="The flag's calls in the window, of any flag version.")
    remotely_evaluated_calls = serializers.IntegerField(
        help_text=(
            "The calls that the flag service evaluated. Only those name a condition set. Local evaluation in a "
            "server SDK and a bootstrapped value name none."
        )
    )
    people_assigned_outside = serializers.IntegerField(
        help_text=(
            "The people who got a variant from a call without a flag version that is no local evaluation in a server "
            "SDK, from an hour after the start of the window: a bootstrap or the caller's own assignment. With a 0% "
            "rollout, 10 or more of them turn `running_but_no_rollout` into `assigned_outside_flag_service`."
        )
    )


class ExperimentHealthInputsExposureEventsSerializer(serializers.Serializer):
    custom_event = serializers.CharField(
        allow_null=True,
        help_text="The event the exposure criteria count in place of the flag calls. Null for flag calls or an action.",
    )
    required_flag_key = serializers.CharField(
        allow_null=True,
        help_text="The flag key the exposure query requires on the flag call events. Null for a custom event or an action.",
    )
    variant_property = serializers.CharField(help_text="The event property that holds the variant.")
    activation = serializers.CharField(
        allow_null=True,
        help_text=(
            "The event, or the action's name, that has to follow a user's flag call before the user counts. Null "
            "without an activation."
        ),
    )


class ExperimentHealthInputsMetricCompileFailureSerializer(serializers.Serializer):
    name = serializers.CharField(help_text="The metric's name as the experiment shows it.")
    role = serializers.CharField(help_text="'primary' or 'secondary'.")
    kind = serializers.ChoiceField(
        choices=ExperimentHealthMetricCompileErrorKind.choices,
        help_text=(
            "Who rejected the query: 'rejected' is a validation of the query builder, 'syntax' and 'query' come "
            "from HogQL, 'definition' means the stored definition doesn't parse into a metric."
        ),
    )
    message = serializers.CharField(
        allow_null=True,
        help_text=(
            "The compiler's message, without the list of a scope's fields. Null when it can hold the evaluation rules "
            "that the AI evaluation markers keep out of the browser."
        ),
    )


class ExperimentHealthInputsMetricCompilesSerializer(serializers.Serializer):
    metric_count = serializers.IntegerField(help_text="The metrics that the experiment calculates, one per uuid.")
    unknown_count = serializers.IntegerField(
        help_text="The metrics whose compile raised an error that names no problem of the metric, such as a defect."
    )
    no_access_count = serializers.IntegerField(
        help_text="The metrics that read a warehouse table or view that the reader may not query, so they aren't checked."
    )
    exposure_query_fails = serializers.BooleanField(
        help_text=(
            "Whether the exposure query alone doesn't compile. Every metric then fails for that reason, so no "
            "failure is listed."
        )
    )
    failures = ExperimentHealthInputsMetricCompileFailureSerializer(
        many=True, help_text="The metrics whose query doesn't compile, with the compiler's message."
    )


class ExperimentHealthInputsMetricCalculationFailureSerializer(serializers.Serializer):
    name = serializers.CharField(help_text="The metric's name as the experiment shows it.")
    role = serializers.CharField(help_text="'primary' or 'secondary'.")
    error_type = serializers.CharField(
        allow_null=True,
        help_text=(
            "The class that the calculation stored for the error, such as 'timeout' or 'rate_limited'. Null for a "
            "failure stored without a class."
        ),
    )
    step = serializers.CharField(
        allow_null=True,
        help_text="The step of the calculation that failed, such as 'calculation'. Null when the failure names none.",
    )
    retriable = serializers.BooleanField(
        help_text=(
            "Whether the results page shows a button to try the metric again, which it does for a retriable error."
        )
    )
    message = serializers.CharField(
        allow_null=True,
        help_text=(
            "The stored message as the results page shows it, without the names that HogQL suggests and the list of "
            "a scope's fields. Null when it can hold evaluation rules that the AI evaluation markers keep out of the "
            "browser."
        ),
    )


class ExperimentHealthInputsZeroMetricSerializer(serializers.Serializer):
    name = serializers.CharField(help_text="The name of the metric, as the results page shows it.")
    role = serializers.CharField(help_text="Whether the metric is a primary or a secondary metric of the experiment.")
    exposures = serializers.IntegerField(help_text="The persons or groups of the result, across the variants.")
    ratio_side = serializers.CharField(
        allow_null=True,
        help_text="The side of a ratio that reads zero. Each side that reads zero has its own entry. Null for the other "
        "metric types.",
    )
    stopped_events = serializers.ListField(
        child=serializers.CharField(),
        help_text="The events of the metric that the project last received before launch.",
    )


class ExperimentHealthInputsLatestCalculationSerializer(serializers.Serializer):
    finished_at = serializers.DateTimeField(
        allow_null=True,
        help_text="When the latest calculation that the results page shows finished. Null when none has finished.",
    )
    failures = ExperimentHealthInputsMetricCalculationFailureSerializer(
        many=True, help_text="The metrics whose latest calculation failed, with the error that the results page shows."
    )
    hours_of_data = serializers.FloatField(
        allow_null=True,
        help_text="The hours from launch to the end of the data of this calculation. Null when none has finished.",
    )
    zero_metrics = ExperimentHealthInputsZeroMetricSerializer(
        many=True, help_text="The metrics that read zero in every variant in this calculation."
    )


class ExperimentHealthInputsReaderAccessSerializer(serializers.Serializer):
    can_read_flag_history = serializers.BooleanField(
        help_text="Whether the reader may read the flag's history, which the flag-change checks need."
    )
    can_query_events = serializers.BooleanField(
        help_text="Whether the reader may query events, which the flag-change and forced-variant checks need."
    )
    denied_event_properties = serializers.ListField(
        child=serializers.CharField(),
        help_text=(
            "Event properties the reader is denied. The forced-variant and release-condition checks skip their scan "
            "when one of them is a flag call property it reads."
        ),
    )


class ExperimentHealthInputsExposureTotalsSerializer(serializers.Serializer):
    total_exposures = serializers.DictField(
        child=serializers.IntegerField(),
        help_text="Exposed people by variant. '$multiple' counts the people exposed to more than one variant.",
    )
    multiple_variant_handling = serializers.CharField(
        help_text="How the analysis treats people in several variants: 'exclude' or 'first_seen'."
    )
    sample_ratio_mismatch_p_value = serializers.FloatField(
        allow_null=True, help_text="The p-value of the sample ratio test. Null when there was too little data."
    )
    hours_since_launch = serializers.FloatField(
        allow_null=True, help_text="Hours from launch to the computation of the answer, as the checks read them."
    )


class ExperimentHealthInputsExposuresSerializer(serializers.Serializer):
    status = serializers.ChoiceField(
        choices=HealthExposureInputsStatus.choices,
        help_text=(
            "Whether a cached answer was read. 'calculating' means no answer is cached and a calculation runs in the "
            "background, so a later request reads a fresh answer. 'stale' means the cached answer is past its age: a "
            "recalculation runs in the background, or the last one failed and 'error' says why. After a failed "
            "calculation, no new one starts for 20 minutes."
        ),
    )
    computed_at = serializers.DateTimeField(allow_null=True, help_text="When the answer was computed.")
    totals = ExperimentHealthInputsExposureTotalsSerializer(
        allow_null=True, help_text="What the exposure checks read. Null without an answer."
    )
    findings = ExperimentHealthFindingSerializer(
        many=True, help_text="The findings of the exposure checks on this answer: zero exposures, SRM and bias risk."
    )
    error = serializers.CharField(
        allow_null=True,
        help_text=(
            "Why the query or its last background calculation failed. Set for 'failed', and for 'stale' when the "
            "recalculation failed."
        ),
    )


class ExperimentHealthInputsSerializer(serializers.Serializer):
    is_launched = serializers.BooleanField(help_text="Whether the experiment has a start date.")
    is_running = serializers.BooleanField(help_text="Whether the experiment is launched and not ended.")
    has_ended = serializers.BooleanField(help_text="Whether the experiment has an end date.")
    is_paused = serializers.BooleanField(help_text="Whether the experiment is paused.")
    archived = serializers.BooleanField(help_text="Whether the experiment is archived.")
    baseline_variant_key = serializers.CharField(
        allow_null=True, help_text="The baseline set in the experiment's settings. Null when unset."
    )
    excluded_variant_keys = serializers.ListField(
        child=serializers.CharField(),
        help_text=(
            "The variants the analysis leaves out of the results. The forced-variant check ignores pins to them."
        ),
    )
    primary_metric_count = serializers.IntegerField(
        help_text="Single-use primary metrics plus shared metrics linked as primary."
    )
    secondary_metric_count = serializers.IntegerField(
        help_text="Single-use secondary metrics plus shared metrics linked as secondary."
    )
    flag = ExperimentHealthInputsFlagSerializer(
        allow_null=True, help_text="The experiment's feature flag. Null when it has none."
    )
    flag_last_called_at = serializers.DateTimeField(
        allow_null=True,
        help_text=(
            "The flag's latest recorded call, which a periodic sync of the flag call events sets. Null when the "
            "experiment has no flag, or the flag has no recorded call."
        ),
    )
    flag_called = serializers.BooleanField(
        allow_null=True,
        help_text=(
            "Whether PostHog has recorded any call of the flag. The flag traffic check reads it on a draft. Null when "
            "the experiment has no flag, or the organization's flag calls are stored where the checks can't read them."
        ),
    )
    flag_called_during_run = serializers.BooleanField(
        allow_null=True,
        help_text=(
            "Whether PostHog has recorded a call of the flag between launch and the end, or until now. The zero "
            "exposures check reads it to say whether the flag is called. Null before launch, after a latest call that "
            "came after the end, or when the organization's flag calls can't be read."
        ),
    )
    flag_called_after_end = serializers.BooleanField(
        allow_null=True,
        help_text=(
            "Whether PostHog has recorded a call of the flag after the end and within the last 3 days. The flag "
            "state check reads it on an ended experiment whose flag is still active with multiple variants. False "
            "only once 3 days have passed since the end. Null before the end, before those 3 days are over without a "
            "call, or when the organization's flag calls can't be read."
        ),
    )
    exposure_events = ExperimentHealthInputsExposureEventsSerializer(
        allow_null=True,
        help_text="The events the exposure criteria count. Null when the stored exposure criteria don't parse.",
    )
    events_received = serializers.DictField(
        child=serializers.BooleanField(),
        help_text=(
            "Whether the project has received each event that the metrics and the exposure criteria name, by event "
            "name. A name that ingestion keeps no record of is absent."
        ),
    )
    metric_compiles = ExperimentHealthInputsMetricCompilesSerializer(
        allow_null=True,
        help_text=(
            "The compile of each metric's query without running it, as the reader, which the 'Invalid metric "
            "definitions' check reads. A metric that compiles is cached per reader for a day, and a failing metric "
            "compiles again on every request. Null when the compile itself failed."
        ),
    )
    latest_calculation = ExperimentHealthInputsLatestCalculationSerializer(
        allow_null=True,
        help_text=(
            "The latest finished calculation of the metrics, which the metric results check reads. Null before "
            "launch, on an archived experiment, or when the read failed."
        ),
    )
    flag_history = ExperimentHealthInputsFlagHistorySerializer(
        allow_null=True,
        help_text=(
            "The changes of the flag since launch that can move exposed people. Null when the experiment is not "
            "running, is archived, its flag is missing or deleted, or the read failed."
        ),
    )
    condition_set_traffic_status = serializers.ChoiceField(
        choices=ExperimentHealthInputsTrafficStatus.choices,
        help_text=(
            "Whether the condition-set traffic was read, or why not. The forced-variant check needs it when the "
            "experiment is launched and some but not all release conditions pin a variant that has a share of the "
            "split and is not excluded from the analysis. The release-condition check needs it when such an "
            "override was removed after launch."
        ),
    )
    condition_set_traffic = ExperimentHealthInputsConditionSetTrafficSerializer(
        allow_null=True,
        help_text="The flag's recent calls by condition set. Null unless condition_set_traffic_status is 'read'.",
    )
    reader_access = ExperimentHealthInputsReaderAccessSerializer(
        help_text="What the reader may read, which decides what the checks can load."
    )
    exposures = ExperimentHealthInputsExposuresSerializer(
        help_text="The exposure query's answer that the exposure checks read, from the cache."
    )
    project = setup_context.ExperimentHealthInputsProjectSerializer(
        help_text="Facts about the project that no check reads yet, from the same providers as the setup context."
    )
