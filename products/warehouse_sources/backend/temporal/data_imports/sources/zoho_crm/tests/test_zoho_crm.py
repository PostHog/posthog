from collections.abc import Callable, Iterable, Sequence
from datetime import UTC, date, datetime
from typing import Any, Optional

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientNonRetryableError,
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    UnexpectedRequest,
    scripted_network,
    source_inputs,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.zohocrm import (
    ZohoCRMSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.zoho_crm.source import ZohoCRMSource
from products.warehouse_sources.backend.temporal.data_imports.sources.zoho_crm.zoho_crm import (
    CLIENT_REJECTED_MESSAGE,
    CLIENT_SECRET_REJECTED_MESSAGE,
    MAX_FIELDS_PER_REQUEST,
    MAX_PAGE,
    PAGE_SIZE,
    REFRESH_TOKEN_REJECTED_MESSAGE,
    ZohoCRMAuthError,
    ZohoCRMClient,
    ZohoCRMResumeConfig,
    chunk_fields,
    format_modified_since,
    readable_field_names,
    resolve_hosts,
    validate_credentials,
)

_TOKEN_PATH = "/oauth/v2/token"


def _response(status_code: int = 200, body: Optional[dict[str, Any]] = None) -> ScriptedResponse:
    return ScriptedResponse(status=status_code, json=body if body is not None else {})


def _undecodable_response(content: bytes) -> ScriptedResponse:
    """A 2xx whose body is not JSON."""
    return ScriptedResponse(body=content)


def _no_content_response(status_code: int) -> ScriptedResponse:
    """An empty-bodied Zoho response, as the real API sends for a read that matched nothing."""
    return ScriptedResponse(status=status_code, body=b"")


def _token_response(api_domain: str = "https://www.zohoapis.com") -> ScriptedResponse:
    return _response(200, {"access_token": "access-token", "api_domain": api_domain, "expires_in": 3600})


def _fields_response(count: int) -> ScriptedResponse:
    return _response(200, {"fields": [{"api_name": f"Field_{index}"} for index in range(count)]})


def _records_response(
    records: list[dict[str, Any]],
    more_records: bool = False,
    next_page_token: Optional[str] = None,
    data_key: str = "data",
) -> ScriptedResponse:
    info: dict[str, Any] = {"more_records": more_records, "per_page": PAGE_SIZE}
    if next_page_token is not None:
        info["next_page_token"] = next_page_token
    return _response(200, {data_key: records, "info": info})


def _script(
    data: Sequence[ScriptedResponse], tokens: Optional[Sequence[ScriptedResponse]] = None
) -> Callable[[RecordedRequest], ScriptedResponse]:
    """Answer the token exchange from `tokens` and every other request from `data`, each in order."""
    token_queue = list(tokens) if tokens is not None else [_token_response()]
    data_queue = list(data)

    def respond(request: RecordedRequest) -> ScriptedResponse:
        queue = token_queue if request.path == _TOKEN_PATH else data_queue
        if not queue:
            raise UnexpectedRequest(f"the script has no answer left for {request.method} {request.url}")
        return queue.pop(0)

    return respond


def _client() -> ZohoCRMClient:
    return ZohoCRMClient("us", "cid", "secret", "refresh")


def _run(
    endpoint: str,
    data: Sequence[ScriptedResponse],
    resume_state: Optional[ZohoCRMResumeConfig] = None,
    **inputs: Any,
) -> DriveResult:
    driver = SourceDriver(
        ZohoCRMSource(),
        ZohoCRMSourceConfig(client_id="cid", client_secret="secret", refresh_token="refresh", region="us"),
    )
    return driver.run(endpoint, _script(data), resume_state=resume_state, **inputs)


def _crm_requests(result: DriveResult) -> list[RecordedRequest]:
    return [request for request in result.requests if request.path.startswith("/crm/")]


class TestResolveHosts:
    def test_unknown_region_raises(self) -> None:
        with pytest.raises(ValueError):
            resolve_hosts("mars")


class TestFormatModifiedSince:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2024, 3, 1, 12, 30, 15, tzinfo=UTC), "2024-03-01T12:30:15+00:00"),
            (datetime(2024, 3, 1, 12, 30, 15), "2024-03-01T12:30:15+00:00"),
            (date(2024, 3, 1), "2024-03-01T00:00:00+00:00"),
            ("2024-03-01T00:00:00+00:00", "2024-03-01T00:00:00+00:00"),
        ],
    )
    def test_formats_cursor_values(self, value: Any, expected: str) -> None:
        assert format_modified_since(value) == expected


