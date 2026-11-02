from typing import Any

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    Script,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.tyntecsms import (
    TyntecSMSSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.tyntec_sms.settings import (
    MAX_REQUEST_IDS,
    MESSAGE_STATUS,
    PHONE_NUMBERS,
    PHONEBOOK_MAX_SIZE,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.tyntec_sms.source import TyntecSMSSource
from products.warehouse_sources.backend.temporal.data_imports.sources.tyntec_sms.tyntec_sms import (
    parse_request_ids,
    validate_credentials,
)


def _make_http_response(body: dict[str, Any], status_code: int = 200) -> ScriptedResponse:
    return ScriptedResponse(status=status_code, json=body)


def _drive(endpoint: str, script: Script, request_ids: str | None = None) -> DriveResult:
    config = TyntecSMSSourceConfig(api_key="test-key", request_ids=request_ids)
    return SourceDriver(TyntecSMSSource(), config).run(endpoint, script)


class TestParseRequestIds:
    def test_caps_list_to_bound_worker_time(self) -> None:
        # Each id is one serial HTTP request per sync; an unbounded list would let a single
        # source occupy an import worker indefinitely.
        raw = ",".join(f"id-{i}" for i in range(MAX_REQUEST_IDS + 5))

        parsed = parse_request_ids(raw)

        assert len(parsed) == MAX_REQUEST_IDS
        assert parsed[0] == "id-0"
        assert parsed[-1] == f"id-{MAX_REQUEST_IDS - 1}"


class TestMessageStatus:
    def test_request_id_is_url_quoted(self) -> None:
        result = _drive(MESSAGE_STATUS, [_make_http_response({"requestId": "a/b"})], request_ids="a/b")

        assert result.urls[0] == "https://api.tyntec.com/messaging/v1/messages/a%2Fb"

    def test_expired_request_id_404_is_skipped(self) -> None:
        # tyntec drops statuses ~3 months after delivery; an expired id must not fail the sync.
        result = _drive(
            MESSAGE_STATUS,
            [
                _make_http_response({"title": "Not Found"}, status_code=404),
                _make_http_response({"requestId": "id-2", "status": "DELIVERED"}),
            ],
            request_ids="id-1, id-2",
        )

        assert [row["requestId"] for row in result.rows] == ["id-2"]
        assert len(result.requests) == 2

    def test_auth_error_is_not_swallowed_by_404_skip(self) -> None:
        result = _drive(
            MESSAGE_STATUS,
            [_make_http_response({"message": "No API key found in request"}, status_code=401)],
            request_ids="id-1",
        )

        assert result.raised is not None
        assert "401 Client Error" in str(result.raised)

    def test_no_request_ids_yields_nothing_without_requests(self) -> None:
        result = _drive(MESSAGE_STATUS, [], request_ids=None)

        assert result.rows == []
        assert result.requests == []

    def test_redirects_are_not_followed(self) -> None:
        redirect = ScriptedResponse(status=302, headers={"Location": "https://attacker.example/steal"})

        result = _drive(MESSAGE_STATUS, always(redirect), request_ids="id-1")

        assert {request.origin for request in result.requests} == {"https://api.tyntec.com"}


class TestListEndpoints:
    def test_phone_numbers_requests_full_documented_cap(self) -> None:
        result = _drive(PHONE_NUMBERS, [_make_http_response({"provisioningRequests": [], "size": 0})])

        assert dict(result.requests[0].query) == {"size": (str(PHONEBOOK_MAX_SIZE),)}


class TestValidateCredentials:
    @pytest.mark.parametrize(
        ("status_code", "expected"),
        [
            # Unknown probe id with a valid key answers 404.
            (404, True),
        ],
    )
    def test_status_mapping(self, status_code: int, expected: bool) -> None:
        with scripted_network([_make_http_response({}, status_code=status_code)]) as network:
            assert validate_credentials("test-key") is expected

        assert network.requests_log[0].headers["apikey"] == "test-key"

    def test_probe_does_not_follow_redirects(self) -> None:
        redirect = ScriptedResponse(status=302, headers={"Location": "https://attacker.example/steal"})

        with scripted_network(always(redirect)) as network:
            validate_credentials("test-key")

        assert {request.origin for request in network.requests_log} == {"https://api.tyntec.com"}
