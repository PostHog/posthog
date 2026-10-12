import json
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, urlsplit

from django.test import SimpleTestCase

from parameterized import parameterized

from products.alerts_platform.backend.facade.contracts import AlertEventKind, AnnouncedTransition, MessageDetail
from products.logs.backend.platform_alert_wording import describe_logs_transition

CONDITION = {"threshold_count": 10, "threshold_operator": "above", "window_minutes": 10}
OCCURRED = datetime(2026, 10, 8, 18, 5, tzinfo=UTC)


def _transition(
    kind: AlertEventKind = AlertEventKind.FIRING, value: float | None = 11.0, filters: dict[str, Any] | None = None
) -> AnnouncedTransition:
    return AnnouncedTransition(
        grouping_key="",
        kind=kind,
        episode_started_at=OCCURRED,
        value=value,
        labels={},
        condition=CONDITION,
        source_config={**(filters or {}), "condition": CONDITION},
        error_message=None,
        occurred_at=OCCURRED,
    )


class TestLogsPlatformAlertWording(SimpleTestCase):
    @parameterized.expand(
        [
            ("firing", AlertEventKind.FIRING, 11.0, "Threshold breached", "11 logs in 10m (threshold: above 10)"),
            ("resolved", AlertEventKind.RESOLVED, 3.0, "Current count", "3 logs in 10m (threshold: above 10)"),
            ("held_check", AlertEventKind.CHECK, 1.0, "Count", "1 log in 10m (threshold: above 10)"),
            (
                "large_count",
                AlertEventKind.FIRING,
                1_250_000.0,
                "Threshold breached",
                "1,250,000 logs in 10m (threshold: above 10)",
            ),
        ]
    )
    def test_a_transition_reads_as_a_count_of_logs(
        self, _name: str, kind: AlertEventKind, value: float, label: str, summary: str
    ) -> None:
        description = describe_logs_transition(project_id=7, transition=_transition(kind, value))

        assert description.details == (MessageDetail(label=label, value=summary),)

    def test_a_check_without_a_value_leaves_the_details_to_the_platform(self) -> None:
        description = describe_logs_transition(project_id=7, transition=_transition(AlertEventKind.ERRORED, value=None))

        assert description.details == ()

    @parameterized.expand(
        [
            (
                "both",
                {"severityLevels": ["error", "fatal"], "serviceNames": ["api"]},
                ("Severity: error, fatal", "Services: api"),
            ),
            ("services_only", {"serviceNames": ["api", "worker"]}, ("Services: api, worker",)),
            (
                "property_filters_only",
                {"filterGroup": {"type": "AND", "values": [{"type": "AND", "values": [{"key": "status"}]}]}},
                ("Property filters applied",),
            ),
            ("no_filters", {}, ("All log levels and services",)),
        ]
    )
    def test_the_context_names_the_filters_the_alert_watches(
        self, _name: str, filters: dict[str, Any], expected: tuple[str, ...]
    ) -> None:
        description = describe_logs_transition(project_id=7, transition=_transition(filters=filters))

        assert description.context == expected

    def test_the_link_opens_the_logs_the_check_counted(self) -> None:
        description = describe_logs_transition(project_id=7, transition=_transition(filters={"serviceNames": ["api"]}))

        assert description.data_link is not None
        assert description.data_link.label == "View logs"
        url = urlsplit(description.data_link.url)
        params = parse_qs(url.query)
        assert url.path == "/project/7/logs"
        assert json.loads(params["serviceNames"][0]) == ["api"]
        assert json.loads(params["dateRange"][0]) == {
            "date_from": "2026-10-08T17:55:00+00:00",
            "date_to": "2026-10-08T18:05:00+00:00",
        }
