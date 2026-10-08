import json
from collections.abc import Iterable
from typing import Any, cast

import pytest
from unittest import mock

import requests
from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.northpass_lms.northpass_lms import (
    NorthpassQuizLogEmptyError,
    NorthpassResumeConfig,
    _build_url,
    _make_child_flattener,
    _make_quiz_attempt_flattener,
    _make_relationship_flattener,
    northpass_source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.northpass_lms.settings import (
    QUIZ_LOG_EMPTY_MESSAGE,
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

    session.send = mock.MagicMock(side_effect=_send)  # type: ignore[method-assign]
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


class TestRelationshipFlattener:
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


class TestTopLevelPagination:
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
    def test_reraises_non_404_child_error(self, mock_make_session):
        pages = self._parent_and_children()
        pages["https://api.northpass.com/v2/courses/c1/enrollments?limit=100"] = _resp({}, status=400)
        _wire(mock_make_session, pages)

        with pytest.raises(requests.HTTPError):
            _rows("course_enrollments", _make_manager())


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
        assert _make_quiz_attempt_flattener(set())(message) == []


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

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_log_with_next_link_stops_and_raises(self, mock_make_session):
        pages = {WEBHOOKS_URL: _page([], next_url="https://api.northpass.com/v2/webhooks?page=2&limit=50")}
        sent = _wire(mock_make_session, pages)

        with pytest.raises(NorthpassQuizLogEmptyError, match=QUIZ_LOG_EMPTY_MESSAGE):
            _rows("quiz_attempts", _make_manager())

        assert sent == [WEBHOOKS_URL]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_log_holding_only_other_event_types_raises(self, mock_make_session):
        pages = {WEBHOOKS_URL: _page([_quiz_message("at9", message_id="m3", event_type="course_completed_events")])}
        _wire(mock_make_session, pages)

        with pytest.raises(NorthpassQuizLogEmptyError, match="quiz_attempts has no rows to sync"):
            _rows("quiz_attempts", _make_manager())

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_answers_raise_when_the_log_holds_no_attempt(self, mock_make_session):
        pages = {WEBHOOKS_URL: _page([])}
        sent = _wire(mock_make_session, pages)

        with pytest.raises(NorthpassQuizLogEmptyError, match="quiz_attempt_answers has no rows to sync"):
            _rows("quiz_attempt_answers", _make_manager())

        assert sent == [WEBHOOKS_URL]

    @parameterized.expand(
        [
            ("empty_page", _page([])),
            ("ignored_404", _resp({"errors": []}, status=404)),
        ]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_answers_yield_nothing_when_the_log_attempt_has_no_answers(
        self, _name: str, answers: Response, mock_make_session: mock.MagicMock
    ) -> None:
        answers_url = "https://api.northpass.com/v2/quiz_attempts/at1/answers?limit=100"
        sent = _wire(mock_make_session, {WEBHOOKS_URL: _page([_quiz_message("at1")]), answers_url: answers})

        rows = _rows("quiz_attempt_answers", _make_manager())

        assert rows == []
        assert sent == [WEBHOOKS_URL, answers_url]


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
