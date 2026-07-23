import json
from datetime import UTC, date, datetime
from typing import Any

from unittest import mock

import pytest
from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import APIKeyAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.eppo.eppo import (
    BASE_URL,
    _build_params,
    _format_since,
    eppo_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.eppo.settings import PAGE_LIMIT

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the eppo module.
EPPO_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.eppo.eppo.make_tracked_session"


class TestFormatSince:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14Z"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14Z"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00Z"),
            ("string_passthrough", "2026-03-04T02:58:14Z", "2026-03-04T02:58:14Z"),
        ]
    )
    def test_format(self, _name: str, value: Any, expected: str) -> None:
        result = _format_since(value)
        assert result == expected
        assert "+00:00" not in result


class TestBuildParams:
    def test_incremental_endpoint_with_cursor_adds_created_since(self) -> None:
        params = _build_params(
            "Experiments",
            incremental_field="created_date",
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
        )
        assert params == {"created_since": "2026-03-04T02:58:14Z"}

    def test_incremental_endpoint_without_cursor_omits_created_since(self) -> None:
        params = _build_params(
            "Experiments",
            incremental_field="created_date",
            should_use_incremental_field=True,
            db_incremental_field_last_value=None,
        )
        assert params == {}

    def test_full_refresh_endpoint_never_filters(self) -> None:
        # Metrics has no server-side timestamp filter; a cursor must not leak into the request.
        params = _build_params(
            "Metrics",
            incremental_field=None,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
        )
        assert params == {}

    def test_static_params_carried_for_feature_flags(self) -> None:
        params = _build_params(
            "FeatureFlags",
            incremental_field=None,
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
        )
        assert params == {"include_archived": "true"}

    def test_static_params_carried_for_audiences(self) -> None:
        params = _build_params(
            "Audiences",
            incremental_field=None,
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
        )
        assert params == {"status": "all"}


def _response(items: list[dict[str, Any]]) -> Response:
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(items).encode()
    return resp