class TestChunkFields:
    @pytest.mark.parametrize(
        "count, expected_sizes",
        [
            (0, [0]),
            (1, [1]),
            (MAX_FIELDS_PER_REQUEST, [MAX_FIELDS_PER_REQUEST]),
            (MAX_FIELDS_PER_REQUEST + 1, [MAX_FIELDS_PER_REQUEST, 1]),
            (MAX_FIELDS_PER_REQUEST * 2 + 3, [MAX_FIELDS_PER_REQUEST, MAX_FIELDS_PER_REQUEST, 3]),
        ],
    )
    def test_slices_never_exceed_the_request_cap(self, count: int, expected_sizes: list[int]) -> None:
        slices = chunk_fields([f"Field_{index}" for index in range(count)])
        assert [len(chunk) for chunk in slices] == expected_sizes


class TestZohoCRMClient:
    def test_token_response_api_domain_overrides_regional_default(self) -> None:
        with scripted_network(_script([], tokens=[_token_response("https://www.zohoapis.eu/")])):
            client = _client()

            client.mint_access_token()

        assert client.api_domain == "https://www.zohoapis.eu"

    def test_error_body_on_a_200_raises_auth_error(self) -> None:
        with scripted_network(_script([], tokens=[_response(200, {"error": "invalid_code"})])):
            client = _client()

            with pytest.raises(ZohoCRMAuthError, match="invalid_code"):
                client.mint_access_token()

    def test_non_json_token_body_is_non_retryable(self) -> None:
        with scripted_network(_script([], tokens=[_undecodable_response(b"<html><body>Sign in</body></html>")])):
            client = _client()

            with pytest.raises(RESTClientNonRetryableError):
                client.mint_access_token()

    def test_remints_once_on_401_and_replays_the_request(self) -> None:
        with scripted_network(
            _script([_response(401), _response(200, {"data": []})], tokens=[_token_response(), _token_response()])
        ) as network:
            response = _client().get("/crm/v8/Leads")

        assert response.status_code == 200
        assert [request.path for request in network.requests_log].count(_TOKEN_PATH) == 2

    def test_session_disables_sample_capture_and_redacts_credentials(self) -> None:
        # Reverting capture=False would upload raw CRM records (contacts, notes, emails) and the
        # minted access token to the shared HTTP sample-capture prefix.
        with scripted_network(_script([])) as network:
            ZohoCRMClient("us", "cid", "secret-value", "refresh-value")

        assert network.session_options == [{"redact_values": ("secret-value", "refresh-value"), "capture": False}]


class TestReadableFieldNames:
    def test_skips_fields_the_api_never_returns(self) -> None:
        fields = _response(
            200,
            {
                "fields": [
                    {"api_name": "Last_Name", "view_type": {"view": True}},
                    {"api_name": "Hidden", "view_type": {"view": False}},
                    {"api_name": "No_View_Type"},
                    {"data_type": "text"},
                ]
            },
        )
        with scripted_network(_script([fields])):
            names = readable_field_names(_client(), "v8", "Leads")

        assert names == ["Last_Name", "No_View_Type"]

    @pytest.mark.parametrize("status_code", [204, 304])
    def test_no_content_metadata_yields_no_projection(self, status_code: int) -> None:
        with scripted_network(_script([_no_content_response(status_code)])):
            assert readable_field_names(_client(), "v8", "Leads") == []

    def test_empty_metadata_body_yields_no_projection(self) -> None:
        with scripted_network(_script([_undecodable_response(b"")])):
            assert readable_field_names(_client(), "v8", "Leads") == []


