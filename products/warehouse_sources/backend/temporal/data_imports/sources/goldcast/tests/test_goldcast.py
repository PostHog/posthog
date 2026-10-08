import json
from collections.abc import Iterable
from typing import Any, cast

import pytest
from unittest import mock

import requests
from parameterized import parameterized
from requests import Response

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
    return [row for page in cast("Iterable[Any]", response.items()) for row in page]


class TestTopLevelEndpoints:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_broadcasts_drop_stream_credentials(self, MockSession) -> None:
        _wire(
            MockSession.return_value,
            [
                _response(
                    [
                        {
                            "id": "b1",
                            "title": "Keynote",
                            "youtube_stream_key": "yt-fake-key",
                            "facebook_stream_key": "fb-fake-key",
                            "custom_stream_key": "custom-fake-key",
                            "external_rtmp_push_stream": "rtmp://stream.example.com/live/fake-key",
                            "wordly_session_key": "wordly-fake-key",
                            "medialive_rtmp_input_details": {"in_stream_key": "rtmp-fake-key"},
                        }
                    ]
                )
            ],
        )
        assert _rows("tok", "broadcasts") == [{"id": "b1", "title": "Keynote"}]


class TestFanOut:
    @parameterized.expand(
        [
            ("webinars", "/event/", "/event/webinars/p1/", "event"),
            ("speakers", "/event/", "/event/p1/public/v1/speakers/", "event"),
            ("broadcast_polls", "/event/broadcasts/", "/event/broadcasts/p1/polls/", "broadcast"),
        ]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_child_request_binds_parent_id_and_stamps_it(
        self, endpoint: str, parent_path: str, child_path: str, parent_field: str, MockSession
    ) -> None:
        snaps = _wire(MockSession.return_value, [_response([{"id": "p1"}]), _response([{"id": "c1"}])])

        assert _rows("tok", endpoint) == [{"id": "c1", parent_field: "p1"}]
        assert snaps[0]["url"] == f"https://customapi.goldcast.io{parent_path}"
        assert snaps[1]["url"] == f"https://customapi.goldcast.io{child_path}"

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
    def test_sync_session_redacts_token_and_skips_sample_capture(self, MockSession) -> None:
        # The token rides in the non-standard `Token` auth header the name-based scrubbers can't
        # recognise, so it must be registered for value-based redaction on the tracked session.
        MockSession.return_value.headers = {}
        MockSession.return_value.prepare_request.side_effect = lambda r: mock.MagicMock()
        MockSession.return_value.send.side_effect = [_response([])]

        _rows("super-secret", "events")

        assert MockSession.call_args.kwargs.get("redact_values") == ("Token super-secret",)
        # Broadcast and webinar bodies carry stream keys the sample scrubber can't recognise.
        assert MockSession.call_args.kwargs.get("capture") is False


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
    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    @mock.patch(GOLDCAST_SESSION_PATCH)
    def test_non_200_returns_false(self, _name: str, status_code: int, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status_code)
        assert validate_credentials("tok") is False

    @mock.patch(GOLDCAST_SESSION_PATCH)
    def test_probe_registers_token_for_redaction_and_uses_token_scheme(self, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)
        validate_credentials("super-secret")

        assert mock_session.call_args.kwargs.get("redact_values") == ("super-secret",)
        _, get_kwargs = mock_session.return_value.get.call_args
        assert get_kwargs["headers"]["Authorization"] == "Token super-secret"
