from dataclasses import replace
from typing import Any

from unittest import TestCase

from parameterized import parameterized

from posthog.schema import PropertyOperator

from products.experiments.backend.facade.contracts import ExperimentHealthFinding, ExperimentHealthFindingSeverity
from products.experiments.backend.health.checks.exposure_criteria import (
    EXPOSURE_EVENT_NOT_INGESTED,
    FILTER_ON_ANOTHER_FLAG,
    FILTER_ON_PROPERTY_NOT_INGESTED,
    exposure_criteria_cannot_match,
)
from products.experiments.backend.health.context import (
    ExposureEvents,
    ExposurePropertyFilter,
    ExposurePropertyType,
    FlagKeyFilter,
    FlagState,
    HealthContext,
)
from products.experiments.backend.health.skips import (
    NOT_AFTER_END,
    NOT_ON_ARCHIVED,
    CheckSkip,
    not_applicable,
    not_checked,
)
from products.experiments.backend.health.test.factories import DRAFT, ENDED, RUNNING_CONTEXT

Severity = ExperimentHealthFindingSeverity
EXACT = PropertyOperator.EXACT


def _flag_filter(*values: str | float | bool, operator: PropertyOperator = EXACT, **changes: Any) -> HealthContext:
    events = ExposureEvents(
        custom_event=None,
        required_flag_key="checkout-test",
        variant_property="$feature_flag_response",
        flag_key_filters=(FlagKeyFilter(operator=operator, values=values),),
    )
    return replace(RUNNING_CONTEXT, exposure_events=events, **changes)


def _custom_event(received: dict[str, bool], **changes: Any) -> HealthContext:
    events = ExposureEvents(
        custom_event="checkout_viewed",
        required_flag_key=None,
        variant_property="$feature/checkout-test",
        flag_key_filters=(),
    )
    return replace(RUNNING_CONTEXT, exposure_events=events, events_received=received, **changes)


FLAG = FlagState(active=True, deleted=False, release_groups=(), variants=(), reachable_conditions=())


def _property_filter(
    received: bool | None,
    operator: PropertyOperator = EXACT,
    values: tuple[str | float | bool, ...] | None = ("pro",),
    *,
    property_type: ExposurePropertyType = "person",
    custom_event: str | None = None,
    action: bool = False,
    **changes: Any,
) -> HealthContext:
    events = ExposureEvents(
        custom_event=custom_event,
        required_flag_key=None if custom_event or action else "checkout-test",
        variant_property="$feature/checkout-test" if custom_event or action else "$feature_flag_response",
        flag_key_filters=(),
        property_filters=(
            ExposurePropertyFilter(
                type=property_type,
                key="plan",
                operator=operator,
                values=values,
                event=None if action else custom_event or "$feature_flag_called",
            ),
        ),
    )
    return replace(
        RUNNING_CONTEXT,
        flag=FLAG,
        exposure_events=events,
        exposure_properties_received={} if received is None else {(property_type, "plan"): received},
        **changes,
    )


NOT_CHECKED_PROPERTY = not_checked(
    "Couldn't check because PostHog can't tell whether the project received a filter's property"
)


Op = PropertyOperator
# Every operator in one of the two sets, so that a new operator fails the test until someone reads how
# `property_to_expr` compiles it for a missing property.
FAILS_A_MISSING_PROPERTY = {
    Op.EXACT,
    Op.ICONTAINS,
    Op.ICONTAINS_MULTI,
    Op.STARTS_WITH,
    Op.ENDS_WITH,
    Op.REGEX,
    Op.GT,
    Op.GTE,
    Op.LT,
    Op.LTE,
    Op.MIN,
    Op.MAX,
    Op.IS_SET,
    Op.IS_DATE_EXACT,
    Op.IS_DATE_BEFORE,
    Op.IS_DATE_AFTER,
    Op.BETWEEN,
    Op.IN_,
    Op.IS_CLEANED_PATH_EXACT,
    Op.SEMVER_EQ,
    Op.SEMVER_GT,
    Op.SEMVER_GTE,
    Op.SEMVER_LT,
    Op.SEMVER_LTE,
    Op.SEMVER_TILDE,
    Op.SEMVER_CARET,
    Op.SEMVER_WILDCARD,
}
PASSES_A_MISSING_PROPERTY = {
    Op.IS_NOT,
    Op.NOT_ICONTAINS,
    Op.NOT_ICONTAINS_MULTI,
    Op.NOT_STARTS_WITH,
    Op.NOT_ENDS_WITH,
    Op.NOT_REGEX,
    Op.IS_NOT_SET,
    Op.NOT_BETWEEN,
    Op.NOT_IN,
    Op.IS_CLEANED_PATH_NOT_EXACT,
    Op.SEMVER_NEQ,
    Op.FLAG_EVALUATES_TO,
}


class TestFailsWhenMissing(TestCase):
    @parameterized.expand([(operator.value, operator) for operator in PropertyOperator])
    def test_fails_when_missing(self, _name: str, operator: PropertyOperator) -> None:
        self.assertIn(operator, FAILS_A_MISSING_PROPERTY | PASSES_A_MISSING_PROPERTY)
        property_filter = ExposurePropertyFilter(
            type="event", key="plan", operator=operator, values=("pro",), event="$feature_flag_called"
        )

        self.assertEqual(property_filter.fails_when_missing, operator in FAILS_A_MISSING_PROPERTY)