class TestGetRows:
    def test_incremental_sync_filters_and_sorts_on_the_cursor_field(self) -> None:
        result = _run(
            "Contacts",
            [_fields_response(1), _records_response([{"id": "1"}])],
            incremental_field="Modified_Time",
            db_incremental_field_last_value=datetime(2024, 6, 1, tzinfo=UTC),
        )

        records_request = _crm_requests(result)[1]
        assert records_request.headers["if-modified-since"] == "2024-06-01T00:00:00+00:00"
        assert records_request.param("sort_by") == "Modified_Time"

    @pytest.mark.parametrize("status_code", [204, 304])
    def test_no_content_module_response_yields_nothing(self, status_code: int) -> None:
        result = _run("Leads", [_fields_response(1), _no_content_response(status_code)])

        assert result.raised is None
        assert result.items == []

    def test_stops_at_the_page_window_when_no_token_is_offered(self) -> None:
        pages = [_records_response([{"id": str(page)}], more_records=True) for page in range(MAX_PAGE + 2)]
        logger = mock.MagicMock()

        result = _run("Leads", [_fields_response(1), *pages], logger=logger)

        assert len(result.items) == MAX_PAGE
        logger.warning.assert_called_once()

    def test_resumes_from_the_saved_page_token(self) -> None:
        result = _run(
            "Leads",
            [_fields_response(1), _records_response([{"id": "9"}])],
            resume_state=ZohoCRMResumeConfig(page=12, page_tokens=["tok-11"]),
        )

        assert result.items == [[{"id": "9"}]]
        assert _crm_requests(result)[1].param("page_token") == "tok-11"

    def test_restarts_when_saved_tokens_no_longer_match_the_field_slices(self) -> None:
        # Two slices now, but the checkpoint only carries one token — the tokens are unusable.
        result = _run(
            "Leads",
            [
                _fields_response(MAX_FIELDS_PER_REQUEST + 1),
                _records_response([{"id": "1"}]),
                _records_response([{"id": "1"}]),
            ],
            resume_state=ZohoCRMResumeConfig(page=25, page_tokens=["stale"]),
        )

        assert _crm_requests(result)[1].param("page") == "1"
        assert _crm_requests(result)[1].param("page_token") is None

    def test_users_endpoint_skips_field_metadata_and_reads_its_own_envelope(self) -> None:
        result = _run("Users", [_records_response([{"id": "u1"}], data_key="users")])

        requests_made = _crm_requests(result)
        assert result.items == [[{"id": "u1"}]]
        assert len(requests_made) == 1
        assert requests_made[0].url.startswith("https://www.zohoapis.com/crm/v8/users")
        assert requests_made[0].param("type") == "AllUsers"
        assert requests_made[0].param("sort_by") is None
        assert requests_made[0].param("fields") is None

    def test_empty_records_body_stops_pagination_without_crashing(self) -> None:
        result = _run(
            "Leads",
            [_fields_response(1), _undecodable_response(b"")],
            resume_state=ZohoCRMResumeConfig(page=1, page_tokens=[]),
        )

        assert result.raised is None
        assert result.items == []
        assert result.final_state is None

    def test_non_json_records_body_is_non_retryable(self) -> None:
        result = _run(
            "Leads",
            [_fields_response(1), _undecodable_response(b"<!DOCTYPE html><html><body>Sign in</body></html>")],
        )

        # The request URL carries a query string, which holds the page token and the field list.
        assert isinstance(result.raised, RESTClientNonRetryableError)
        assert str(result.raised) == "Non-JSON response from https://www.zohoapis.com/crm/v8/Leads"

    def test_truncated_records_body_stays_retryable(self) -> None:
        result = _run("Leads", [_fields_response(1), _undecodable_response(b'{"data": [{"id": "1"}')])

        assert isinstance(result.raised, RESTClientRetryableError)


class TestValidateCredentials:
    def test_valid_when_the_modules_probe_succeeds(self) -> None:
        with scripted_network(_script([_response(200, {"modules": []})])):
            assert validate_credentials("us", "cid", "secret", "refresh") == (True, None)

    def test_unknown_region_is_rejected_without_a_request(self) -> None:
        is_valid, error = validate_credentials("mars", "cid", "secret", "refresh")

        assert is_valid is False
        assert error is not None and "mars" in error

    @pytest.mark.parametrize(
        ("error_code", "expected"),
        [
            ("invalid_code", REFRESH_TOKEN_REJECTED_MESSAGE),
            ("invalid_client", CLIENT_REJECTED_MESSAGE),
            ("invalid_client_secret", CLIENT_SECRET_REJECTED_MESSAGE),
        ],
    )
    def test_token_rejection_gives_actionable_copy(self, error_code: str, expected: str) -> None:
        with scripted_network(_script([], tokens=[_response(200, {"error": error_code})])):
            is_valid, error = validate_credentials("us", "cid", "secret", "refresh")

        assert is_valid is False
        assert error == expected
        assert error_code not in (error or "")

    def test_http_failure_is_not_valid(self) -> None:
        with scripted_network(_script([_response(403)])):
            assert validate_credentials("us", "cid", "secret", "refresh") == (False, None)


class TestZohoCRMSourceResponse:
    def test_items_are_lazy_until_iterated(self) -> None:
        source = ZohoCRMSource()
        config = ZohoCRMSourceConfig(client_id="cid", client_secret="secret", refresh_token="refresh", region="us")
        inputs = source_inputs("Leads")

        with scripted_network(_script([_fields_response(1), _records_response([{"id": "1"}])])) as network:
            response = source.source_for_pipeline(config, source.get_resumable_source_manager(inputs), inputs)

            assert network.requests_log == []
            items = response.items()
            assert isinstance(items, Iterable)
            assert list(items) == [[{"id": "1"}]]
