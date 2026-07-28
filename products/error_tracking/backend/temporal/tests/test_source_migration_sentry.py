import json

from parameterized import parameterized

from products.error_tracking.backend.models import ErrorTrackingIssue
from products.error_tracking.backend.temporal.source_migration.sentry import (
    MAX_FRAMES,
    build_anchor_event_uuid,
    build_event_uuid,
    build_exception_list,
    build_fingerprint,
    build_first_seen_anchor_event,
    extract_distinct_id,
    extract_project_slug,
    map_sentry_status,
    sentry_event_to_capture_event,
)

SENTRY_ENTRIES = [
    {"type": "breadcrumbs", "data": {"values": []}},
    {
        "type": "exception",
        "data": {
            "values": [
                {
                    "type": "TypeError",
                    "value": "cannot read properties of undefined",
                    "module": "app.views",
                    "mechanism": {"handled": False, "type": "generic", "extra": "dropped"},
                    "stacktrace": {
                        "frames": [
                            {
                                "function": "outer",
                                "filename": "app/views.py",
                                "absPath": "/srv/app/views.py",
                                "lineNo": 10,
                                "colNo": 5,
                                "inApp": True,
                                "context": [[8, "a = 1"], [9, "b = 2"], [10, "raise TypeError"], [11, "c = 3"]],
                            },
                            {"function": None, "absPath": "/srv/app/lib.py", "inApp": False},
                        ]
                    },
                },
                {"type": "ValueError", "value": "outermost"},
            ]
        },
    },
]


def _event_row(**overrides):
    row = {
        "event_id": "abc123",
        "issue_id": "4501",
        "date_created": "2026-05-01T12:00:00Z",
        "platform": "python",
        "message": "something broke",
        "user": json.dumps({"email": "jo@example.com", "id": "u1", "username": "jo"}),
        "tags": json.dumps([{"key": "release", "value": "1.2.3"}, {"key": "environment", "value": "prod"}]),
        "entries": json.dumps(SENTRY_ENTRIES),
        "issue_title": "TypeError: cannot read properties of undefined",
        "issue_culprit": "app.views in outer",
        "issue_level": "error",
        "issue_status": "unresolved",
        "issue_permalink": "https://sentry.io/organizations/acme/issues/4501/",
        "issue_short_id": "APP-1X",
        "issue_count": "240",
        "issue_user_count": 12,
        "issue_first_seen": "2026-01-15T00:00:00Z",
        "issue_project": json.dumps({"id": "7", "slug": "backend"}),
    }
    row.update(overrides)
    return row


