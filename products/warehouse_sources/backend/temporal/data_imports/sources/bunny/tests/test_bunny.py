import json
from typing import Any

import pytest
from unittest import mock

import requests
from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.bunny.bunny import (
    BUNNY_BASE_URL,
    PER_PAGE,
    BunnyResumeConfig,
    bunny_source,
    check_access,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.bunny.settings import BUNNY_ENDPOINTS, ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# check_access builds its own tracked session in the bunny module.
BUNNY_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.bunny.bunny.make_tracked_session"
)


def _response(
    items: list[dict[str, Any]] | None,
    *,
    has_more: bool = False,
    drop_items: bool = False,
    status_code: int = 200,
) -> Response:
    body: dict[str, Any] = {"CurrentPage": 1, "TotalItems": len(items or []), "HasMoreItems": has_more}
    if not drop_items:
        body["Items"] = items or []
    resp = Response()
    resp.status_code = status_code
    resp.url = f"{BUNNY_BASE_URL}/pullzone"
    resp.reason = "Error" if status_code >= 400 else "OK"
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: BunnyResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and return a list that captures each request's params AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so inspecting it after the run
    shows only the final state — snapshot a copy when each request is prepared instead.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(manager: mock.MagicMock, endpoint: str = "pull_zones"):
    return bunny_source(
        access_key="bunny-key",
        endpoint=endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager,
    )


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_single_page_yields_items_and_stops(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response([{"Id": 1}, {"Id": 2}], has_more=False)])

        manager = _make_manager()
        rows = _rows(_source(manager))

        assert rows == [{"Id": 1}, {"Id": 2}]
        assert session.send.call_count == 1
        assert params[0] == {"page": 1, "perPage": PER_PAGE}
        # No further pages, so no resume state is persisted.
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_follows_pagination_until_has_more_is_false(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _response([{"Id": 1}], has_more=True),
                _response([{"Id": 2}], has_more=True),
                _response([{"Id": 3}], has_more=False),
            ],
        )

        manager = _make_manager()
        rows = _rows(_source(manager))

        assert rows == [{"Id": 1}, {"Id": 2}, {"Id": 3}]
        assert [p["page"] for p in params] == [1, 2, 3]
        assert all(p["perPage"] == PER_PAGE for p in params)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_saves_next_page_after_yielding_each_batch(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"Id": 1}], has_more=True), _response([{"Id": 2}], has_more=False)])

        manager = _make_manager()
        _rows(_source(manager))

        # State is saved AFTER page 1 is yielded (pointing at page 2), and never for the final page.
        assert [call.args[0] for call in manager.save_state.call_args_list] == [BunnyResumeConfig(next_page=2)]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_page(self, MockSession) -> None:
        session = MockSession.return_value
        # Page 1 must never be fetched on resume.
        params = _wire(session, [_response([{"Id": 2}], has_more=True), _response([{"Id": 3}], has_more=False)])

        manager = _make_manager(BunnyResumeConfig(next_page=2))
        rows = _rows(_source(manager))

        assert rows == [{"Id": 2}, {"Id": 3}]
        assert [p["page"] for p in params] == [2, 3]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_page_with_has_more_continues(self, MockSession) -> None:
        session = MockSession.return_value
        # Termination follows HasMoreItems, not page emptiness — an empty page mid-stream must not
        # end the sync early.
        _wire(session, [_response([], has_more=True), _response([{"Id": 9}], has_more=False)])

        manager = _make_manager()
        rows = _rows(_source(manager))

        assert rows == [{"Id": 9}]
        assert session.send.call_count == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_items_key_raises_loudly(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response(None, drop_items=True)])

        # A 200 body without "Items" means the response shape changed — fail loud, not silently 0 rows.
        with pytest.raises(ValueError, match="matched nothing"):
            _rows(_source(_make_manager()))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_access_key_travels_via_redacting_auth(self, MockSession) -> None:
        session = MockSession.return_value
        session.headers = {}
        captured_auth: list[Any] = []

        def _prepare(request: Any) -> mock.MagicMock:
            captured_auth.append(request.auth)
            return mock.MagicMock()

        session.prepare_request.side_effect = _prepare
        session.send.side_effect = [_response([{"Id": 1}], has_more=False)]

        _rows(_source(_make_manager()))

        # The secret goes through the framework auth (value-redacted in logs), not plain headers.
        assert captured_auth[0].api_key == "bunny-key"
        assert captured_auth[0].name == "AccessKey"
        assert captured_auth[0].location == "header"
        assert session.headers.get("Accept") == "application/json"
        assert "AccessKey" not in session.headers


class TestErrorHandling:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    @mock.patch("tenacity.nap.time.sleep")
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_retryable_statuses_are_retried_then_succeed(
        self, _name: str, status: int, MockSession, _mock_sleep
    ) -> None:
        session = MockSession.return_value
        _wire(session, [_response([], status_code=status), _response([{"Id": 1}], has_more=False)])

        rows = _rows(_source(_make_manager()))

        assert rows == [{"Id": 1}]
        assert session.send.call_count == 2

    @mock.patch("tenacity.nap.time.sleep")
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_persistent_server_error_exhausts_retries(self, MockSession, _mock_sleep) -> None:
        session = MockSession.return_value
        _wire(session, [_response([], status_code=500)] * 5)

        with pytest.raises(RESTClientRetryableError):
            _rows(_source(_make_manager()))
        assert session.send.call_count == 5

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_client_errors_raise_for_status(self, _name: str, status: int, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([], status_code=status)])

        with pytest.raises(requests.HTTPError):
            _rows(_source(_make_manager()))
        # Credential problems are permanent — no retries.
        assert session.send.call_count == 1


class TestCheckAccess:
    @pytest.mark.parametrize(
        "status, expected",
        [
            (200, (True, 200)),
            (401, (False, 401)),
            (403, (False, 403)),
            (500, (False, 500)),
        ],
    )
    @mock.patch(BUNNY_SESSION_PATCH)
    def test_status_mapping(self, mock_session, status: int, expected: tuple[bool, int]) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status)
        assert check_access("bunny-key") == expected

    @mock.patch(BUNNY_SESSION_PATCH)
    def test_connection_error_maps_to_none(self, mock_session) -> None:
        mock_session.return_value.get.side_effect = requests.ConnectionError("boom")
        assert check_access("bunny-key") == (False, None)


class TestBunnySourceResponse:
    @parameterized.expand(
        [
            ("pull_zones", None),
            ("storage_zones", None),
            ("dns_zones", "DateCreated"),
            ("video_libraries", "DateCreated"),
        ]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_partitioning_matches_endpoint_config(self, endpoint: str, partition_key: str | None, MockSession) -> None:
        MockSession.return_value.headers = {}
        response = _source(_make_manager(), endpoint=endpoint)
        assert response.name == endpoint
        assert response.primary_keys == ["Id"]
        if partition_key is None:
            assert response.partition_mode is None
            assert response.partition_keys is None
        else:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [partition_key]

    def test_every_endpoint_uses_id_primary_key(self) -> None:
        # bunny.net IDs are globally unique, so a single `Id` key is sufficient table-wide.
        assert all(config.primary_keys == ["Id"] for config in BUNNY_ENDPOINTS.values())
        assert set(BUNNY_ENDPOINTS) == set(ENDPOINTS)
