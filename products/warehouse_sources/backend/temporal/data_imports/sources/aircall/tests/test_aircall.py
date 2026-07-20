import json
from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

from requests import Response
from requests.auth import AuthBase

from products.warehouse_sources.backend.temporal.data_imports.sources.aircall.aircall import (
    AircallResumeConfig,
    _build_params,
    _build_url,
    _to_epoch,
    aircall_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aircall.settings import (
    AIRCALL_ENDPOINTS,
    ENDPOINTS,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the aircall module.
AIRCALL_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.aircall.aircall.make_tracked_session"
)


def _response(items_key: str, items: list[dict[str, Any]], next_link: str | None) -> Response:
    body = {"meta": {"next_page_link": next_link}, items_key: items}
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: AircallResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and return a list capturing each request AT PREPARE TIME.

    ``request.params``/``request.url`` are mutated in place across pages, so inspecting them
    after the run shows only the final state — snapshot a copy when each request is prepared.
    """
    session.headers = {}
    snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        snapshots.append({"url": request.url, "params": dict(request.params or {}), "auth": request.auth})
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


def _source(endpoint: str, manager: mock.MagicMock, **kwargs: Any):
    return aircall_source("id", "token", endpoint, team_id=1, job_id="j", resumable_source_manager=manager, **kwargs)


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestToEpoch:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (None, None),
            (1700000000, 1700000000),
            (1700000000.9, 1700000000),
            ("1700000000", 1700000000),
            (datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC), 1700000000),
            (date(2023, 11, 15), int(datetime(2023, 11, 15, tzinfo=UTC).timestamp())),
            ("not-a-number", None),
            (True, None),
        ],
    )
    def test_to_epoch_values(self, value, expected):
        assert _to_epoch(value) == expected


class TestBuildParams:
    def test_incremental_endpoint_requests_ascending_order(self):
        params = _build_params(AIRCALL_ENDPOINTS["calls"], from_value=None)
        assert params["order"] == "asc"
        assert params["per_page"] == 50
        assert "from" not in params

    def test_from_value_included_when_set(self):
        params = _build_params(AIRCALL_ENDPOINTS["calls"], from_value=1700000000)
        assert params["from"] == 1700000000

    def test_full_refresh_endpoint_without_cursor_has_no_order(self):
        params = _build_params(AIRCALL_ENDPOINTS["teams"], from_value=None)
        assert "order" not in params
        assert "from" not in params


class TestBuildUrl:
    def test_no_params(self):
        assert _build_url("/calls", {}) == "https://api.aircall.io/v1/calls"

    def test_drops_none_values_and_encodes(self):
        url = _build_url("/calls", {"per_page": 50, "from": None, "order": "asc"})
        assert url == "https://api.aircall.io/v1/calls?per_page=50&order=asc"


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected",
        [
            (200, True),
            (401, False),
            (403, False),
            (500, False),
        ],
    )
    @mock.patch(AIRCALL_SESSION_PATCH)
    def test_validate_credentials_status_mapping(self, mock_session, status_code, expected):
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status_code)

        assert validate_credentials("id", "token") is expected

    @mock.patch(AIRCALL_SESSION_PATCH)
    def test_validate_credentials_swallows_exceptions(self, mock_session):
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("id", "token") is False

    @mock.patch(AIRCALL_SESSION_PATCH)
    def test_validate_credentials_probes_ping_with_basic_auth(self, mock_session):
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)

        validate_credentials("id", "token")

        call = mock_session.return_value.get.call_args
        assert call.args[0] == "https://api.aircall.io/v1/ping"
        assert call.kwargs["auth"].username == "id"
        assert call.kwargs["auth"].password == "token"


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_via_next_page_link(self, MockSession):
        session = MockSession.return_value
        requests_seen = _wire(
            session,
            [
                _response("users", [{"id": 1}, {"id": 2}], "https://api.aircall.io/v1/users?page=2"),
                _response("users", [{"id": 3}], None),
            ],
        )

        manager = _make_manager()
        rows = _rows(_source("users", manager))

        assert [row["id"] for row in rows] == [1, 2, 3]
        assert requests_seen[0]["url"] == "https://api.aircall.io/v1/users"
        assert requests_seen[0]["params"] == {"per_page": 50}
        # The next-page URL is self-contained; original params are dropped.
        assert requests_seen[1]["url"] == "https://api.aircall.io/v1/users?page=2"
        assert requests_seen[1]["params"] == {}
        # State is saved only while a next page exists.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == AircallResumeConfig(
            next_url="https://api.aircall.io/v1/users?page=2"
        )

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_requests_carry_basic_auth(self, MockSession):
        session = MockSession.return_value
        requests_seen = _wire(session, [_response("teams", [{"id": 1}], None)])

        _rows(_source("teams", _make_manager()))

        auth = requests_seen[0]["auth"]
        assert isinstance(auth, AuthBase)
        assert auth.username == "id"
        assert auth.password == "token"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_state(self, MockSession):
        session = MockSession.return_value
        requests_seen = _wire(session, [_response("users", [{"id": 9}], None)])

        resume_url = "https://api.aircall.io/v1/users?page=5"
        manager = _make_manager(AircallResumeConfig(next_url=resume_url))

        rows = _rows(_source("users", manager))

        assert [row["id"] for row in rows] == [9]
        assert requests_seen[0]["url"] == resume_url
        assert requests_seen[0]["params"] == {}

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_reanchors_from_cursor_to_page_around_cap(self, MockSession):
        # First window ends without a next link; the latest started_at is used to issue a
        # fresh `from`-anchored request, then that window ends with no new advancement.
        session = MockSession.return_value
        requests_seen = _wire(
            session,
            [
                _response("calls", [{"id": 1, "started_at": 100}, {"id": 2, "started_at": 200}], None),
                _response("calls", [{"id": 2, "started_at": 200}], None),
            ],
        )

        manager = _make_manager()
        rows = _rows(_source("calls", manager))

        # Two requests: original window + one re-anchored window.
        assert len(requests_seen) == 2
        assert "from=200" in requests_seen[1]["url"]
        # The re-anchored window URL is checkpointed like a next-page link.
        manager.save_state.assert_called_once()
        assert "from=200" in manager.save_state.call_args.args[0].next_url
        # Boundary row re-emitted; merge on primary key dedupes downstream.
        assert [row["id"] for row in rows] == [1, 2, 2]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_no_reanchor_for_full_refresh_endpoint(self, MockSession):
        session = MockSession.return_value
        requests_seen = _wire(session, [_response("teams", [{"id": 1}], None)])

        _rows(_source("teams", _make_manager()))

        assert len(requests_seen) == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_response_stops(self, MockSession):
        session = MockSession.return_value
        _wire(session, [_response("calls", [], None)])

        manager = _make_manager()
        rows = _rows(_source("calls", manager))

        assert rows == []
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_run_anchors_from_on_watermark(self, MockSession):
        session = MockSession.return_value
        requests_seen = _wire(session, [_response("calls", [{"id": 1, "started_at": 1700000000}], None)])

        _rows(
            _source(
                "calls",
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=1700000000,
                incremental_field="started_at",
            )
        )

        assert requests_seen[0]["params"] == {"per_page": 50, "order": "asc", "from": 1700000000}
        # started_at did not advance past the watermark, so no re-anchored window is issued.
        assert len(requests_seen) == 1


class TestAircallSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_response_metadata_per_endpoint(self, MockSession, endpoint):
        config = AIRCALL_ENDPOINTS[endpoint]
        response = _source(endpoint, _make_manager())

        assert response.name == endpoint
        assert response.primary_keys == [config.primary_key]
        assert response.sort_mode == "asc"
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    @pytest.mark.parametrize("config", list(AIRCALL_ENDPOINTS.values()))
    def test_partition_keys_are_stable_creation_fields(self, config):
        if config.partition_key:
            assert config.partition_key in {"started_at", "created_at"}
