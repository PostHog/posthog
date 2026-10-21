import urllib.parse
from collections.abc import Callable, Iterable, Sequence
from datetime import UTC, datetime
from typing import Any, Optional, cast

import pytest
import time_machine
from unittest import mock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    UnexpectedRequest,
    always,
    scripted_network,
    source_inputs,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.powerbiadmin import (
    PowerBiAdminSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.power_bi_admin.power_bi_admin import (
    ADMIN_API_DENIED_ERROR,
    PowerBiAdminClient,
    PowerBiAdminResumeConfig,
    _coerce_date,
    _parse_creation_time,
    power_bi_admin_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.power_bi_admin.settings import (
    ACTIVITY_EVENTS_ENDPOINT,
    ODATA_PAGE_SIZE,
    POWER_BI_ADMIN_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.power_bi_admin.source import PowerBiAdminSource

TENANT_ID = "11111111-1111-1111-1111-111111111111"
CLIENT_ID = "22222222-2222-2222-2222-222222222222"
CLIENT_SECRET = "super-secret"

TOKEN_PATH = f"/{TENANT_ID}/oauth2/v2.0/token"


def _body(status: int = 200, json_body: Any = None, text: str = "") -> ScriptedResponse:
    if text:
        return ScriptedResponse(status=status, body=text.encode())
    return ScriptedResponse(status=status, json=json_body if json_body is not None else {})


def _token_response(token: str = "token-1") -> ScriptedResponse:
    return _body(200, {"access_token": token, "expires_in": 3599})


def _script(
    gets: Sequence[ScriptedResponse] | ScriptedResponse | Callable[[RecordedRequest], ScriptedResponse],
    tokens: Optional[Sequence[ScriptedResponse]] = None,
) -> Callable[[RecordedRequest], ScriptedResponse]:
    """Answer the token exchange and the admin API from separate queues.

    A single response in `gets` answers every call, because the real stack retries a 5xx.
    """
    token_queue = list(tokens) if tokens is not None else [_token_response()]
    get_queue = list(gets) if isinstance(gets, Sequence) else None

    def respond(request: RecordedRequest) -> ScriptedResponse:
        if request.path == TOKEN_PATH:
            if not token_queue:
                raise UnexpectedRequest(f"no token answer left for {request.url}")
            return token_queue.pop(0)
        if isinstance(gets, ScriptedResponse):
            return gets
        if not isinstance(gets, Sequence):
            return gets(request)
        assert get_queue is not None
        if not get_queue:
            raise UnexpectedRequest(f"no answer left for {request.method} {request.url}")
        return get_queue.pop(0)

    return respond


def _driver() -> SourceDriver:
    return SourceDriver(
        PowerBiAdminSource(),
        PowerBiAdminSourceConfig(tenant_id=TENANT_ID, client_id=CLIENT_ID, client_secret=CLIENT_SECRET),
    )


def _run(
    endpoint: str,
    gets: Sequence[ScriptedResponse] | ScriptedResponse | Callable[[RecordedRequest], ScriptedResponse],
    *,
    tokens: Optional[Sequence[ScriptedResponse]] = None,
    resume_state: Optional[PowerBiAdminResumeConfig] = None,
    **inputs: Any,
) -> DriveResult:
    return _driver().run(endpoint, _script(gets, tokens), resume_state=resume_state, **inputs)


def _api_requests(requests_log: Sequence[RecordedRequest]) -> list[RecordedRequest]:
    return [request for request in requests_log if request.method == "GET"]


def _activity_params(result: DriveResult) -> list[dict[str, str]]:
    return [{name: values[0] for name, values in request.query.items()} for request in _api_requests(result.requests)]


def _skips(result: DriveResult) -> list[str | None]:
    return [request.param("$skip") for request in _api_requests(result.requests)]


def _event(event_id: str, creation_time: str = "2026-07-20T10:00:00Z") -> dict[str, Any]:
    return {"Id": event_id, "Operation": "ViewReport", "CreationTime": creation_time}


def _activity_page(events: list[dict[str, Any]], continuation_token: Optional[str] = None) -> ScriptedResponse:
    body: dict[str, Any] = {"activityEventEntities": events}
    if continuation_token is not None:
        body["continuationToken"] = continuation_token
    return _body(200, body)


def _empty_days(count: int) -> list[ScriptedResponse]:
    return [_activity_page([]) for _ in range(count)]


def _source_response(endpoint: str) -> SourceResponse:
    manager = PowerBiAdminSource().get_resumable_source_manager(source_inputs(endpoint))
    return power_bi_admin_source(
        tenant_id=TENANT_ID,
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        endpoint=endpoint,
        logger=mock.MagicMock(),
        resumable_source_manager=manager,
    )


class TestHelpers:
    @parameterized.expand(
        [
            ("none", None, None),
            ("empty", "  ", None),
            ("garbage", "not-a-date", None),
            ("iso_datetime_z", "2026-07-20T10:00:00Z", "2026-07-20"),
            ("iso_datetime_naive", "2026-07-20T10:00:00", "2026-07-20"),
            ("iso_date", "2026-07-20", "2026-07-20"),
        ]
    )
    def test_coerce_date(self, _name: str, value: Any, expected: Optional[str]) -> None:
        result = _coerce_date(value)
        assert (result.isoformat() if result else None) == expected

    def test_coerce_date_from_aware_datetime_uses_utc_day(self) -> None:
        # 00:30 on the 21st in UTC+2 is still the 20th in UTC, which is the day the API windows on.
        value = datetime.fromisoformat("2026-07-21T00:30:00+02:00")
        result = _coerce_date(value)
        assert result is not None and result.isoformat() == "2026-07-20"

    @parameterized.expand(
        [
            ("none", None, None),
            ("empty", "", None),
            ("garbage", "nope", None),
            ("with_z", "2026-07-20T10:00:00Z", "2026-07-20T10:00:00+00:00"),
            ("naive_gets_utc", "2026-07-20T10:00:00", "2026-07-20T10:00:00+00:00"),
        ]
    )
    def test_parse_creation_time(self, _name: str, value: Any, expected: Optional[str]) -> None:
        result = _parse_creation_time(value)
        assert (result.isoformat() if result else None) == expected


class TestPowerBiAdminClient:
    def test_mint_token_posts_client_credentials(self) -> None:
        with scripted_network([_token_response("abc")]) as network:
            client = PowerBiAdminClient(TENANT_ID, CLIENT_ID, CLIENT_SECRET, mock.MagicMock())
            assert client.mint_token() == "abc"

        assert client.token_url == f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token"
        request = network.requests_log[0]
        assert request.url == client.token_url
        body = urllib.parse.parse_qs((request.body or b"").decode())
        assert body["grant_type"] == ["client_credentials"]
        assert body["scope"] == ["https://analysis.windows.net/powerbi/api/.default"]
        assert body["client_secret"] == [CLIENT_SECRET]

    def test_mint_token_raises_when_no_token_returned(self) -> None:
        with scripted_network([_body(200, {"token_type": "Bearer"})]):
            client = PowerBiAdminClient(TENANT_ID, CLIENT_ID, CLIENT_SECRET, mock.MagicMock())
            try:
                client.mint_token()
            except ValueError as e:
                assert "access token" in str(e)
            else:
                raise AssertionError("expected a ValueError when Entra ID returns no access token")

    def test_secret_is_redacted_in_the_tracked_session(self) -> None:
        with scripted_network([]) as network:
            PowerBiAdminClient(TENANT_ID, CLIENT_ID, CLIENT_SECRET, mock.MagicMock())

        assert network.session_options[0]["redact_values"] == (CLIENT_SECRET,)

    def test_expired_token_is_reminted_once_then_the_call_succeeds(self) -> None:
        script = _script(
            [_body(401, text="expired"), _body(200, {"value": [{"id": "g1"}]})],
            [_token_response("first"), _token_response("second")],
        )
        with scripted_network(script) as network:
            client = PowerBiAdminClient(TENANT_ID, CLIENT_ID, CLIENT_SECRET, mock.MagicMock())
            body = client.get("/groups")

        assert body == {"value": [{"id": "g1"}]}
        assert [request.method for request in network.requests_log].count("POST") == 2
        gets = _api_requests(network.requests_log)
        assert gets[0].headers["authorization"] == "Bearer first"
        assert gets[1].headers["authorization"] == "Bearer second"

    def test_persistent_401_is_raised_after_the_remint(self) -> None:
        script = _script(
            [_body(401, text="denied"), _body(401, text="denied")],
            [_token_response("first"), _token_response("second")],
        )
        with scripted_network(script) as network:
            client = PowerBiAdminClient(TENANT_ID, CLIENT_ID, CLIENT_SECRET, mock.MagicMock())
            try:
                client.get("/groups")
            except requests.HTTPError:
                pass
            else:
                raise AssertionError("expected the second 401 to raise")

        assert len(_api_requests(network.requests_log)) == 2


class TestActivityEvents:
    @pytest.fixture(autouse=True)
    def _frozen_clock(self):
        with time_machine.travel("2026-07-26T12:00:00Z", tick=False):
            yield

    def test_full_refresh_walks_the_whole_retention_window_one_day_per_request(self) -> None:
        result = _run(ACTIVITY_EVENTS_ENDPOINT, _empty_days(28))

        assert result.items == []
        params = _activity_params(result)
        assert len(params) == 28
        assert params[0]["startDateTime"] == "'2026-06-29T00:00:00'"
        assert params[0]["endDateTime"] == "'2026-06-29T23:59:59'"
        assert params[-1]["startDateTime"] == "'2026-07-26T00:00:00'"

    def test_incremental_restarts_at_the_watermark_day(self) -> None:
        result = _run(
            ACTIVITY_EVENTS_ENDPOINT,
            [_activity_page([_event("e1")]) for _ in range(3)],
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-07-24T18:00:00Z",
        )

        assert len(result.items) == 3
        assert [p["startDateTime"] for p in _activity_params(result)] == [
            "'2026-07-24T00:00:00'",
            "'2026-07-25T00:00:00'",
            "'2026-07-26T00:00:00'",
        ]

    def test_incremental_watermark_older_than_retention_is_clamped(self) -> None:
        result = _run(
            ACTIVITY_EVENTS_ENDPOINT,
            _empty_days(28),
            should_use_incremental_field=True,
            db_incremental_field_last_value="2024-01-01T00:00:00Z",
        )

        assert _activity_params(result)[0]["startDateTime"] == "'2026-06-29T00:00:00'"

    def test_creation_time_is_typed_as_a_datetime(self) -> None:
        result = _run(
            ACTIVITY_EVENTS_ENDPOINT,
            [_activity_page([_event("e1", "2026-07-26T09:15:00Z")]), *_empty_days(27)],
        )

        assert result.items[0][0]["CreationTime"] == datetime(2026, 7, 26, 9, 15, tzinfo=UTC)

    def test_continuation_token_loop_ends_on_a_missing_token_not_on_empty_rows(self) -> None:
        result = _run(
            ACTIVITY_EVENTS_ENDPOINT,
            [
                _activity_page([_event("e1")], "t1"),
                # Empty page that still carries a token: the loop must keep going.
                _activity_page([], "t2"),
                _activity_page([_event("e2")]),
                *_empty_days(27),
            ],
        )

        assert [row["Id"] for batch in result.items for row in batch] == ["e1", "e2"]
        params = _activity_params(result)
        assert params[1] == {"continuationToken": "'t1'"}
        assert params[2] == {"continuationToken": "'t2'"}
        # After the day drained, the next request windows the following day again.
        assert "startDateTime" in params[3]

    def test_repeated_continuation_token_stops_the_day_instead_of_looping(self) -> None:
        result = _run(
            ACTIVITY_EVENTS_ENDPOINT,
            [_activity_page([_event("e1")], "same") for _ in range(2)] + _empty_days(27),
        )

        assert len(result.items) == 2
        # 2 pages of the first day + one windowed request for each of the 27 remaining days.
        assert len(_api_requests(result.requests)) == 29

    def test_state_is_saved_after_each_page_and_after_each_day(self) -> None:
        result = _run(
            ACTIVITY_EVENTS_ENDPOINT,
            [_activity_page([_event("e1")], "t1"), _activity_page([_event("e2")]), *_empty_days(27)],
        )

        saved = result.saved_states
        assert saved[0] == PowerBiAdminResumeConfig(next_day="2026-06-29", continuation_token="t1")
        assert saved[1] == PowerBiAdminResumeConfig(next_day="2026-06-30")
        assert saved[-1] == PowerBiAdminResumeConfig(next_day="2026-07-27")

    def test_resume_starts_from_the_saved_day_and_continuation_token(self) -> None:
        result = _run(
            ACTIVITY_EVENTS_ENDPOINT,
            [_activity_page([_event("e1")]) for _ in range(2)],
            resume_state=PowerBiAdminResumeConfig(next_day="2026-07-25", continuation_token="saved-token"),
        )

        assert len(result.items) == 2
        params = _activity_params(result)
        assert params[0] == {"continuationToken": "'saved-token'"}
        assert params[1]["startDateTime"] == "'2026-07-26T00:00:00'"

    def test_resume_takes_precedence_over_the_incremental_watermark(self) -> None:
        result = _run(
            ACTIVITY_EVENTS_ENDPOINT,
            _empty_days(1),
            resume_state=PowerBiAdminResumeConfig(next_day="2026-07-26"),
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-07-01T00:00:00Z",
        )

        assert _activity_params(result)[0]["startDateTime"] == "'2026-07-26T00:00:00'"

    def test_stale_resume_day_drops_its_continuation_token(self) -> None:
        # A token issued before the retention window rolled over is no longer valid, so the
        # clamped day must be re-windowed rather than resumed from the token.
        result = _run(
            ACTIVITY_EVENTS_ENDPOINT,
            _empty_days(28),
            resume_state=PowerBiAdminResumeConfig(next_day="2024-01-01", continuation_token="stale"),
        )

        assert _activity_params(result)[0]["startDateTime"] == "'2026-06-29T00:00:00'"


class TestInventoryEndpoints:
    @parameterized.expand([("groups",), ("datasets",), ("reports",), ("dashboards",), ("dataflows",)])
    def test_short_page_terminates_the_odata_walk(self, endpoint: str) -> None:
        result = _run(endpoint, [_body(200, {"value": [{"id": "a"}, {"id": "b"}]})])

        assert result.items == [[{"id": "a"}, {"id": "b"}]]
        assert len(_api_requests(result.requests)) == 1
        assert _activity_params(result) == [{"$top": str(ODATA_PAGE_SIZE), "$skip": "0"}]

    def test_full_page_advances_skip_until_a_short_page(self) -> None:
        full_page = [{"id": str(i)} for i in range(ODATA_PAGE_SIZE)]

        result = _run("groups", [_body(200, {"value": full_page}), _body(200, {"value": [{"id": "last"}]})])

        assert len(result.items) == 2
        assert _skips(result) == ["0", str(ODATA_PAGE_SIZE)]
        assert result.saved_states[0] == PowerBiAdminResumeConfig(skip=ODATA_PAGE_SIZE)

    def test_resume_starts_from_the_saved_skip(self) -> None:
        result = _run(
            "groups",
            [_body(200, {"value": [{"id": "a"}]})],
            resume_state=PowerBiAdminResumeConfig(skip=10000),
        )

        assert _skips(result)[0] == "10000"

    def test_a_run_with_no_saved_state_starts_from_the_first_page(self) -> None:
        result = _run("groups", [_body(200, {"value": [{"id": "a"}]})])

        assert _skips(result)[0] == "0"

    def test_capacities_is_a_single_unpaged_request(self) -> None:
        result = _run("capacities", [_body(200, {"value": [{"id": "c1"}]})])

        assert result.items == [[{"id": "c1"}]]
        assert _api_requests(result.requests)[0].query == {}

    def test_empty_response_yields_nothing(self) -> None:
        assert _run("groups", [_body(200, {"value": []})]).items == []


class TestSourceResponse:
    @parameterized.expand([(name,) for name in POWER_BI_ADMIN_ENDPOINTS])
    def test_response_carries_the_endpoint_primary_keys(self, endpoint: str) -> None:
        with scripted_network([]):
            response = _source_response(endpoint)

        assert response.name == endpoint
        assert response.primary_keys == POWER_BI_ADMIN_ENDPOINTS[endpoint].primary_keys
        assert response.sort_mode == "asc"

    def test_activity_events_partition_on_creation_time(self) -> None:
        with scripted_network([]):
            response = _source_response(ACTIVITY_EVENTS_ENDPOINT)

        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["CreationTime"]

    def test_inventory_endpoints_have_no_datetime_partitioning(self) -> None:
        with scripted_network([]):
            response = _source_response("groups")

        assert response.partition_mode is None
        assert response.partition_keys is None

    def test_items_is_lazy_and_iterates_the_endpoint(self) -> None:
        with scripted_network(_script([_body(200, {"value": [{"id": "g1"}]})])) as network:
            response = _source_response("groups")

            assert network.requests_log == []
            batches = list(cast("Iterable[Any]", response.items()))

        assert batches == [[{"id": "g1"}]]


class TestValidateCredentials:
    def test_valid_credentials_probe_the_admin_groups_endpoint(self) -> None:
        with scripted_network(_script([_body(200, {"value": [{"id": "g1"}]})])) as network:
            is_valid, message = validate_credentials(TENANT_ID, CLIENT_ID, CLIENT_SECRET)

        assert (is_valid, message) == (True, None)
        assert _api_requests(network.requests_log)[0].query == {"$top": ("1",)}

    def test_blank_tenant_id_fails_without_a_request(self) -> None:
        with scripted_network([]) as network:
            is_valid, message = validate_credentials("   ", CLIENT_ID, CLIENT_SECRET)

        assert is_valid is False
        assert message is not None and "tenant" in message.lower()
        assert network.requests_log == []

    @parameterized.expand([(400,)])
    def test_rejected_token_reports_bad_service_principal(self, status: int) -> None:
        with scripted_network(_script([], [_body(status, text="invalid_client")])):
            is_valid, message = validate_credentials(TENANT_ID, CLIENT_ID, CLIENT_SECRET)

        assert is_valid is False
        assert message is not None and "client secret" in message

    @parameterized.expand([(401,), (403,)])
    def test_denied_admin_api_reports_the_tenant_grant(self, status: int) -> None:
        # A 401 gets one re-mint before it is treated as a denial, so both attempts fail here.
        script = _script(
            [_body(status, text="denied"), _body(status, text="denied")],
            [_token_response("a"), _token_response("b")],
        )
        with scripted_network(script):
            is_valid, message = validate_credentials(TENANT_ID, CLIENT_ID, CLIENT_SECRET)

        assert (is_valid, message) == (False, ADMIN_API_DENIED_ERROR)

    def test_unexpected_admin_api_status_is_reported_with_the_status(self) -> None:
        with scripted_network(_script(_body(500, text="boom"))):
            is_valid, message = validate_credentials(TENANT_ID, CLIENT_ID, CLIENT_SECRET)

        assert is_valid is False
        assert message is not None and "500" in message

    def test_network_failure_asks_for_a_retry(self) -> None:
        with scripted_network(always(ConnectionError("no route to host"))):
            is_valid, message = validate_credentials(TENANT_ID, CLIENT_ID, CLIENT_SECRET)

        assert is_valid is False
        assert message is not None and "retry" in message.lower()
