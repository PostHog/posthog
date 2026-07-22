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


class TestNorthpassSource:
    @parameterized.expand(
        [
            ("people", ["id"], "created_at"),
            ("courses", ["id"], "created_at"),
            ("course_enrollments", ["course_id", "id"], "enrolled_at"),
            ("learning_path_enrollments", ["learning_path_id", "id"], "enrolled_at"),
        ]
    )
    def test_source_response_carries_endpoint_keys_and_partitioning(self, endpoint, primary_keys, partition_key):
        response = northpass_source("key", endpoint, team_id=1, job_id="j", resumable_source_manager=_make_manager())
        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        assert response.partition_keys == [partition_key]
        assert response.partition_mode == "datetime"
        assert response.partition_format == "month"