class TestExposureCriteriaCannotMatch(TestCase):
    @parameterized.expand(
        [
            ("another_flag", _flag_filter("pricing-test"), (FILTER_ON_ANOTHER_FLAG, Severity.WARNING)),
            (
                "another_flag_in_a_draft",
                _flag_filter("pricing-test", **DRAFT),
                (FILTER_ON_ANOTHER_FLAG, Severity.WARNING),
            ),
            (
                "another_flag_after_the_end",
                _flag_filter("pricing-test", **ENDED),
                (FILTER_ON_ANOTHER_FLAG, Severity.WARNING),
            ),
            ("one_value_is_the_flag", _flag_filter("pricing-test", "checkout-test"), None),
            ("the_key_in_another_case", _flag_filter("Checkout-Test"), (FILTER_ON_ANOTHER_FLAG, Severity.WARNING)),
            ("no_values_match_every_event", _flag_filter(), None),
            ("a_number_can_be_converted", _flag_filter(7), None),
            ("not_exact", _flag_filter("pricing-test", operator=PropertyOperator.IS_NOT), None),
            ("archived", _flag_filter("pricing-test", archived=True), not_applicable(NOT_ON_ARCHIVED)),
            (
                "custom_event_in_a_draft",
                _custom_event({"checkout_viewed": False}, **DRAFT, hours_since_launch=None),
                (EXPOSURE_EVENT_NOT_INGESTED, Severity.INFO),
            ),
            (
                "custom_event_in_the_first_day",
                _custom_event({"checkout_viewed": False}, hours_since_launch=23.9),
                (EXPOSURE_EVENT_NOT_INGESTED, Severity.INFO),
            ),
            (
                "custom_event_a_day_after_launch",
                _custom_event({"checkout_viewed": False}, hours_since_launch=24),
                (EXPOSURE_EVENT_NOT_INGESTED, Severity.WARNING),
            ),
            ("custom_event_received", _custom_event({"checkout_viewed": True}), None),
            (
                "custom_event_without_a_definition",
                _custom_event({}),
                not_checked("Couldn't check because PostHog keeps no record of this event name"),
            ),
            (
                "custom_event_after_the_end",
                _custom_event({"checkout_viewed": False}, **ENDED),
                not_applicable(NOT_AFTER_END),
            ),
            ("property_not_received", _property_filter(False), (FILTER_ON_PROPERTY_NOT_INGESTED, Severity.WARNING)),
            (
                "property_not_received_in_a_draft",
                _property_filter(False, **DRAFT),
                (FILTER_ON_PROPERTY_NOT_INGESTED, Severity.INFO),
            ),
            (
                "property_not_received_after_the_end",
                _property_filter(False, **ENDED),
                (FILTER_ON_PROPERTY_NOT_INGESTED, Severity.WARNING),
            ),
            (
                "property_not_received_after_the_end_of_a_custom_event",
                _property_filter(False, custom_event="checkout_viewed", **ENDED),
                (FILTER_ON_PROPERTY_NOT_INGESTED, Severity.WARNING),
            ),
            (
                "person_property_not_received_on_an_action",
                _property_filter(False, action=True),
                (FILTER_ON_PROPERTY_NOT_INGESTED, Severity.WARNING),
            ),
            (
                "event_property_on_an_action",
                _property_filter(False, property_type="event", action=True),
                NOT_CHECKED_PROPERTY,
            ),
            (
                "event_property_of_a_group_identify_event",
                _property_filter(
                    False,
                    property_type="event",
                    custom_event="$groupidentify",
                    events_received={"$groupidentify": True},
                ),
                NOT_CHECKED_PROPERTY,
            ),
            (
                "is_set_without_a_value",
                _property_filter(False, PropertyOperator.IS_SET, None),
                (FILTER_ON_PROPERTY_NOT_INGESTED, Severity.WARNING),
            ),
            ("property_received", _property_filter(True), None),
            ("a_missing_property_passes_a_negated_filter", _property_filter(False, PropertyOperator.IS_NOT), None),
            ("an_empty_list_matches_every_event", _property_filter(False, values=()), None),
            ("is_set_with_an_empty_list", _property_filter(False, PropertyOperator.IS_SET, ()), None),
            ("exact_without_a_value_matches_a_missing_property", _property_filter(False, values=None), None),
            ("property_without_a_definition", _property_filter(None), NOT_CHECKED_PROPERTY),
            (
                "custom_event_after_the_end_with_a_received_property",
                _property_filter(True, custom_event="checkout_viewed", **ENDED),
                None,
            ),
        ]
    )
    def test_exposure_criteria_cannot_match(
        self, _name: str, ctx: HealthContext, expected: tuple[str, Severity] | CheckSkip | None
    ) -> None:
        outcome = exposure_criteria_cannot_match(ctx)

        actual = (outcome.subcode, outcome.severity) if isinstance(outcome, ExperimentHealthFinding) else outcome
        self.assertEqual(actual, expected)
