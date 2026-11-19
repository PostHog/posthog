import pytest

from products.signals.backend.emission.azure_application_insights_exceptions import (
    azure_exception_emitter,
    exception_source_id,
)
from products.signals.backend.emission.google_play_console_error_issues import google_play_console_error_issue_emitter


def _azure(**overrides):
    record = {
        "problem_id": "System.NullReferenceException at App.Run",
        "exception_type": "System.NullReferenceException",
        "sample_message": "Object reference not set",
        "role_name": "web",
        "occurrences": 12,
        "first_seen": "2026-10-20T10:00:00+00:00",
        "last_seen": "2026-10-21T10:00:00+00:00",
    }
    record.update(overrides)
    return record


def _play(**overrides):
    record = {
        "issue_name": "apps/com.example/errorIssues/1",
        "issue_type": "CRASH",
        "cause": "java.lang.IllegalStateException",
        "code_location": "com.example.Main.run",
        "report_count": 40,
        "affected_users": 9,
        "first_version": "1.0",
        "last_version": "1.2",
        "last_report_time": "2026-10-21T10:00:00Z",
        "issue_url": "https://play.google.com/console/x",
    }
    record.update(overrides)
    return record


def test_azure_full_record():
    output = azure_exception_emitter(1, _azure())
    assert output is not None
    assert output.weight == 0.5
    assert "Exceptions in web: 12 occurrences" in output.description
    assert "Object reference not set" in output.description
    assert output.extra["occurrences"] == "12"


def test_azure_source_id_changes_per_week_and_problem():
    base = exception_source_id(_azure())
    assert base == exception_source_id(_azure())
    assert base != exception_source_id(_azure(last_seen="2026-10-30T10:00:00+00:00"))
    assert base != exception_source_id(_azure(problem_id="other"))


def test_azure_long_message_is_truncated():
    output = azure_exception_emitter(1, _azure(sample_message="x" * 1000))
    assert output is not None
    assert "x" * 300 in output.description and "x" * 301 not in output.description


@pytest.mark.parametrize(
    "overrides",
    [
        {"problem_id": ""},
        {"problem_id": None},
        {"exception_type": "", "sample_message": ""},
        {"exception_type": None, "sample_message": None},
    ],
)
def test_azure_skipped_records(overrides):
    assert azure_exception_emitter(1, _azure(**overrides)) is None


def test_play_full_record():
    output = google_play_console_error_issue_emitter(1, _play())
    assert output is not None
    assert output.source_id == "apps/com.example/errorIssues/1"
    assert output.description.splitlines() == [
        "Google Play CRASH: java.lang.IllegalStateException",
        "Location: com.example.Main.run",
        "Reports: 40, Users: 9",
    ]
    assert output.extra["issue_url"] == "https://play.google.com/console/x"


def test_play_location_only():
    output = google_play_console_error_issue_emitter(1, _play(cause="", report_count=None, affected_users=None))
    assert output is not None
    assert output.description == "Google Play CRASH\nLocation: com.example.Main.run"


@pytest.mark.parametrize(
    "overrides",
    [{"issue_name": ""}, {"cause": "", "code_location": ""}, {"cause": None, "code_location": None}],
)
def test_play_skipped_records(overrides):
    assert google_play_console_error_issue_emitter(1, _play(**overrides)) is None
