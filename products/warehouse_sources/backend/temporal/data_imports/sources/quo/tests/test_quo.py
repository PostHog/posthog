import json
from datetime import UTC, date, datetime
from typing import Any, Optional

import pytest
from unittest import mock

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import APIKeyAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import UnknownResourceError
from products.warehouse_sources.backend.temporal.data_imports.sources.quo.quo import (
    QuoResumeConfig,
    _to_iso,
    quo_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.quo.settings import ENDPOINTS, QUO_ENDPOINTS

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials and the fan-out build their own tracked session in the quo module.
QUO_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.quo.quo.make_tracked_session"

WATERMARK = datetime(2026, 1, 1, tzinfo=UTC)
WATERMARK_ISO = "2026-01-01T00:00:00+00:00"


def _body(items: list[dict[str, Any]], next_page_token: str | None) -> dict[str, Any]:
    body: dict[str, Any] = {"data": items}
    if next_page_token is not None:
        body["nextPageToken"] = next_page_token
    return body


def _response(items: list[dict[str, Any]], next_page_token: str | None = None) -> Response:
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(_body(items, next_page_token)).encode()
    return resp


def _json_response(items: list[dict[str, Any]], next_page_token: str | None = None) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.status_code = 200
    resp.json.return_value = _body(items, next_page_token)
    return resp


def _make_manager(resume_state: QuoResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and return a list capturing each request AT PREPARE TIME.

    ``request.params``/``request.url`` are mutated in place across pages, so inspecting them
    after the run shows only the final state; snapshot a copy when each request is prepared.
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
    return quo_source("key", endpoint, team_id=1, job_id="j", resumable_source_manager=manager, **kwargs)


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestToIso:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (None, None),
            (datetime(2026, 1, 1, tzinfo=UTC), "2026-01-01T00:00:00+00:00"),
            (datetime(2026, 1, 1), "2026-01-01T00:00:00+00:00"),
            (date(2026, 1, 2), "2026-01-02T00:00:00+00:00"),
            ("2026-01-01T00:00:00Z", "2026-01-01T00:00:00+00:00"),
            (1700000000, None),
        ],
    )
    def test_to_iso_values(self, value: Any, expected: Optional[str]):
        assert _to_iso(value) == expected


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
    @mock.patch(QUO_SESSION_PATCH)
    def test_validate_credentials_status_mapping(self, mock_session, status_code, expected):
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status_code)

        assert validate_credentials("key") is expected

    @mock.patch(QUO_SESSION_PATCH)
    def test_validate_credentials_swallows_exceptions(self, mock_session):
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("key") is False

    @mock.patch(QUO_SESSION_PATCH)
    def test_validate_credentials_probes_phone_numbers_with_raw_key(self, mock_session):
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)

        validate_credentials("key")

        call = mock_session.return_value.get.call_args
        assert call.args[0] == "https://api.quo.com/v1/phone-numbers"
        # Quo takes the raw key in the Authorization header, with no Bearer prefix.
        assert call.kwargs["headers"]["Authorization"] == "key"


class TestTopLevelPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_via_page_token(self, MockSession):
        session = MockSession.return_value
        requests_seen = _wire(
            session,
            [
                _response([{"id": "US1"}, {"id": "US2"}], next_page_token="tok"),
                _response([{"id": "US3"}]),
            ],
        )

        manager = _make_manager()
        rows = _rows(_source("users", manager))

        assert [row["id"] for row in rows] == ["US1", "US2", "US3"]
        assert requests_seen[0]["params"] == {"maxResults": 50}
        assert requests_seen[1]["params"] == {"maxResults": 50, "pageToken": "tok"}
        # State is saved only while a next page exists.
        manager.save_state.assert_called_once_with(QuoResumeConfig(page_token="tok"))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_requests_carry_api_key_in_authorization_header(self, MockSession):
        session = MockSession.return_value
        requests_seen = _wire(session, [_response([{"id": "US1"}])])

        _rows(_source("users", _make_manager()))

        auth = requests_seen[0]["auth"]
        assert isinstance(auth, APIKeyAuth)
        assert auth.name == "Authorization"
        assert auth.api_key == "key"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_state(self, MockSession):
        session = MockSession.return_value
        requests_seen = _wire(session, [_response([{"id": "US9"}])])

        manager = _make_manager(QuoResumeConfig(page_token="tok5"))
        rows = _rows(_source("users", manager))

        assert [row["id"] for row in rows] == ["US9"]
        assert requests_seen[0]["params"]["pageToken"] == "tok5"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_unpaginated_endpoint_issues_one_request_without_page_size(self, MockSession):
        session = MockSession.return_value
        requests_seen = _wire(session, [_response([{"id": "PN1"}])])

        rows = _rows(_source("phone_numbers", _make_manager()))

        assert [row["id"] for row in rows] == ["PN1"]
        assert len(requests_seen) == 1
        assert requests_seen[0]["params"] == {}

    @pytest.mark.parametrize(
        "incremental_field, expected_param",
        [
            ("createdAt", "createdAfter"),
            ("updatedAt", "updatedAfter"),
        ],
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_run_maps_cursor_field_to_server_filter(self, MockSession, incremental_field, expected_param):
        session = MockSession.return_value
        requests_seen = _wire(session, [_response([{"id": "CN1"}])])

        _rows(
            _source(
                "conversations",
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=WATERMARK,
                incremental_field=incremental_field,
            )
        )

        assert requests_seen[0]["params"] == {"maxResults": 100, expected_param: WATERMARK_ISO}

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_full_refresh_omits_time_filters(self, MockSession):
        session = MockSession.return_value
        requests_seen = _wire(session, [_response([{"id": "CN1"}])])

        _rows(_source("conversations", _make_manager()))

        assert requests_seen[0]["params"] == {"maxResults": 100}


class TestFanOut:
    def _fan_out_requests(self, session: mock.MagicMock) -> list[tuple[str, dict[str, Any]]]:
        return [(call.args[0], dict(call.kwargs.get("params") or {})) for call in session.get.call_args_list]

    @mock.patch(QUO_SESSION_PATCH)
    def test_calls_fan_out_per_conversation(self, mock_session):
        session = mock_session.return_value
        session.get.side_effect = [
            _json_response(
                [
                    {"id": "CN1", "phoneNumberId": "PN1", "participants": ["+15550001"]},
                    {"id": "CN2", "phoneNumberId": "PN2", "participants": ["+15550002"]},
                ]
            ),
            _json_response([{"id": "AC1"}]),
            _json_response([{"id": "AC2"}]),
        ]

        rows = _rows(_source("calls", _make_manager()))

        assert [row["id"] for row in rows] == ["AC1", "AC2"]
        requests_seen = self._fan_out_requests(session)
        assert requests_seen[0] == ("https://api.quo.com/v1/conversations", {"maxResults": 100})
        assert requests_seen[1] == (
            "https://api.quo.com/v1/calls",
            {"maxResults": 100, "phoneNumberId": "PN1", "participants": ["+15550001"]},
        )
        assert requests_seen[2] == (
            "https://api.quo.com/v1/calls",
            {"maxResults": 100, "phoneNumberId": "PN2", "participants": ["+15550002"]},
        )

    @pytest.mark.parametrize(
        "endpoint, expected_group_queried",
        [
            # /v1/calls serves one-to-one conversations only; /v1/messages accepts the group's
            # full participants array.
            ("calls", False),
            ("messages", True),
        ],
    )
    @mock.patch(QUO_SESSION_PATCH)
    def test_group_conversations_skipped_for_calls_only(self, mock_session, endpoint, expected_group_queried):
        session = mock_session.return_value
        group_conversation = {"id": "CN1", "phoneNumberId": "PN1", "participants": ["+15550001", "+15550002"]}
        one_to_one = {"id": "CN2", "phoneNumberId": "PN1", "participants": ["+15550003"]}
        child_pages = [_json_response([{"id": "A1"}])]
        if expected_group_queried:
            child_pages.append(_json_response([{"id": "A2"}]))
        session.get.side_effect = [_json_response([group_conversation, one_to_one]), *child_pages]

        _rows(_source(endpoint, _make_manager()))

        child_requests = self._fan_out_requests(session)[1:]
        participants_queried = [params["participants"] for _url, params in child_requests]
        if expected_group_queried:
            assert participants_queried == [["+15550001", "+15550002"], ["+15550003"]]
        else:
            assert participants_queried == [["+15550003"]]

    @mock.patch(QUO_SESSION_PATCH)
    def test_duplicate_and_incomplete_conversations_produce_no_extra_requests(self, mock_session):
        session = mock_session.return_value
        session.get.side_effect = [
            _json_response(
                [
                    {"id": "CN1", "phoneNumberId": "PN1", "participants": ["+15550001"]},
                    # Same pair again (e.g. a deleted and recreated conversation).
                    {"id": "CN2", "phoneNumberId": "PN1", "participants": ["+15550001"]},
                    {"id": "CN3", "phoneNumberId": None, "participants": ["+15550002"]},
                    {"id": "CN4", "phoneNumberId": "PN1", "participants": []},
                ]
            ),
            _json_response([{"id": "AM1"}]),
        ]

        rows = _rows(_source("messages", _make_manager()))

        assert [row["id"] for row in rows] == ["AM1"]
        assert len(session.get.call_args_list) == 2

    @mock.patch(QUO_SESSION_PATCH)
    def test_child_pagination_follows_page_token(self, mock_session):
        session = mock_session.return_value
        session.get.side_effect = [
            _json_response([{"id": "CN1", "phoneNumberId": "PN1", "participants": ["+15550001"]}]),
            _json_response([{"id": "AC1"}], next_page_token="tok"),
            _json_response([{"id": "AC2"}]),
        ]

        rows = _rows(_source("calls", _make_manager()))

        assert [row["id"] for row in rows] == ["AC1", "AC2"]
        requests_seen = self._fan_out_requests(session)
        assert requests_seen[2][1]["pageToken"] == "tok"

    @mock.patch(QUO_SESSION_PATCH)
    def test_incremental_watermark_applied_to_child_requests_only(self, mock_session):
        session = mock_session.return_value
        session.get.side_effect = [
            _json_response([{"id": "CN1", "phoneNumberId": "PN1", "participants": ["+15550001"]}]),
            _json_response([{"id": "AC1"}]),
        ]

        _rows(
            _source(
                "calls",
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=WATERMARK,
                incremental_field="createdAt",
            )
        )

        requests_seen = self._fan_out_requests(session)
        # The parent walk stays unfiltered: an old conversation can still receive new calls.
        assert "createdAfter" not in requests_seen[0][1]
        assert requests_seen[1][1]["createdAfter"] == WATERMARK_ISO


class TestQuoSourceResponse:
    def test_unknown_endpoint_raises_unknown_resource(self):
        with pytest.raises(UnknownResourceError):
            _source("not_a_table", _make_manager())

    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_response_metadata_per_endpoint(self, MockSession, endpoint):
        config = QUO_ENDPOINTS[endpoint]
        response = _source(endpoint, _make_manager())

        assert response.name == endpoint
        assert response.primary_keys == [config.primary_key]
        # Quo lists return newest-first, so the watermark must only commit at sync end.
        assert response.sort_mode == "desc"
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    @pytest.mark.parametrize("config", list(QUO_ENDPOINTS.values()))
    def test_partition_keys_are_stable_creation_fields(self, config):
        if config.partition_key:
            assert config.partition_key == "createdAt"
