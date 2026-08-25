import json
from collections.abc import Iterable
from typing import Any, cast

import pytest
from unittest import mock

import requests
from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.northpass_lms.northpass_lms import (
    NorthpassResumeConfig,
    _build_url,
    _flatten_item,
    _make_child_flattener,
    _make_quiz_attempt_flattener,
    _make_relationship_flattener,
    northpass_source,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"


def _resp(body: dict[str, Any], status: int = 200) -> Response:
    resp = Response()
    resp.status_code = status
    resp._content = json.dumps(body).encode()
    return resp


def _page(items: list[dict[str, Any]], next_url: str | None = None) -> Response:
    links = {"next": next_url} if next_url else {}
    return _resp({"data": items, "links": links})


def _make_manager(resume_state: NorthpassResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(mock_make_session: mock.MagicMock, pages: dict[str, Any]) -> list[str]:
    """Route the RESTClient's session to ``pages`` keyed by prepared URL, capturing each sent URL.

    A real ``requests.Session`` prepares requests (so ``prepared.url`` — used by the framework's
    host-pinning guard — is a genuine URL), while ``send`` is mocked to look up the fixture by URL.
    A fixture value that is an ``Exception`` is raised; anything else is returned as the response.
    """
    session = requests.Session()
    sent: list[str] = []

    def _send(prepared: Any, **kwargs: Any) -> Response:
        sent.append(prepared.url)
        result = pages[prepared.url]
        if isinstance(result, Exception):
            raise result
        return result

    session.send = mock.MagicMock(side_effect=_send)  # type: ignore[method-assign]  # ty: ignore[invalid-assignment]
    mock_make_session.return_value = session
    return sent


def _rows(endpoint: str, manager: mock.MagicMock) -> list[dict[str, Any]]:
    response = northpass_source("key", endpoint, team_id=1, job_id="j", resumable_source_manager=manager)
    return [row for page in cast("Iterable[Any]", response.items()) for row in page]


COURSES_P1 = "https://api.northpass.com/v2/courses?limit=100"
COURSES_P2 = "https://api.northpass.com/v2/courses?page=2&limit=100"


class TestBuildUrl:
    @parameterized.expand(
        [
            ("no_params", {}, "https://api.northpass.com/v2/courses"),
            ("encodes_params", {"limit": 100}, "https://api.northpass.com/v2/courses?limit=100"),
        ]
    )
    def test_build_url(self, _name, params, expected):
        assert _build_url("/courses", params) == expected


class TestFlattenItem:
    def test_promotes_attributes_and_drops_links(self):
        item = {
            "id": "c1",
            "type": "courses",
            "attributes": {"name": "Intro", "created_at": "2024-10-08T08:37:18Z"},
            "links": {"self": "https://api.northpass.com/v2/courses/c1"},
            "relationships": {"categories": {"data": []}},
        }
        row = _flatten_item(item)

        assert row["id"] == "c1"
        assert row["type"] == "courses"
        assert row["name"] == "Intro"
        assert row["created_at"] == "2024-10-08T08:37:18Z"
        assert "links" not in row
        assert "attributes" not in row
        assert row["relationships"] == {"categories": {"data": []}}

    def test_tolerates_missing_attributes(self):
        row = _flatten_item({"id": "x", "type": "quizzes"})
        assert row == {"id": "x", "type": "quizzes"}


class TestRelationshipFlattener:
    def test_promotes_relationship_ids_to_root_columns(self):
        flatten = _make_relationship_flattener({"person": "person_id", "activity": "activity_id"})
        row = flatten(
            {
                "type": "learner_viewed_activity_events",
                "attributes": {"created_at": "2024-10-08T08:37:24Z"},
                "relationships": {
                    "person": {"data": {"type": "people", "id": "p1"}},
                    "activity": {"data": {"type": "activities", "id": "a1"}},
                },
            }
        )

        # These columns form the endpoint's primary key, so they must land at the row root.
        assert row["person_id"] == "p1"
        assert row["activity_id"] == "a1"
        assert row["created_at"] == "2024-10-08T08:37:24Z"

    @parameterized.expand(
        [
            ("no_relationships_block", {"type": "x", "attributes": {"created_at": "t"}}),
            ("relationship_missing", {"type": "x", "relationships": {"person": {"data": {"id": "p1"}}}}),
            ("relationship_data_null", {"type": "x", "relationships": {"activity": {"data": None}}}),
        ]
    )
    def test_missing_relationship_still_emits_column(self, _name, item):
        flatten = _make_relationship_flattener({"activity": "activity_id"})
        row = flatten(item)

        # The column must exist (as None) even when the event has no such relationship, so the
        # table schema stays stable across heterogeneous event types.
        assert row["activity_id"] is None


class TestChildFlattener:
    def test_renames_injected_parent_id_and_flattens(self):
        flatten = _make_child_flattener("courses", "course_id")
        # include_from_parent injects the parent id under `_courses_id`.
        row = flatten({"id": "e1", "type": "course_enrollments", "attributes": {"progress": 30}, "_courses_id": "c1"})

        assert row["course_id"] == "c1"
        assert row["progress"] == 30
        assert "_courses_id" not in row

    def test_parent_id_wins_over_same_named_attribute(self):
        flatten = _make_child_flattener("courses", "course_id")
        row = flatten({"id": "e1", "attributes": {"course_id": "attr_val"}, "_courses_id": "c1"})
        assert row["course_id"] == "c1"


class TestTopLevelPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_until_next_link_missing(self, mock_make_session):
        pages = {
            COURSES_P1: _page(
                [{"id": "1", "attributes": {"name": "a"}}, {"id": "2", "attributes": {"name": "b"}}],
                next_url=COURSES_P2,
            ),
            COURSES_P2: _page([{"id": "3", "attributes": {"name": "c"}}]),
        }
        sent = _wire(mock_make_session, pages)
        rows = _rows("courses", _make_manager())

        assert [r["id"] for r in rows] == ["1", "2", "3"]
        assert [r["name"] for r in rows] == ["a", "b", "c"]
        assert sent == [COURSES_P1, COURSES_P2]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_saves_resume_state_only_while_pages_remain(self, mock_make_session):
        pages = {
            COURSES_P1: _page([{"id": "1"}], next_url=COURSES_P2),
            COURSES_P2: _page([{"id": "2"}]),
        }
        _wire(mock_make_session, pages)
        manager = _make_manager()
        _rows("courses", manager)

        # Saved after yielding page 1 (more remains), never after the last page.
        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [NorthpassResumeConfig(next_url=COURSES_P2)]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_next_url(self, mock_make_session):
        pages = {COURSES_P2: _page([{"id": "2"}])}
        sent = _wire(mock_make_session, pages)
        manager = _make_manager(NorthpassResumeConfig(next_url=COURSES_P2))
        rows = _rows("courses", manager)

        assert [r["id"] for r in rows] == ["2"]
        # The first page is skipped entirely — resume starts at the saved URL.
        assert sent == [COURSES_P2]

    @parameterized.expand(
        [
            ("attacker_host", "https://evil.example.com/steal?limit=100"),
            ("subdomain_spoof", "https://api.northpass.com.evil.com/v2/courses?page=2"),
            ("internal_metadata", "http://169.254.169.254/latest/meta-data/"),
        ]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_refuses_to_follow_offhost_next_link(self, _name, off_host_url, mock_make_session):
        # A hostile upstream points `links.next` off-host; the credentialed request must never be sent.
        pages = {COURSES_P1: _page([{"id": "1"}], next_url=off_host_url)}
        sent = _wire(mock_make_session, pages)

        with pytest.raises(ValueError):
            _rows("courses", _make_manager())

        # Pagination is rejected before the off-host URL ever reaches the wire.
        assert off_host_url not in sent
        assert sent == [COURSES_P1]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_treats_404_on_first_page_as_empty_collection(self, mock_make_session):
        # An account with no rows in a collection 404s instead of returning `data: []` (seen on
        # /learning-paths). This must not fail the sync -- it's the same "no data" outcome as an
        # empty body, not a retryable or fatal error.
        pages = {COURSES_P1: _resp({"errors": []}, status=404)}
        _wire(mock_make_session, pages)

        rows = _rows("courses", _make_manager())

        assert rows == []


class TestFanOut:
    def _parent_and_children(self) -> dict[str, Any]:
        return {
            # Parent enumeration (two courses).
            "https://api.northpass.com/v2/courses?limit=100": _page([{"id": "c1"}, {"id": "c2"}]),
            "https://api.northpass.com/v2/courses/c1/enrollments?limit=100": _page(
                [{"id": "e1", "attributes": {"progress": 30}}]
            ),
            "https://api.northpass.com/v2/courses/c2/enrollments?limit=100": _page(
                [{"id": "e2", "attributes": {"progress": 60}}]
            ),
        }

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_injects_parent_id_into_every_child_row(self, mock_make_session):
        _wire(mock_make_session, self._parent_and_children())
        rows = _rows("course_enrollments", _make_manager())

        by_id = {r["id"]: r for r in rows}
        assert by_id["e1"]["course_id"] == "c1"
        assert by_id["e2"]["course_id"] == "c2"
        # The injected parent id is what keeps the [course_id, id] primary key unique table-wide.
        assert by_id["e1"]["progress"] == 30

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_advances_parent_bookmark_between_parents(self, mock_make_session):
        _wire(mock_make_session, self._parent_and_children())
        manager = _make_manager()
        _rows("course_enrollments", manager)

        # After finishing c1, the fan-out cursor marks it completed so a crash resumes at the next parent.
        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert (
            NorthpassResumeConfig(
                fanout_state={"completed": ["/courses/c1/enrollments"], "current": None, "child_state": None}
            )
            in saved
        )

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_parent_bookmark_skipping_earlier_parents(self, mock_make_session):
        sent = _wire(mock_make_session, self._parent_and_children())
        manager = _make_manager(
            NorthpassResumeConfig(
                fanout_state={"completed": ["/courses/c1/enrollments"], "current": None, "child_state": None}
            )
        )
        rows = _rows("course_enrollments", manager)

        assert [r["id"] for r in rows] == ["e2"]
        # c1's enrollments must not be re-fetched when resuming past it.
        assert "https://api.northpass.com/v2/courses/c1/enrollments?limit=100" not in sent

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_skips_parent_that_404s_mid_fanout(self, mock_make_session):
        pages = self._parent_and_children()
        pages["https://api.northpass.com/v2/courses/c1/enrollments?limit=100"] = _resp({"errors": []}, status=404)
        _wire(mock_make_session, pages)

        rows = _rows("course_enrollments", _make_manager())

        # c1 vanished mid-sync; its 404 is swallowed and c2 still syncs.
        assert [r["id"] for r in rows] == ["e2"]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_reraises_non_404_child_error(self, mock_make_session):
        pages = self._parent_and_children()
        pages["https://api.northpass.com/v2/courses/c1/enrollments?limit=100"] = _resp({}, status=400)
        _wire(mock_make_session, pages)

        with pytest.raises(requests.HTTPError):
            _rows("course_enrollments", _make_manager())

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_treats_404_on_parent_enumeration_as_empty(self, mock_make_session):
        # The parent list itself (not a per-parent child page) 404s when the account has no
        # parent rows. Fanning out over zero parents must yield zero rows, not crash the sync.
        pages = {"https://api.northpass.com/v2/courses?limit=100": _resp({"errors": []}, status=404)}
        _wire(mock_make_session, pages)

        rows = _rows("course_enrollments", _make_manager())

        assert rows == []

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_course_activities_rows_carry_course_id_and_title(self, mock_make_session):
        pages = {
            "https://api.northpass.com/v2/courses?limit=100": _page([{"id": "c1"}, {"id": "c2"}]),
            "https://api.northpass.com/v2/courses/c1/activities?limit=100": _page(
                [{"id": "a1", "type": "activities", "attributes": {"title": "Lesson 1"}}]
            ),
            "https://api.northpass.com/v2/courses/c2/activities?limit=100": _page(
                [{"id": "a2", "type": "activities", "attributes": {"title": "Lesson 2"}}]
            ),
        }
        _wire(mock_make_session, pages)

        rows = _rows("course_activities", _make_manager())

        # The injected course id keeps the [course_id, id] primary key unique table-wide.
        assert [(r["id"], r["course_id"], r["title"]) for r in rows] == [
            ("a1", "c1", "Lesson 1"),
            ("a2", "c2", "Lesson 2"),
        ]


class TestActivityEvents:
    EVENTS_P1 = "https://api.northpass.com/v2/events?limit=100"
    EVENTS_P2 = "https://api.northpass.com/v2/events?page=2&limit=100"

    @staticmethod
    def _event(person_id: str, activity_id: str, created_at: str) -> dict[str, Any]:
        return {
            "type": "learner_viewed_activity_events",
            "attributes": {"created_at": created_at},
            "relationships": {
                "person": {"data": {"type": "people", "id": person_id}},
                "activity": {"data": {"type": "activities", "id": activity_id}},
            },
        }

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_yields_rows_keyed_by_person_activity_and_time(self, mock_make_session):
        pages = {
            self.EVENTS_P1: _page([self._event("p1", "a1", "2024-10-08T08:37:24Z")], next_url=self.EVENTS_P2),
            self.EVENTS_P2: _page([self._event("p2", "a1", "2024-10-08T09:00:00Z")]),
        }
        sent = _wire(mock_make_session, pages)

        rows = _rows("activity_events", _make_manager())

        # Rows land with the person/activity ids promoted out of `relationships` — the columns the
        # composite primary key and any join to `course_activities` / `people` depend on.
        assert [(r["person_id"], r["activity_id"], r["created_at"]) for r in rows] == [
            ("p1", "a1", "2024-10-08T08:37:24Z"),
            ("p2", "a1", "2024-10-08T09:00:00Z"),
        ]
        assert all(r["type"] == "learner_viewed_activity_events" for r in rows)
        assert sent == [self.EVENTS_P1, self.EVENTS_P2]


def _quiz_message(
    attempt_id: str | None,
    message_id: str = "m1",
    event_type: str = "quiz_completed_events",
    relationships: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """A sent-webhooks log message carrying a quiz-completed event payload."""
    attributes: dict[str, Any] = {
        "value": 100,
        "created_at": "2024-10-08T08:37:45Z",
        "attempts_remaining": 0,
        "minimum_passing_score": 80,
    }
    if attempt_id is not None:
        attributes["quiz_attempt_uuid"] = attempt_id
    return {
        "id": message_id,
        "type": "webhook",
        "attributes": {
            "attempt_left": 1,
            "created_at": "2024-10-08T08:37:45.656Z",
            "received_at": "2024-10-08T08:37:45.644Z",
            "type": event_type,
            "url": "https://example.com/hook",
            "payload": {
                "data": {
                    "id": f"evt-{message_id}",
                    "type": event_type,
                    "attributes": attributes,
                    "relationships": relationships
                    if relationships is not None
                    else {
                        "quiz": {"data": {"type": "quizzes", "id": "q1"}},
                        "course": {"data": {"type": "courses", "id": "c1"}},
                        "person": {"data": {"type": "people", "id": "p1"}},
                        "activity": {"data": {"type": "activities", "id": "a1"}},
                    },
                }
            },
        },
    }


def _message_without_payload() -> dict[str, Any]:
    message = _quiz_message("at1")
    del message["attributes"]["payload"]
    return message


class TestQuizAttemptFlattener:
    def test_reshapes_webhook_message_into_attempt_row(self):
        row = _make_quiz_attempt_flattener()(_quiz_message("at1"))

        assert isinstance(row, dict)
        # The attempt UUID must land as `id` — it is the primary key and what the answers fan-out
        # resolves; the message's own delivery id must not leak into the row.
        assert row["id"] == "at1"
        assert row["event_id"] == "evt-m1"
        assert row["type"] == "quiz_completed_events"
        assert row["value"] == 100
        assert row["minimum_passing_score"] == 80
        assert row["attempts_remaining"] == 0
        assert row["created_at"] == "2024-10-08T08:37:45Z"
        assert (row["quiz_id"], row["course_id"], row["person_id"], row["activity_id"]) == ("q1", "c1", "p1", "a1")

    @parameterized.expand(
        [
            ("other_event_type", _quiz_message("at1", event_type="course_completed_events")),
            ("no_payload", _message_without_payload()),
            ("payload_without_attempt_uuid", _quiz_message(None)),
        ]
    )
    def test_drops_unusable_messages(self, _name, message):
        # A message that can't yield an attempt row must be dropped, not emitted — a row without an
        # `id` would fail the fan-out's parent resolution and corrupt the primary key.
        assert _make_quiz_attempt_flattener()(message) == []

    def test_dedupes_attempts_across_messages_within_a_run(self):
        flatten = _make_quiz_attempt_flattener()

        first = flatten(_quiz_message("at1", message_id="m1"))
        second = flatten(_quiz_message("at1", message_id="m2"))

        # The log stores one message per subscribed webhook endpoint, so the same attempt can
        # appear twice; only the first delivery may produce a row.
        assert isinstance(first, dict)
        assert second == []

    def test_seen_state_is_fresh_per_flattener(self):
        # Each sync builds its own flattener; a shared seen-set would make every sync after the
        # first in a long-lived worker yield an empty table.
        assert isinstance(_make_quiz_attempt_flattener()(_quiz_message("at1")), dict)
        assert isinstance(_make_quiz_attempt_flattener()(_quiz_message("at1")), dict)

    def test_missing_relationships_still_emit_id_columns(self):
        row = _make_quiz_attempt_flattener()(_quiz_message("at1", relationships={}))

        assert isinstance(row, dict)
        # Columns must exist (as None) even when a reference is absent, so the table schema stays
        # stable across events.
        assert (row["quiz_id"], row["course_id"], row["person_id"], row["activity_id"]) == (None, None, None, None)


WEBHOOKS_URL = "https://api.northpass.com/v2/webhooks?filter%5Btype%5D%5Bin%5D=quiz_completed_events&limit=50"


class TestQuizAttemptsAndAnswers:
    def _log_and_answers(self) -> dict[str, Any]:
        return {
            WEBHOOKS_URL: _page(
                [
                    _quiz_message("at1", message_id="m1"),
                    # A second delivery of the same attempt (another subscribed endpoint) and a
                    # non-quiz message that slipped past the server-side type filter.
                    _quiz_message("at1", message_id="m2"),
                    _quiz_message("at9", message_id="m3", event_type="course_completed_events"),
                    _quiz_message("at2", message_id="m4"),
                ]
            ),
            "https://api.northpass.com/v2/quiz_attempts/at1/answers?limit=100": _page(
                [
                    {
                        "id": "ans1",
                        "type": "learner_answers",
                        "attributes": {"value": "New Answer", "correct": False, "created_at": "2024-10-08T08:37:34Z"},
                        "relationships": {
                            "question": {"data": {"type": "questions/choose", "id": "qq1"}},
                            "quiz_attempt": {"data": {"type": "quiz_attempts", "id": "at1"}},
                        },
                    }
                ]
            ),
            "https://api.northpass.com/v2/quiz_attempts/at2/answers?limit=100": _page(
                # No question relationship: the promoted column must still exist (as None).
                [{"id": "ans2", "type": "learner_answers", "attributes": {"correct": True}}]
            ),
        }

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_quiz_attempts_syncs_from_filtered_webhooks_log(self, mock_make_session):
        sent = _wire(mock_make_session, self._log_and_answers())

        rows = _rows("quiz_attempts", _make_manager())

        # The duplicate delivery and the non-quiz message must not produce rows.
        assert [(r["id"], r["value"], r["person_id"]) for r in rows] == [("at1", 100, "p1"), ("at2", 100, "p1")]
        # The exact URL proves the type filter and the /webhooks 50-row page cap are sent.
        assert sent == [WEBHOOKS_URL]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_answers_fan_out_over_attempts_from_the_log(self, mock_make_session):
        sent = _wire(mock_make_session, self._log_and_answers())

        rows = _rows("quiz_attempt_answers", _make_manager())

        by_id = {r["id"]: r for r in rows}
        # Rows carry the injected attempt id (part of the primary key) and the promoted question id.
        assert by_id["ans1"]["quiz_attempt_id"] == "at1"
        assert by_id["ans1"]["question_id"] == "qq1"
        assert by_id["ans1"]["correct"] is False
        assert by_id["ans2"]["quiz_attempt_id"] == "at2"
        assert by_id["ans2"]["question_id"] is None
        # One answers request per unique attempt: the duplicate delivery and the non-quiz message
        # must not fan out.
        assert sent == [
            WEBHOOKS_URL,
            "https://api.northpass.com/v2/quiz_attempts/at1/answers?limit=100",
            "https://api.northpass.com/v2/quiz_attempts/at2/answers?limit=100",
        ]


class TestNorthpassSource:
    @parameterized.expand(
        [
            ("people", ["id"], "created_at"),
            ("courses", ["id"], "created_at"),
            ("course_enrollments", ["course_id", "id"], "enrolled_at"),
            ("learning_path_enrollments", ["learning_path_id", "id"], "enrolled_at"),
            ("activity_events", ["person_id", "activity_id", "type", "created_at"], "created_at"),
            # The v2 API exposes no timestamps on activities, so the catalog is unpartitioned.
            ("course_activities", ["course_id", "id"], None),
            ("quiz_attempts", ["id"], "created_at"),
            ("quiz_attempt_answers", ["quiz_attempt_id", "id"], "created_at"),
        ]
    )
    def test_source_response_carries_endpoint_keys_and_partitioning(self, endpoint, primary_keys, partition_key):
        response = northpass_source("key", endpoint, team_id=1, job_id="j", resumable_source_manager=_make_manager())
        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        if partition_key is None:
            assert response.partition_keys is None
            assert response.partition_mode is None
        else:
            assert response.partition_keys == [partition_key]
            assert response.partition_mode == "datetime"
            assert response.partition_format == "month"