class TestSentryTransform:
    def test_capture_event_shape(self):
        event = sentry_event_to_capture_event(_event_row(), "acme", "mig-1")

        assert event["event"] == "$exception"
        assert event["distinct_id"] == "jo@example.com"
        assert event["timestamp"] == "2026-05-01T12:00:00Z"
        assert event["event_uuid"] == build_event_uuid("acme", "abc123")
        assert event["options"] == {"disable_skew_correction": True}

        props = event["properties"]
        assert props["$exception_fingerprint"] == "sentry:acme:4501"
        assert props["$issue_name"] == "TypeError: cannot read properties of undefined"
        assert props["$issue_description"] == "app.views in outer"
        assert props["$exception_level"] == "error"
        assert props["$sentry_event_id"] == "abc123"
        assert props["$sentry_url"] == "https://sentry.io/organizations/acme/issues/4501/"
        assert props["$sentry_project"] == "backend"
        assert props["$sentry_tags"] == {"release": "1.2.3", "environment": "prod"}
        assert props["$import_job_id"] == "mig-1"
        assert props["$lib"] == "posthog-sentry-import"

    def test_exception_list_reversed_with_custom_frames(self):
        exceptions = build_exception_list(json.dumps(SENTRY_ENTRIES), "python", "Fallback", None)

        assert [e["type"] for e in exceptions] == ["ValueError", "TypeError"]
        assert exceptions[1]["mechanism"] == {"handled": False, "type": "generic"}
        assert exceptions[1]["module"] == "app.views"
        assert "stacktrace" not in exceptions[0]

        frames = exceptions[1]["stacktrace"]["frames"]
        assert exceptions[1]["stacktrace"]["type"] == "raw"
        assert frames[0] == {
            "platform": "custom",
            "lang": "python",
            "function": "outer",
            "filename": "app/views.py",
            "lineno": 10,
            "colno": 5,
            "module": None,
            "context_line": "raise TypeError",
            "pre_context": ["a = 1", "b = 2"],
            "post_context": ["c = 3"],
            "in_app": True,
            "resolved": True,
        }
        assert frames[1]["function"] == "<anonymous>"
        assert frames[1]["filename"] == "/srv/app/lib.py"
        assert frames[1]["in_app"] is False

    def test_frame_cap_keeps_most_recent(self):
        frames = [{"function": f"f{i}"} for i in range(MAX_FRAMES + 10)]
        entries = [{"type": "exception", "data": {"values": [{"type": "E", "stacktrace": {"frames": frames}}]}}]

        result = build_exception_list(entries, "python", None, None)

        kept = result[0]["stacktrace"]["frames"]
        assert len(kept) == MAX_FRAMES
        assert kept[0]["function"] == "f10"
        assert kept[-1]["function"] == f"f{MAX_FRAMES + 9}"

    def test_message_only_event_falls_back_to_issue_title(self):
        exceptions = build_exception_list(None, "python", "Boom", "something broke")

        assert exceptions == [{"type": "Boom", "value": "something broke"}]

    @parameterized.expand(
        [
            ({"email": "a@b.c", "id": "1", "username": "u"}, "a@b.c"),
            ({"id": "1", "username": "u"}, "1"),
            ({"username": "u"}, "u"),
            ({}, "sentry:acme:anonymous"),
            (None, "sentry:acme:anonymous"),
        ]
    )
    def test_distinct_id_fallback_chain(self, user, expected):
        raw = json.dumps(user) if user is not None else None
        assert extract_distinct_id(raw, "acme") == expected

    @parameterized.expand(
        [
            ("resolved", ErrorTrackingIssue.Status.RESOLVED),
            ("ignored", ErrorTrackingIssue.Status.SUPPRESSED),
            ("muted", ErrorTrackingIssue.Status.SUPPRESSED),
            ("unresolved", None),
            (None, None),
        ]
    )
    def test_status_mapping(self, sentry_status, expected):
        assert map_sentry_status(sentry_status) == expected

    def test_deterministic_ids(self):
        assert build_fingerprint("acme", "4501") == "sentry:acme:4501"
        assert build_event_uuid("acme", "abc123") == build_event_uuid("acme", "abc123")
        assert build_event_uuid("acme", "abc123") != build_event_uuid("acme", "abc124")
        assert build_anchor_event_uuid("acme", "4501") != build_event_uuid("acme", "4501")

    def test_anchor_event_only_when_first_seen_predates_event(self):
        anchor = build_first_seen_anchor_event(_event_row(), "acme", "mig-1")
        assert anchor is not None
        assert anchor["timestamp"] == "2026-01-15T00:00:00Z"
        assert anchor["event_uuid"] == build_anchor_event_uuid("acme", "4501")
        assert anchor["distinct_id"] == "sentry:acme:anonymous"
        assert anchor["properties"]["$exception_fingerprint"] == "sentry:acme:4501"

        row = _event_row(issue_first_seen="2026-05-01T12:00:00Z")
        assert build_first_seen_anchor_event(row, "acme", "mig-1") is None

    def test_project_slug_extraction(self):
        assert extract_project_slug(_event_row()) == "backend"
        assert extract_project_slug(_event_row(issue_project=None)) is None
        assert extract_project_slug(_event_row(issue_project="not json {")) is None

    def test_none_properties_dropped(self):
        row = _event_row(issue_short_id=None, issue_permalink=None, tags=None)
        props = sentry_event_to_capture_event(row, "acme", "mig-1")["properties"]
        assert "$sentry_short_id" not in props
        assert "$sentry_url" not in props
        assert "$sentry_tags" not in props
