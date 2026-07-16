import json
from typing import Any

import pytest
from unittest import mock

import requests
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.campayn.campayn import (
    base_url,
    campayn_source,
    is_subdomain_valid,
    normalize_subdomain,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.campayn.settings import (
    CAMPAYN_ENDPOINTS,
    ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClient,
    RESTClientRetryableError,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the campayn module.
CAMPAYN_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.campayn.campayn.make_tracked_session"
)


def _response(body: Any, status: int = 200, reason: str | None = None, url: str | None = None) -> Response:
    resp = Response()
    resp.status_code = status
    resp._content = json.dumps(body).encode()
    resp.reason = reason
    resp.url = url  # type: ignore[assignment]
    return resp


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and snapshot each request's URL + auth headers AT PREPARE TIME.

    The framework auth object only runs against the prepared request, so we apply it to a stand-in
    with a real headers dict to observe the Authorization header it would send.
    """
    session.headers = {}
    seen: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        prepared = mock.MagicMock()
        prepared.headers = {}
        if request.auth is not None:
            request.auth(prepared)
        seen.append({"url": request.url, "auth_headers": dict(prepared.headers)})
        return prepared

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return seen


def _source(endpoint: str):
    return campayn_source("acme", "k", endpoint, team_id=1, job_id="j")


def _batches(source_response) -> list[list[dict[str, Any]]]:
    return [list(page) for page in source_response.items()]


class TestNormalizeSubdomain:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("acme", "acme"),
            ("  acme  ", "acme"),
            ("acme.campayn.com", "acme"),
            ("https://acme.campayn.com/", "acme"),
            ("http://acme.campayn.com/api/v1/lists.json", "acme"),
            ("ACME.CAMPAYN.COM", "ACME"),
        ],
    )
    def test_normalize(self, raw: str, expected: str) -> None:
        assert normalize_subdomain(raw) == expected


class TestIsSubdomainValid:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("acme", True),
            ("acme-corp", True),
            ("acme.campayn.com", True),
            ("https://acme.campayn.com", True),
            # Pasted paths/URLs collapse to the bare label, so these end up safe.
            ("acme/../evil", True),
            ("acme@evil.com", False),
            ("acme.evil.com", False),
            ("acme corp", False),
            ("", False),
        ],
    )
    def test_validity(self, raw: str, expected: bool) -> None:
        assert is_subdomain_valid(raw) is expected


class TestTopLevelEndpoints:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_lists_yields_single_batch(self, MockSession) -> None:
        session = MockSession.return_value
        seen = _wire(session, [_response([{"id": "1"}, {"id": "2"}])])

        batches = _batches(_source("lists"))

        assert batches == [[{"id": "1"}, {"id": "2"}]]
        # No pagination anywhere on Campayn's API — exactly one request per endpoint.
        assert session.send.call_count == 1
        assert seen[0]["url"] == f"{base_url('acme')}/lists.json"
        assert seen[0]["auth_headers"]["Authorization"] == "TRUEREST apikey=k"
        assert session.headers.get("Accept") == "application/json"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_response_yields_nothing(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([])])

        assert _batches(_source("emails")) == []

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_single_object_body_is_wrapped_as_one_row(self, MockSession) -> None:
        # Defensive: the docs say list endpoints return bare arrays, but a single-object body is
        # tolerated as one row rather than crashing the sync.
        session = MockSession.return_value
        _wire(session, [_response({"id": "1"})])

        assert _batches(_source("reports")) == [[{"id": "1"}]]


class TestFanOut:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_contacts_fan_out_injects_list_id(self, MockSession) -> None:
        session = MockSession.return_value
        seen = _wire(
            session,
            [
                _response([{"id": "10"}, {"id": "20"}]),
                _response([{"id": "1", "email": "a@x.com"}]),
                _response([{"id": "2", "email": "b@x.com"}]),
            ],
        )

        batches = _batches(_source("contacts"))

        assert batches == [
            [{"id": "1", "email": "a@x.com", "list_id": "10"}],
            [{"id": "2", "email": "b@x.com", "list_id": "20"}],
        ]
        assert [s["url"] for s in seen] == [
            f"{base_url('acme')}/lists.json",
            f"{base_url('acme')}/lists/10/contacts.json",
            f"{base_url('acme')}/lists/20/contacts.json",
        ]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_fan_out_stringifies_numeric_parent_id(self, MockSession) -> None:
        # The composite primary key expects list_id as a string, whatever JSON type the API returns.
        session = MockSession.return_value
        seen = _wire(session, [_response([{"id": 10}]), _response([{"id": "1"}])])

        batches = _batches(_source("contacts"))

        assert batches == [[{"id": "1", "list_id": "10"}]]
        assert seen[1]["url"] == f"{base_url('acme')}/lists/10/contacts.json"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_fan_out_with_no_lists_yields_nothing(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([])])

        assert _batches(_source("forms")) == []
        assert session.send.call_count == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_fan_out_skips_list_deleted_mid_sync(self, MockSession) -> None:
        # A list deleted between enumeration and the child fetch 404s — skip it, keep syncing.
        session = MockSession.return_value
        _wire(
            session,
            [
                _response([{"id": "10"}, {"id": "20"}]),
                _response({"error": "not found"}, status=404),
                _response([{"id": "2"}]),
            ],
        )

        batches = _batches(_source("contacts"))

        assert batches == [[{"id": "2", "list_id": "20"}]]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_fan_out_reraises_non_404_http_error(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _response([{"id": "10"}]),
                _response({"error": "forbidden"}, status=403, reason="Forbidden", url="https://x"),
            ],
        )

        with pytest.raises(requests.HTTPError, match="403 Client Error"):
            _batches(_source("forms"))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_fan_out_fails_loudly_on_parent_row_missing_id(self, MockSession) -> None:
        # `id` drives all fan-out, so a malformed list record must fail rather than silently
        # dropping its contacts/forms.
        session = MockSession.return_value
        _wire(session, [_response([{"name": "no id here"}])])

        with pytest.raises(ValueError, match="field 'id'"):
            _batches(_source("contacts"))


class TestErrorHandling:
    @pytest.mark.parametrize("status", [429, 500, 503])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_retryable_statuses_raise_retryable_error(self, MockSession, status: int) -> None:
        # Override tenacity's backoff sleep so the 5 retries don't actually wait; the client
        # reraises the last retryable error once attempts are exhausted.
        session = MockSession.return_value
        _wire(session, [_response({}, status=status) for _ in range(5)])

        with (
            mock.patch.object(RESTClient._send_request.retry, "sleep"),  # type: ignore[attr-defined]
            pytest.raises(RESTClientRetryableError),
        ):
            _batches(_source("lists"))
        assert session.send.call_count == 5

    @pytest.mark.parametrize(
        "status, reason",
        [(401, "Unauthorized"), (403, "Forbidden"), (404, "Not Found")],
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_client_errors_raise_http_error(self, MockSession, status: int, reason: str) -> None:
        session = MockSession.return_value
        _wire(session, [_response({}, status=status, reason=reason, url="https://x")])

        # The "<status> Client Error" prefix is what get_non_retryable_errors matches on.
        with pytest.raises(requests.HTTPError, match=f"{status} Client Error"):
            _batches(_source("lists"))


class TestCampaynSource:
    def test_all_endpoints_buildable_with_correct_primary_keys(self) -> None:
        for endpoint in ENDPOINTS:
            response = _source(endpoint)
            assert response.name == endpoint
            assert response.primary_keys == CAMPAYN_ENDPOINTS[endpoint].primary_keys
            # No stable creation-time field exists, so nothing is partitioned.
            assert response.partition_mode is None

    def test_fan_out_endpoints_key_includes_parent_list_id(self) -> None:
        assert _source("contacts").primary_keys == ["list_id", "id"]
        assert _source("forms").primary_keys == ["list_id", "id"]


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status, expected",
        [(200, True), (401, False), (403, False), (500, False)],
    )
    @mock.patch(CAMPAYN_SESSION_PATCH)
    def test_status_mapping(self, mock_session: mock.MagicMock, status: int, expected: bool) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status)
        assert validate_credentials("acme", "k") is expected

    @mock.patch(CAMPAYN_SESSION_PATCH)
    def test_connection_error_returns_false(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("acme", "k") is False

    @mock.patch(CAMPAYN_SESSION_PATCH)
    def test_probes_lists_endpoint_with_auth_header(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)
        validate_credentials("acme", "k")

        call = mock_session.return_value.get.call_args
        called_url = call.args[0] if call.args else call.kwargs["url"]
        assert called_url == f"{base_url('acme')}/lists.json"
        assert call.kwargs["headers"]["Authorization"] == "TRUEREST apikey=k"