def _redirect_response(location: str) -> Response:
    resp = Response()
    resp.status_code = 302
    resp.headers["Location"] = location
    resp._content = b""
    return resp


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and return a list that captures each request AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so inspecting it after the
    run shows only the final state — snapshot a copy when each request is prepared instead.
    """
    session.headers = {}
    snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        snapshots.append({"url": request.url, "params": dict(request.params or {}), "auth": request.auth})
        # Carry the real URL onto the prepared request so the client's host-pinning check
        # (allowed_hosts) sees the Eppo origin rather than a MagicMock.
        prepared = mock.MagicMock()
        prepared.url = request.url
        return prepared

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


def _source(endpoint: str, **kwargs: Any):
    defaults: dict[str, Any] = {
        "incremental_field": None,
        "should_use_incremental_field": False,
        "db_incremental_field_last_value": None,
    }
    defaults.update(kwargs)
    return eppo_source(api_key="key", endpoint=endpoint, team_id=1, job_id="j", **defaults)


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestEppoSourcePagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginated_endpoint_stops_on_short_page(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [
                _response([{"id": i} for i in range(PAGE_LIMIT)]),
                _response([{"id": PAGE_LIMIT}]),
            ],
        )

        rows = _rows(_source("Experiments"))

        assert len(rows) == PAGE_LIMIT + 1
        assert session.send.call_count == 2
        assert snapshots[0]["url"] == f"{BASE_URL}/experiments"
        assert snapshots[0]["params"] == {"limit": PAGE_LIMIT, "offset": 0}
        assert snapshots[1]["params"] == {"limit": PAGE_LIMIT, "offset": PAGE_LIMIT}

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginated_endpoint_stops_on_empty_page(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([])])

        rows = _rows(_source("Holdouts"))

        assert rows == []
        assert session.send.call_count == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_unpaginated_endpoint_fetches_single_page_with_no_offset_params(self, MockSession) -> None:
        session = MockSession.return_value
        # A full-limit-sized page would normally imply another page exists, but Tags has no
        # documented offset/limit — it must not be treated as paginated.
        snapshots = _wire(session, [_response([{"id": i} for i in range(PAGE_LIMIT)])])

        rows = _rows(_source("Tags"))

        assert len(rows) == PAGE_LIMIT
        assert session.send.call_count == 1
        assert "limit" not in snapshots[0]["params"]
        assert "offset" not in snapshots[0]["params"]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_auth_is_framework_api_key(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response([{"id": 1}])])

        _rows(_source("Environments"))

        auth = snapshots[0]["auth"]
        assert isinstance(auth, APIKeyAuth)
        assert auth.api_key == "key"
        assert auth.name == "X-Eppo-Token"
        assert auth.location == "header"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_sync_client_refuses_off_origin_redirect(self, MockSession) -> None:
        # A 3xx from the Eppo API must not be followed — otherwise the X-Eppo-Token header would be
        # replayed to the redirect target. The client is pinned with allow_redirects=False.
        session = MockSession.return_value
        _wire(session, [_redirect_response("https://evil.example/steal")])

        with pytest.raises(ValueError, match="refusing to follow"):
            _rows(_source("Experiments"))

        assert session.send.call_args.kwargs["allow_redirects"] is False

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_cursor_added_to_request(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response([{"id": 1}])])

        _rows(
            _source(
                "Experiments",
                incremental_field="created_date",
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
            )
        )

        assert snapshots[0]["params"]["created_since"] == "2026-03-04T02:58:14Z"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_static_params_present_for_feature_flags_and_audiences(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response([{"id": 1}])])
        _rows(_source("FeatureFlags"))
        assert snapshots[0]["params"]["include_archived"] == "true"

        session2 = MockSession.return_value
        snapshots2 = _wire(session2, [_response([{"id": 1}])])
        _rows(_source("Audiences"))
        assert snapshots2[-1]["params"]["status"] == "all"

    @parameterized.expand(
        [
            ("Experiments", ["id"]),
            ("Metrics", ["id"]),
            ("MetricCollections", ["id"]),
            ("FeatureFlags", ["id"]),
            ("Bandits", ["id"]),
            ("Holdouts", ["id"]),
            ("Teams", ["id"]),
            ("Tags", ["id"]),
            ("Audiences", ["id"]),
            ("Environments", ["id"]),
        ]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_primary_keys_per_endpoint(self, endpoint: str, expected_keys: list[str], MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"id": 1}])])

        response = _source(endpoint)

        assert response.primary_keys == expected_keys

    @parameterized.expand(
        [
            ("Experiments", "created_date"),
            ("Metrics", "created_date"),
            ("MetricCollections", None),
            ("FeatureFlags", "created_at"),
            ("Bandits", "created_at"),
            ("Holdouts", "created_at"),
            ("Teams", None),
            ("Tags", "created_at"),
            ("Audiences", "created_at"),
            ("Environments", "created_at"),
        ]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_partition_keys_per_endpoint(self, endpoint: str, expected_partition: str | None, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"id": 1}])])

        response = _source(endpoint)

        if expected_partition is None:
            assert response.partition_keys is None
            assert response.partition_mode is None
        else:
            assert response.partition_keys == [expected_partition]
            assert response.partition_mode == "datetime"


class TestValidateCredentials:
    @mock.patch(EPPO_SESSION_PATCH)
    def test_ok(self, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)
        assert validate_credentials("key") == (True, 200)

    @mock.patch(EPPO_SESSION_PATCH)
    def test_unauthorized(self, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=401)
        assert validate_credentials("key") == (False, 401)

    @mock.patch(EPPO_SESSION_PATCH)
    def test_swallows_transport_errors(self, mock_session) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("key") == (False, None)

    @mock.patch(EPPO_SESSION_PATCH)
    def test_probes_experiments_endpoint_with_token_header(self, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)
        validate_credentials("key")

        call = mock_session.return_value.get.call_args
        assert call.args[0] == f"{BASE_URL}/experiments?limit=1"
        assert call.kwargs["headers"]["X-Eppo-Token"] == "key"

    @mock.patch(EPPO_SESSION_PATCH)
    def test_probe_session_disables_redirects(self, mock_session) -> None:
        # The probe carries the token; a redirect must not be followed off the validated Eppo host.
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)
        validate_credentials("key")
        assert mock_session.call_args.kwargs["allow_redirects"] is False
