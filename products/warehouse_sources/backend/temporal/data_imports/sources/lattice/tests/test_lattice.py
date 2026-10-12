import json
from typing import Any

import pytest
from unittest import mock

import requests
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.lattice.lattice import (
    LatticeResumeConfig,
    _base_url,
    lattice_source,
    validate_credentials,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the lattice module.
LATTICE_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.lattice.lattice.make_tracked_session"
)


def _response(
    items: list[dict[str, Any]] | None,
    *,
    has_more: bool = False,
    ending_cursor: str | None = None,
    page_info: bool = False,
) -> Response:
    body: dict[str, Any] = (
        {"data": items or [], "pageInfo": {"endCursor": ending_cursor, "hasNextPage": has_more}}
        if page_info
        else {"data": items or [], "hasMore": has_more, "endingCursor": ending_cursor}
    )
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: LatticeResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and capture each request's (url, params) AT SEND TIME.

    ``request.params`` is one dict mutated in place across pages, so inspect it when each request
    is prepared instead of after the run.
    """
    session.headers = {}
    snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        snapshots.append({"url": request.url, "params": dict(request.params or {})})
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(region: str, endpoint: str, manager: mock.MagicMock):
    return lattice_source(
        region=region,
        api_key="key",
        endpoint=endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager,
    )


class TestBaseUrl:
    def test_invalid_region_raises(self):
        with pytest.raises(ValueError):
            _base_url("evil.example.com")


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected_valid, expected_message",
        [
            (200, True, None),
            # Keys inherit the creating user's privileges; 403 means a scope
            # gap, not a bad key.
            (403, True, None),
            (401, False, "Invalid Lattice API key"),
        ],
    )
    @mock.patch(LATTICE_SESSION_PATCH)
    def test_validate_credentials_status_mapping(self, mock_session, status_code, expected_valid, expected_message):
        response = mock.MagicMock()
        response.status_code = status_code
        mock_session.return_value.get.return_value = response

        assert validate_credentials("us", "key") == (expected_valid, expected_message)

    @mock.patch(LATTICE_SESSION_PATCH)
    def test_validate_credentials_rejects_bad_region_without_request(self, mock_session):
        is_valid, error = validate_credentials("evil", "key")
        assert is_valid is False
        assert error is not None
        mock_session.return_value.get.assert_not_called()

    @mock.patch(LATTICE_SESSION_PATCH)
    def test_validate_credentials_transport_error_is_not_invalid_key(self, mock_session):
        # A transient connectivity failure must not be reported as a bad key.
        mock_session.return_value.get.side_effect = requests.ConnectionError("boom")

        is_valid, error = validate_credentials("us", "key")
        assert is_valid is False
        assert error is not None
        assert "Invalid Lattice API key" not in error


class TestPagination:
    @pytest.mark.parametrize(
        "endpoint, page_info",
        [
            ("users", False),
            # /v1/goals/updates nests the cursor under pageInfo instead of the top level.
            ("goal_updates", True),
        ],
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_via_ending_cursor(self, MockSession, endpoint, page_info):
        session = MockSession.return_value
        snaps = _wire(
            session,
            [
                _response([{"id": "1"}], has_more=True, ending_cursor="cur_abc", page_info=page_info),
                _response([{"id": "2"}], has_more=False, page_info=page_info),
            ],
        )

        manager = _make_manager()
        rows = _rows(_source("us", endpoint, manager))

        assert [r["id"] for r in rows] == ["1", "2"]
        # Checkpoint saved after the first page (points at the next cursor); the second page ends it.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0].starting_after == "cur_abc"
        assert snaps[1]["params"]["startingAfter"] == "cur_abc"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_cursor(self, MockSession):
        session = MockSession.return_value
        snaps = _wire(session, [_response([])])

        manager = _make_manager(LatticeResumeConfig(starting_after="cur_resume"))
        list(_source("us", "users", manager).items())

        assert snaps[0]["params"]["startingAfter"] == "cur_resume"


class TestReviewCycleFanout:
    @pytest.mark.parametrize(
        "endpoint, resume_state, expected_child_urls",
        [
            (
                "reviews",
                None,
                [
                    "https://api.latticehq.com/v1/reviewCycle/c1/reviews",
                    "https://api.latticehq.com/v1/reviewCycle/c2/reviews",
                ],
            ),
            (
                "reviewees",
                None,
                [
                    "https://api.latticehq.com/v1/reviewCycle/c1/reviewees",
                    "https://api.latticehq.com/v1/reviewCycle/c2/reviewees",
                ],
            ),
            (
                "reviews",
                LatticeResumeConfig(
                    fanout_state={"completed": ["/v1/reviewCycle/c1/reviews"], "current": None, "child_state": None}
                ),
                ["https://api.latticehq.com/v1/reviewCycle/c2/reviews"],
            ),
        ],
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_fans_out_over_review_cycles(self, MockSession, endpoint, resume_state, expected_child_urls):
        session = MockSession.return_value
        child_responses = {
            "https://api.latticehq.com/v1/reviewCycle/c1/" + endpoint: _response([{"id": "r1"}]),
            "https://api.latticehq.com/v1/reviewCycle/c2/" + endpoint: _response([{"id": "r1"}]),
        }
        snaps = _wire(session, [])
        session.send.side_effect = lambda *_args, **_kwargs: (
            _response([{"id": "c1"}, {"id": "c2"}]) if len(snaps) == 1 else child_responses[snaps[-1]["url"]]
        )

        rows = _rows(_source("us", endpoint, _make_manager(resume_state)))

        assert snaps[0]["url"] == "https://api.latticehq.com/v1/reviewCycles"
        assert [s["url"] for s in snaps[1:]] == expected_child_urls
        # Review ids repeat across cycles, so each row must carry its cycle for the composite key.
        expected_cycles = [url.split("/")[-2] for url in expected_child_urls]
        assert [(r["review_cycle_id"], r["id"]) for r in rows] == [(c, "r1") for c in expected_cycles]
