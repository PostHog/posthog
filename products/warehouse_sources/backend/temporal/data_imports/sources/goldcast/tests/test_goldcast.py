import json
from typing import Any

import pytest
from unittest import mock

import requests
from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import APIKeyAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.goldcast.goldcast import (
    goldcast_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.goldcast.settings import GOLDCAST_ENDPOINTS

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the goldcast module.
GOLDCAST_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.goldcast.goldcast.make_tracked_session"
)


def _response(payload: Any, *, status: int = 200, url: str = "https://customapi.goldcast.io/") -> Response:
    resp = Response()
    resp.status_code = status
    resp.url = url
    resp.reason = "OK" if status == 200 else "Error"
    resp._content = json.dumps(payload).encode() if payload is not None else b""
    return resp


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and snapshot each request (url/params/auth) AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so a copy is snapshotted when
    each request is prepared rather than inspected afterwards.
    """
    session.headers = {}
    snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        snapshots.append({"url": request.url, "params": dict(request.params or {}), "auth": request.auth})
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


def _rows(access_key: str, endpoint: str) -> list[dict[str, Any]]:
    response = goldcast_source(access_key=access_key, endpoint=endpoint, team_id=1, job_id="j")
    return [row for page in response.items() for row in page]


class TestTopLevelEndpoints:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_collection_endpoint_yields_all_rows(self, MockSession) -> None:
        _wire(MockSession.return_value, [_response([{"id": "e1"}, {"id": "e2"}])])
        assert _rows("tok", "events") == [{"id": "e1"}, {"id": "e2"}]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_single_object_endpoint_yields_one_row(self, MockSession) -> None:
        # The organization endpoint returns a single object, not a collection — it must sync as one row.
        _wire(MockSession.return_value, [_response({"id": "org1"})])
        assert _rows("tok", "organizations") == [{"id": "org1"}]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_collection_yields_nothing(self, MockSession) -> None:
        _wire(MockSession.return_value, [_response([])])
        assert _rows("tok", "events") == []


class TestFanOut:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_stamps_parent_event_id_onto_each_child_row(self, MockSession) -> None:
        # The parent event id must be injected so the composite ["event", "id"] key is unique
        # table-wide — webinar rows carry no `event` field of their own.
        _wire(
            MockSession.return_value,
            [
                _response([{"id": "e1"}, {"id": "e2"}]),
                _response([{"id": "w1"}]),
                _response([{"id": "w2"}, {"id": "w3"}]),
            ],
        )

        assert _rows("tok", "webinars") == [
            {"id": "w1", "event": "e1"},
            {"id": "w2", "event": "e2"},
            {"id": "w3", "event": "e2"},
        ]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_webinars_request_uses_event_in_path(self, MockSession) -> None:
        snaps = _wire(MockSession.return_value, [_response([{"id": "e1"}]), _response([{"id": "w1"}])])
        _rows("tok", "webinars")
        assert snaps[1]["url"] == "https://customapi.goldcast.io/event/webinars/e1/"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_event_members_query_param_path_and_restamping(self, MockSession) -> None:
        # event_members already carries `event`; the parent id re-stamps it via an `?event=` query.
        snaps = _wire(
            MockSession.return_value,
            [_response([{"id": "e1"}]), _response([{"id": "m1", "event": "stale"}])],
        )

        assert _rows("tok", "event_members") == [{"id": "m1", "event": "e1"}]
        assert snaps[1]["url"] == "https://customapi.goldcast.io/event/event-members/?event=e1"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_child_404_for_one_event_is_skipped_not_fatal(self, MockSession) -> None:
        _wire(
            MockSession.return_value,
            [
                _response([{"id": "e1"}, {"id": "e2"}]),
                _response({"detail": "Not found"}, status=404),
                _response([{"id": "w2"}]),
            ],
        )
        assert _rows("tok", "webinars") == [{"id": "w2", "event": "e2"}]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_child_non_404_error_propagates(self, MockSession) -> None:
        _wire(
            MockSession.return_value,
            [_response([{"id": "e1"}]), _response({"detail": "Forbidden"}, status=403)],
        )
        with pytest.raises(requests.HTTPError):
            _rows("tok", "webinars")

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_event_missing_id_key_fails_loudly(self, MockSession) -> None:
        # A malformed parent event (missing the required `id` fan-out key) must raise rather than
        # silently under-sync that event's children with no signal.
        _wire(MockSession.return_value, [_response([{"name": "no id"}])])
        with pytest.raises(KeyError):
            _rows("tok", "webinars")

    @parameterized.expand([("empty_string", ""), ("none", None), ("zero", 0)])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_event_with_falsy_id_fails_loudly(self, _name: str, falsy_id: Any, MockSession) -> None:
        # A falsy `id` (empty string, None, 0) must raise too — silently skipping it would
        # under-sync that event's children exactly like a missing key would.
        _wire(MockSession.return_value, [_response([{"id": falsy_id}])])
        with pytest.raises(ValueError):
            _rows("tok", "webinars")


class TestAuthAndRedaction:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_auth_uses_non_standard_token_scheme(self, MockSession) -> None:
        # Goldcast uses `Authorization: Token <key>`, not Bearer.
        snaps = _wire(MockSession.return_value, [_response([{"id": "e1"}])])
        _rows("super-secret", "events")

        auth = snaps[0]["auth"]
        assert isinstance(auth, APIKeyAuth)
        assert auth.name == "Authorization"
        assert auth.location == "header"
        assert auth.api_key == "Token super-secret"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_sync_session_registers_token_for_redaction(self, MockSession) -> None:
        # The token rides in the non-standard `Token` auth header the name-based scrubbers can't
        # recognise, so it must be registered for value-based redaction on the tracked session.
        MockSession.return_value.headers = {}
        MockSession.return_value.prepare_request.side_effect = lambda r: mock.MagicMock()
        MockSession.return_value.send.side_effect = [_response([])]

        _rows("super-secret", "events")

        assert MockSession.call_args.kwargs.get("redact_values") == ("Token super-secret",)


class TestSourceResponse:
    @parameterized.expand(
        [
            ("events", ["id"], "created_at"),
            ("organizations", ["id"], "created_at"),
            # agenda_items has no creation timestamp, so it must not be partitioned.
            ("agenda_items", ["id"], None),
            # Fan-out children carry the parent id in a composite key for table-wide uniqueness.
            ("webinars", ["event", "id"], "created_at"),
            ("event_members", ["event", "id"], "created_at"),
        ]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_partition_and_primary_keys_per_endpoint(
        self, endpoint: str, expected_keys: list[str], partition_key: str | None, MockSession
    ) -> None:
        response = goldcast_source(access_key="tok", endpoint=endpoint, team_id=1, job_id="j")

        assert response.name == endpoint
        assert response.primary_keys == expected_keys
        if partition_key is None:
            assert response.partition_mode is None
            assert response.partition_keys is None
        else:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [partition_key]

    def test_every_endpoint_declares_a_primary_key(self) -> None:
        # A non-unique / missing key seeds duplicate rows that make every later merge multi-match.
        for name, config in GOLDCAST_ENDPOINTS.items():
            assert config.primary_keys, f"{name} has no primary key"


class TestValidateCredentials:
    @mock.patch(GOLDCAST_SESSION_PATCH)
    def test_valid_token_returns_true(self, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)
        assert validate_credentials("tok") is True

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    @mock.patch(GOLDCAST_SESSION_PATCH)
    def test_non_200_returns_false(self, _name: str, status_code: int, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status_code)
        assert validate_credentials("tok") is False

    @mock.patch(GOLDCAST_SESSION_PATCH)
    def test_network_error_returns_false(self, mock_session) -> None:
        mock_session.return_value.get.side_effect = requests.ConnectionError("boom")
        assert validate_credentials("tok") is False

    @mock.patch(GOLDCAST_SESSION_PATCH)
    def test_probe_registers_token_for_redaction_and_uses_token_scheme(self, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)
        validate_credentials("super-secret")

        assert mock_session.call_args.kwargs.get("redact_values") == ("super-secret",)
        _, get_kwargs = mock_session.return_value.get.call_args
        assert get_kwargs["headers"]["Authorization"] == "Token super-secret"
