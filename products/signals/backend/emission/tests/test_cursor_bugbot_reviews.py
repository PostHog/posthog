import json

import pytest

from products.signals.backend.emission.cursor_bugbot_reviews import cursor_bugbot_emitter


def _record(**overrides):
    record = {
        "request_id": "req-1",
        "timestamp": "2026-10-01T10:00:00Z",
        "repo": "github.com/acme/app",
        "pr_number": 42,
        "commit_sha": "abc123",
        "bugs_found": 2,
        "dry_run": False,
        "publication_status": "posted",
        "bugs": json.dumps(
            [
                {"comment_id": "1", "severity": "high", "resolution_status": "unresolved"},
                {"comment_id": "2", "severity": "low", "resolution_status": "resolved"},
            ]
        ),
    }
    record.update(overrides)
    return record


def test_full_record():
    output = cursor_bugbot_emitter(1, _record())
    assert output is not None
    assert output.source_id == "req-1"
    assert "found 2 issues in github.com/acme/app PR #42" in output.description
    assert "Severity: 1 high, 1 low" in output.description
    assert "Unresolved: 1" in output.description
    assert output.extra["pr_number"] == "42"
    assert output.extra["bugs_found"] == "2"


def test_bug_titles_are_listed_when_present():
    bugs = [{"severity": "medium", "title": "Unbounded retry loop", "description": "retry() has no ceiling."}]
    output = cursor_bugbot_emitter(1, _record(bugs=bugs, bugs_found=1))
    assert output is not None
    assert "- [medium] Unbounded retry loop: retry() has no ceiling." in output.description


@pytest.mark.parametrize(
    "overrides",
    [
        {"request_id": ""},
        {"dry_run": True},
        {"dry_run": "true"},
        {"bugs_found": 0},
        {"bugs_found": None},
        {"bugs_found": "many"},
        {"bugs": json.dumps([{"severity": "low", "resolution_status": "resolved"}])},
    ],
)
def test_skipped_records(overrides):
    assert cursor_bugbot_emitter(1, _record(**overrides)) is None


@pytest.mark.parametrize("bugs", ["not json", None, "{}", ""])
def test_malformed_bugs_still_emit(bugs):
    output = cursor_bugbot_emitter(1, _record(bugs=bugs))
    assert output is not None
    assert "Severity" not in output.description


def test_unknown_severity_levels_are_tallied_after_known_levels():
    bugs = [
        {"severity": "blocker", "resolution_status": "unresolved"},
        {"severity": "critical", "resolution_status": "unresolved"},
        {"severity": "low", "resolution_status": "unresolved"},
    ]
    output = cursor_bugbot_emitter(1, _record(bugs=json.dumps(bugs), bugs_found=3))
    assert output is not None
    assert "Severity: 1 critical, 1 low, 1 blocker" in output.description
