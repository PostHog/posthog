import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlsplit

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from products.alerts_platform.backend.facade.contracts import AlertEventKind, AnnouncedTransition, MessageDetail
from products.cdp.backend.validation import generate_template_bytecode
from products.logs.backend.alert_destinations import EVENT_KIND_CONFIG
from products.logs.backend.logs_url_params import build_logs_url_params
from products.logs.backend.platform_alert_wording import describe_logs_transition, legacy_logs_webhook_body

from common.hogvm.python.execute import execute_bytecode

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

    @parameterized.expand(
        [
            ("firing", AlertEventKind.FIRING, "firing"),
            ("resolved", AlertEventKind.RESOLVED, "resolved"),
            ("errored", AlertEventKind.ERRORED, "errored"),
            ("auto_disabled", AlertEventKind.BROKEN, "broken"),
        ]
    )
    @override_settings(SITE_URL="https://us.posthog.com")
    def test_the_legacy_webhook_body_matches_what_the_hog_function_sent(
        self, _name: str, kind: AlertEventKind, legacy_kind: str
    ) -> None:
        filters = {"serviceNames": ["api"], "severityLevels": ["error"]}
        breach = kind in (AlertEventKind.FIRING, AlertEventKind.RESOLVED)
        transition = replace(
            _transition(kind, 11.0 if breach else None, filters), error_message=None if breach else "query timed out"
        )

        native = legacy_logs_webhook_body(
            project_id=7, alert_id="alert-1", alert_name="API errors", consecutive_failures=2, transition=transition
        )

        # The properties the logs stack put on its event, rendered through the stock template.
        properties = {
            "alert_id": "alert-1",
            "alert_name": "API errors",
            "result_count": 11,
            "threshold_count": 10,
            "threshold_operator": "above",
            "window_minutes": 10,
            "service_names": ["api"],
            "severity_levels": ["error"],
            "logs_url_params": build_logs_url_params(
                transition.source_config, date_from=OCCURRED - timedelta(minutes=10), date_to=OCCURRED
            ),
            "triggered_at": OCCURRED.isoformat(),
            "consecutive_failures": 2,
            "error_message": "query timed out",
            "last_error_message": "query timed out",
        }
        globals_ = {
            "event": {"uuid": native["id"], "properties": properties},
            "project": {"url": "https://us.posthog.com/project/7"},
        }
        legacy = _render(generate_template_bytecode(EVENT_KIND_CONFIG[legacy_kind].webhook_body, set()), globals_)

        assert native == legacy

    def test_a_naive_history_timestamp_is_sent_as_utc(self) -> None:
        transition = replace(_transition(), occurred_at=OCCURRED.replace(tzinfo=None))

        body = legacy_logs_webhook_body(
            project_id=7, alert_id="alert-1", alert_name="API errors", consecutive_failures=0, transition=transition
        )

        assert body["timestamp"] == OCCURRED.isoformat()


def _render(node: Any, globals_: dict[str, Any]) -> Any:
    if isinstance(node, list) and node and node[0] in ("_H", "_h"):
        return execute_bytecode(node, globals=globals_).result
    if isinstance(node, dict):
        return {key: _render(value, globals_) for key, value in node.items()}
    if isinstance(node, list):
        return [_render(item, globals_) for item in node]
    return node
