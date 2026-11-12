import json

import pytest

from products.signals.backend.emission.amazon_cloudwatch_alarm_history import (
    alarm_source_id,
    amazon_cloudwatch_alarm_emitter,
)
from products.signals.backend.emission.appsignal_anomaly_incidents import appsignal_anomaly_incident_emitter
from products.signals.backend.emission.appsignal_performance_incidents import (
    action_names,
    appsignal_performance_incident_emitter,
)
from products.signals.backend.emission.logicmonitor_alerts import logicmonitor_alert_emitter
from products.signals.backend.emission.mux_errors import mux_error_emitter, mux_error_source_id
from products.signals.backend.emission.newrelic_alert_issues import issue_title, newrelic_alert_issue_emitter
from products.signals.backend.emission.newrelic_errors import (
    javascript_error_source_id,
    newrelic_javascript_error_emitter,
    newrelic_transaction_error_emitter,
)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("High CPU on web", "High CPU on web"),
        ('["High CPU on web", "Disk full", "High CPU on web"]', "High CPU on web; Disk full"),
        ('["", null, 3]', ""),
        ("[not json", "[not json"),
        ('{"title": "x"}', '{"title": "x"}'),
        (None, ""),
    ],
)
def test_newrelic_issue_title(raw, expected):
    assert issue_title(raw) == expected


@pytest.mark.parametrize(
    "record,expected_description",
    [
        (
            {
                "issue_id": "abc",
                "issue_title": '["Error rate high"]',
                "issue_priority": "CRITICAL",
                "activated_at": "t",
            },
            "New Relic alert: Error rate high\nPriority: critical",
        ),
        (
            {"issue_id": "abc", "issue_title": "Error rate high", "issue_priority": None},
            "New Relic alert: Error rate high",
        ),
        ({"issue_id": "abc", "issue_title": "[]"}, None),
        ({"issue_id": "", "issue_title": "Error rate high"}, None),
    ],
)
def test_newrelic_alert_issue_emitter(record, expected_description):
    output = newrelic_alert_issue_emitter(1, record)
    if expected_description is None:
        assert output is None
        return
    assert output is not None
    assert output.description == expected_description
    assert output.source_id == "alert_issue:abc"


def _newrelic_error(**overrides):
    record = {
        "app_name": "storefront",
        "error_class": "TypeError",
        "error_message": "x is undefined",
        "occurrences": 7,
        "first_seen": "2026-11-09T10:00:00+00:00",
        "last_seen": "2026-11-10T10:00:00+00:00",
    }
    record.update(overrides)
    return record


@pytest.mark.parametrize(
    "overrides,expected_headline",
    [
        ({}, "TypeError: x is undefined"),
        ({"error_message": ""}, "TypeError"),
        ({"error_class": None}, "x is undefined"),
        ({"error_class": "", "error_message": None}, None),
    ],
)
def test_newrelic_error_headline(overrides, expected_headline):
    output = newrelic_javascript_error_emitter(1, _newrelic_error(**overrides))
    if expected_headline is None:
        assert output is None
        return
    assert output is not None
    assert output.description.split("\n")[0] == expected_headline
    assert output.weight < 1.0


def test_newrelic_transaction_error_names_the_transaction():
    output = newrelic_transaction_error_emitter(1, _newrelic_error(sample_transaction="WebTransaction/Uri/checkout"))
    assert output is not None
    assert output.description.split("\n")[1:] == [
        "Transaction errors in storefront: 7 occurrences between 2026-11-09T10:00:00+00:00 and 2026-11-10T10:00:00+00:00",
        "Transaction: WebTransaction/Uri/checkout",
    ]
    assert output.extra["kind"] == "transaction_error"


@pytest.mark.parametrize(
    "overrides,same",
    [
        ({"occurrences": 99, "first_seen": "2026-11-09T11:00:00+00:00"}, True),
        ({"last_seen": "2026-11-20T10:00:00+00:00"}, False),
        ({"app_name": "admin"}, False),
        ({"error_message": "y is undefined"}, False),
    ],
)
def test_newrelic_error_source_id_keys_on_group_and_week(overrides, same):
    assert (
        javascript_error_source_id(_newrelic_error()) == javascript_error_source_id(_newrelic_error(**overrides))
    ) is same


def test_cloudwatch_alarm_emitter():
    record = {
        "alarm_name": "api-5xx",
        "alarm_kind": "MetricAlarm",
        "state_reason": "Threshold Crossed: 1 datapoint was greater than the threshold (5.0). " + "x" * 2000,
        "transitions": 3,
        "first_seen": "2026-11-09T10:00:00+00:00",
        "last_seen": "2026-11-10T10:00:00+00:00",
    }
    output = amazon_cloudwatch_alarm_emitter(1, record)
    assert output is not None
    summary, reason = output.description.split("\n")
    assert summary == (
        "CloudWatch alarm api-5xx entered the ALARM state 3 times between "
        "2026-11-09T10:00:00+00:00 and 2026-11-10T10:00:00+00:00"
    )
    assert reason.startswith("Threshold Crossed") and len(reason) == 1000
    assert output.source_id == alarm_source_id(record)
    assert output.source_id != alarm_source_id({**record, "last_seen": "2026-11-20T10:00:00+00:00"})
    assert amazon_cloudwatch_alarm_emitter(1, {**record, "alarm_name": " "}) is None


