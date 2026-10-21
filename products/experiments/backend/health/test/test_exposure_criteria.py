from dataclasses import replace
from typing import Any

from unittest import TestCase

from parameterized import parameterized

from posthog.schema import PropertyOperator

from products.experiments.backend.facade.contracts import ExperimentHealthFindingSeverity
from products.experiments.backend.health.checks.exposure_criteria import (
    EXPOSURE_EVENT_NOT_INGESTED,
    FILTER_ON_ANOTHER_FLAG,
    exposure_criteria_cannot_match,
)
from products.experiments.backend.health.context import ExposureEvents, FlagKeyFilter, HealthContext
from products.experiments.backend.health.test.factories import DRAFT, ENDED, RUNNING_CONTEXT

Severity = ExperimentHealthFindingSeverity
EXACT = PropertyOperator.EXACT


def _flag_filter(*values: str | float | bool, operator: PropertyOperator = EXACT, **changes: Any) -> HealthContext:
    events = ExposureEvents(
        custom_event=None,
        required_flag_key="checkout-test",
        flag_key_filters=(FlagKeyFilter(operator=operator, values=values),),
    )
    return replace(RUNNING_CONTEXT, exposure_events=events, **changes)


def _custom_event(received: dict[str, bool], **changes: Any) -> HealthContext:
    events = ExposureEvents(custom_event="checkout_viewed", required_flag_key=None, flag_key_filters=())
    return replace(RUNNING_CONTEXT, exposure_events=events, events_received=received, **changes)


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
            ("archived", _flag_filter("pricing-test", archived=True), None),
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
            ("custom_event_without_a_definition", _custom_event({}), None),
            ("custom_event_after_the_end", _custom_event({"checkout_viewed": False}, **ENDED), None),
        ]
    )
    def test_exposure_criteria_cannot_match(
        self, _name: str, ctx: HealthContext, expected: tuple[str, Severity] | None
    ) -> None:
        finding = exposure_criteria_cannot_match(ctx)

        self.assertEqual((finding.subcode, finding.severity) if finding else None, expected)
