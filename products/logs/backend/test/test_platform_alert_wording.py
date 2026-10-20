import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlsplit

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from products.alerts_platform.backend.facade.contracts import AlertEventKind, AnnouncedTransition, MessageDetail
from products.cdp.backend.validation import generate_template_bytecode
from products.logs.backend.alert_destinations import EVENT_KIND_CONFIG, EventKind
from products.logs.backend.logs_url_params import build_logs_url_params
from products.logs.backend.platform_alert_wording import describe_logs_transition, legacy_logs_webhook_body
from products.logs.backend.platform_source_config import logs_source_config

from common.hogvm.python.execute import execute_bytecode

CONDITION = {"threshold_count": 10, "threshold_operator": "above", "window_minutes": 10}
OCCURRED = datetime(2026, 10, 8, 18, 5, tzinfo=UTC)


def _transition(
    kind: AlertEventKind = AlertEventKind.FIRING,
    value: float | None = 11.0,
    filters: dict[str, Any] | None = None,
    flat: bool = False,
) -> AnnouncedTransition:
    return AnnouncedTransition(
        grouping_key="",
        kind=kind,
        episode_started_at=OCCURRED,
        value=value,
        labels={},
        condition=CONDITION,
        source_config={**(filters or {}), "condition": CONDITION}
        if flat
        else logs_source_config(filters or {}, CONDITION),
        error_message=None,
        occurred_at=OCCURRED,
    )


def _facets(services: list[str], levels: list[str]) -> dict[str, Any]:
    route = {"key": "http.route", "type": "log_attribute", "operator": "exact", "value": ["/checkout"]}
    return {
        "type": "AND",
        "values": [
            {
                "type": "AND",
                "values": [
                    {"key": "service_name", "type": "log", "operator": "exact", "value": services},
                    {"key": "severity_level", "type": "log", "operator": "exact", "value": levels},
                    route,
                ],
            }
        ],
    }


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
            ("flat_history_row", {"serviceNames": ["api"]}, ("Services: api",), True),
        ]
    )
    def test_the_context_names_the_filters_the_alert_watches(
        self, _name: str, filters: dict[str, Any], expected: tuple[str, ...], flat: bool = False
    ) -> None:
        description = describe_logs_transition(project_id=7, transition=_transition(filters=filters, flat=flat))

        assert description.context == expected

    @parameterized.expand(
        [
            ("ungrouped", {}, (), ["api", "worker"], ["error", "warn"]),
            (
                "grouped",
                {"service_name": "worker", "severity_text": "error"},
                (MessageDetail(label="Service", value="worker"), MessageDetail(label="Severity", value="error")),
                ["worker"],
                ["error"],
            ),
        ]
    )
    def test_a_message_names_the_group_and_links_to_the_logs_the_check_counted(
        self,
        _name: str,
        labels: dict[str, str],
        group_details: tuple[MessageDetail, ...],
        service_names: list[str],
        severity_levels: list[str],
    ) -> None:
        filters = {
            "serviceNames": ["api", "worker"],
            "severityLevels": ["error", "warn"],
            "filterGroup": _facets(["api", "worker"], ["error", "warn"]),
        }
        transition = replace(_transition(filters=filters), labels=labels)

        description = describe_logs_transition(project_id=7, transition=transition)

        assert description.details == (
            *group_details,
            MessageDetail(label="Threshold breached", value="11 logs in 10m (threshold: above 10)"),
        )
        assert description.data_link is not None
        assert description.data_link.label == "View logs"
        url = urlsplit(description.data_link.url)
        params = parse_qs(url.query)
        assert url.path == "/project/7/logs"
        assert json.loads(params["serviceNames"][0]) == service_names
        assert json.loads(params["severityLevels"][0]) == severity_levels
        # The logs scene reads a column's selection from `filterGroup` when the group holds one.
        assert json.loads(params["filterGroup"][0]) == _facets(service_names, severity_levels)
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
        self, _name: str, kind: AlertEventKind, legacy_kind: EventKind
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
                filters, date_from=OCCURRED - timedelta(minutes=10), date_to=OCCURRED
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
        naive = replace(_transition(), occurred_at=OCCURRED.replace(tzinfo=None))

        body = legacy_logs_webhook_body(
            project_id=7, alert_id="alert-1", alert_name="API errors", consecutive_failures=0, transition=naive
        )
        aware = legacy_logs_webhook_body(
            project_id=7, alert_id="alert-1", alert_name="API errors", consecutive_failures=0, transition=_transition()
        )

        assert body["timestamp"] == OCCURRED.isoformat()
        # The link's window carries the zone too, or a browser outside UTC shifts it.
        assert body["data"]["logs_url"] == aware["data"]["logs_url"]

    @parameterized.expand([("legacy_webhook_body",), ("message_link",)])
    def test_a_logs_link_opens_the_window_the_check_queried(self, link: str) -> None:
        # The ingestion checkpoint clamped this check's window end to well before it was recorded.
        window_end = OCCURRED - timedelta(minutes=7)
        transition = replace(
            _transition(filters={"serviceNames": ["api"]}),
            evaluation_key=f"slot:{OCCURRED.isoformat()}|window:{window_end.isoformat()}",
        )

        if link == "legacy_webhook_body":
            url = legacy_logs_webhook_body(
                project_id=7, alert_id="alert-1", alert_name="API errors", consecutive_failures=0, transition=transition
            )["data"]["logs_url"]
        else:
            data_link = describe_logs_transition(project_id=7, transition=transition).data_link
            assert data_link is not None
            url = data_link.url

        query = parse_qs(urlsplit(url).query)
        date_range = json.loads(query["dateRange"][0])
        assert date_range["date_to"] == window_end.isoformat()


def _render(node: Any, globals_: dict[str, Any]) -> Any:
    if isinstance(node, list) and node and node[0] in ("_H", "_h"):
        return execute_bytecode(node, globals=globals_).result
    if isinstance(node, dict):
        return {key: _render(value, globals_) for key, value in node.items()}
    if isinstance(node, list):
        return [_render(item, globals_) for item in node]
    return node