@pytest.mark.parametrize(
    "overrides,expected_description",
    [
        (
            {},
            "LogicMonitor alert: CPU alert on web-01\nInstance: CPU, Datapoint: CPUBusyPercent, Severity: critical",
        ),
        (
            {"monitor_object_name": "", "severity": 2},
            "LogicMonitor alert: CPU alert\nInstance: CPU, Datapoint: CPUBusyPercent, Severity: warning",
        ),
        (
            {"resource_template_name": None, "instance_name": "", "data_point_name": None, "severity": 9},
            "LogicMonitor alert: web-01\nSeverity: 9",
        ),
        ({"resource_template_name": "", "monitor_object_name": ""}, None),
    ],
)
def test_logicmonitor_alert_emitter(overrides, expected_description):
    record = {
        "id": "DS123",
        "severity": 4,
        "acked": False,
        "monitor_object_name": "web-01",
        "resource_template_name": "CPU",
        "instance_name": "CPU",
        "data_point_name": "CPUBusyPercent",
        "start_epoch": 1762941600,
        **overrides,
    }
    output = logicmonitor_alert_emitter(1, record)
    if expected_description is None:
        assert output is None
        return
    assert output is not None
    assert output.description == expected_description
    assert output.source_id == "DS123"


@pytest.mark.parametrize(
    "raw,expected",
    [
        (["UsersController#show", "UsersController#show", "Api#index"], ["UsersController#show", "Api#index"]),
        ('["SyncJob#perform"]', ["SyncJob#perform"]),
        ("not json", []),
        (None, []),
        ([{"name": "x"}, ""], []),
    ],
)
def test_appsignal_action_names(raw, expected):
    assert action_names(raw) == expected


@pytest.mark.parametrize(
    "has_n_plus_one,expects_n_plus_one_line",
    [(True, True), ("true", True), (False, False), (None, False)],
)
def test_appsignal_performance_incident_emitter(has_n_plus_one, expects_n_plus_one_line):
    output = appsignal_performance_incident_emitter(
        1,
        {
            "id": "42",
            "action_names": '["UsersController#show"]',
            "namespace": "web",
            "mean": 812.5,
            "has_n_plus_one": has_n_plus_one,
            "state": "OPEN",
        },
    )
    assert output is not None
    lines = output.description.split("\n")
    assert lines[:2] == ["Slow web action: UsersController#show", "Mean duration: 812.5 ms"]
    assert ("N+1 queries detected in recent deploys" in lines) is expects_n_plus_one_line
    assert output.source_id == "performance_incident:42"
    assert appsignal_performance_incident_emitter(1, {"id": "42", "action_names": "[]"}) is None


@pytest.mark.parametrize(
    "trigger,expected_lines",
    [
        (
            json.dumps({"name": "High error rate", "metricName": "transaction_exception_rate", "field": "MEAN"}),
            [
                "AppSignal anomaly alert: High error rate",
                "Metric: transaction_exception_rate (mean)",
                "Tags: namespace=web",
            ],
        ),
        (
            {"metric_name": "memory_usage"},
            ["AppSignal anomaly alert: memory_usage", "Metric: memory_usage", "Tags: namespace=web"],
        ),
        ("not json", None),
    ],
)
def test_appsignal_anomaly_incident_emitter(trigger, expected_lines):
    record = {
        "id": "7",
        "trigger": trigger,
        "tags": json.dumps([{"key": "namespace", "value": "web"}, {"key": "", "value": "x"}, "bad"]),
        "state": "OPEN",
    }
    output = appsignal_anomaly_incident_emitter(1, record)
    if expected_lines is None:
        assert output is None
        return
    assert output is not None
    assert output.description.split("\n") == expected_lines
    assert output.source_id == "anomaly_incident:7"


@pytest.mark.parametrize(
    "overrides,expected_lines",
    [
        (
            {},
            [
                "Video playback error 2: Network error",
                "The video could not be loaded",
                "Affected 12 views (share of views: 0.04)",
            ],
        ),
        (
            {"error_code": None, "error_description": "Network error"},
            ["Network error", "Affected 12 views (share of views: 0.04)"],
        ),
        ({"error_message": "", "view_count": None}, ["Video playback error 2: The video could not be loaded"]),
        ({"error_message": "", "error_description": None}, None),
    ],
)
def test_mux_error_emitter(overrides, expected_lines):
    record = {
        "id": "err-1",
        "error_code": 2,
        "error_message": "Network error",
        "error_description": "The video could not be loaded",
        "view_count": 12,
        "view_share": 0.04,
        "last_seen_at": "2026-11-10T10:00:00Z",
        **overrides,
    }
    output = mux_error_emitter(1, record)
    if expected_lines is None:
        assert output is None
        return
    assert output is not None
    assert output.description.split("\n") == expected_lines
    assert output.source_id == mux_error_source_id(record)
    assert output.source_id != mux_error_source_id({**record, "last_seen_at": "2026-11-20T10:00:00Z"})
