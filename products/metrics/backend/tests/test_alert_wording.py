from datetime import UTC, datetime

from django.test import SimpleTestCase

from parameterized import parameterized

from products.alerts_platform.backend.facade.contracts import AlertEventKind, AnnouncedTransition
from products.metrics.backend.alerts.wording import describe_transition

THRESHOLD = {"kind": "threshold", "operator": "lt", "threshold": 1}


def _transition(value: float | None, condition: dict[str, object]) -> AnnouncedTransition:
    return AnnouncedTransition(
        grouping_key="",
        kind=AlertEventKind.FIRING,
        episode_started_at=datetime(2026, 1, 1, tzinfo=UTC),
        value=value,
        labels={},
        condition=condition,
        source_config={"query": 'up{job="exporter"}'},
        error_message=None,
        occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


class TestMetricsAlertWording(SimpleTestCase):
    @parameterized.expand(
        [
            ("a_missing_series", None, THRESHOLD, [("Data", "The query returned no series"), ("Threshold", "< 1")]),
            ("a_reported_value", 0.0, THRESHOLD, [("Value", "0"), ("Threshold", "< 1")]),
            ("a_present_series_with_no_number", None, {"kind": "present"}, []),
        ]
    )
    def test_a_firing_says_whether_the_series_reported(
        self, _name: str, value: float | None, condition: dict[str, object], expected: list[tuple[str, str]]
    ) -> None:
        details = describe_transition(project_id=1, transition=_transition(value, condition)).details

        assert [(detail.label, detail.value) for detail in details[1:]] == expected
