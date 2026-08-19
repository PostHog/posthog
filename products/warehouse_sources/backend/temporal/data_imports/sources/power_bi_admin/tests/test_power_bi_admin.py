from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any, Optional, cast

from freezegun import freeze_time
from unittest import mock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.power_bi_admin.power_bi_admin import (
    ADMIN_API_DENIED_ERROR,
    PowerBiAdminClient,
    PowerBiAdminResumeConfig,
    _coerce_date,
    _get_rows,
    _parse_creation_time,
    power_bi_admin_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.power_bi_admin.settings import (
    ACTIVITY_EVENTS_ENDPOINT,
    ODATA_PAGE_SIZE,
    POWER_BI_ADMIN_ENDPOINTS,
)

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.power_bi_admin.power_bi_admin"

TENANT_ID = "11111111-1111-1111-1111-111111111111"
CLIENT_ID = "22222222-2222-2222-2222-222222222222"
CLIENT_SECRET = "super-secret"


def _response(status: int = 200, json_body: Any = None, text: str = "") -> mock.MagicMock:
    response = mock.MagicMock(spec=requests.Response)
    response.status_code = status
    response.ok = 200 <= status < 300
    response.text = text
    response.json.return_value = json_body if json_body is not None else {}
    if not response.ok:
        error = requests.HTTPError(f"{status} Client Error", response=response)
        response.raise_for_status.side_effect = error
    else:
        response.raise_for_status.return_value = None
    return response


def _token_response(token: str = "token-1") -> mock.MagicMock:
    return _response(200, {"access_token": token, "expires_in": 3599})


def _session(get_responses: list[mock.MagicMock], post_responses: Optional[list[mock.MagicMock]] = None) -> Any:
    session = mock.MagicMock(spec=requests.Session)
    session.get.side_effect = get_responses
    session.post.side_effect = post_responses if post_responses is not None else [_token_response()]
    return session


def _manager(resume_state: Optional[PowerBiAdminResumeConfig] = None) -> Any:
    manager = mock.MagicMock(spec=ResumableSourceManager)
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _run(
    endpoint: str,
    session: Any,
    manager: Optional[Any] = None,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> list[list[dict[str, Any]]]:
    with mock.patch(f"{MODULE}.make_tracked_session", return_value=session):
        return list(
            _get_rows(
                tenant_id=TENANT_ID,
                client_id=CLIENT_ID,
                client_secret=CLIENT_SECRET,
                endpoint=endpoint,
                logger=mock.MagicMock(),
                resumable_source_manager=manager if manager is not None else _manager(),
                should_use_incremental_field=should_use_incremental_field,
                db_incremental_field_last_value=db_incremental_field_last_value,
            )
        )


def _activity_params(session: Any) -> list[dict[str, str]]:
    return [call.kwargs["params"] for call in session.get.call_args_list]


def _event(event_id: str, creation_time: str = "2026-07-20T10:00:00Z") -> dict[str, Any]:
    return {"Id": event_id, "Operation": "ViewReport", "CreationTime": creation_time}


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
        session = _session([], [_token_response("abc")])
        with mock.patch(f"{MODULE}.make_tracked_session", return_value=session):
            client = PowerBiAdminClient(TENANT_ID, CLIENT_ID, CLIENT_SECRET, mock.MagicMock())
            assert client.mint_token() == "abc"

        assert client.token_url == f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token"
        body = session.post.call_args.kwargs["data"]
        assert body["grant_type"] == "client_credentials"
        assert body["scope"] == "https://analysis.windows.net/powerbi/api/.default"
        assert body["client_secret"] == CLIENT_SECRET

    def test_mint_token_raises_when_no_token_returned(self) -> None:
        session = _session([], [_response(200, {"token_type": "Bearer"})])
        with mock.patch(f"{MODULE}.make_tracked_session", return_value=session):
            client = PowerBiAdminClient(TENANT_ID, CLIENT_ID, CLIENT_SECRET, mock.MagicMock())
            try:
                client.mint_token()
            except ValueError as e:
                assert "access token" in str(e)
            else:
                raise AssertionError("expected a ValueError when Entra ID returns no access token")

    def test_secret_is_redacted_in_the_tracked_session(self) -> None:
        with mock.patch(f"{MODULE}.make_tracked_session") as make_session:
            PowerBiAdminClient(TENANT_ID, CLIENT_ID, CLIENT_SECRET, mock.MagicMock())

        assert make_session.call_args.kwargs["redact_values"] == (CLIENT_SECRET,)

    def test_expired_token_is_reminted_once_then_the_call_succeeds(self) -> None:
        session = _session(
            [_response(401, text="expired"), _response(200, {"value": [{"id": "g1"}]})],
            [_token_response("first"), _token_response("second")],
        )
        with mock.patch(f"{MODULE}.make_tracked_session", return_value=session):
            client = PowerBiAdminClient(TENANT_ID, CLIENT_ID, CLIENT_SECRET, mock.MagicMock())
            body = client.get("/groups")

        assert body == {"value": [{"id": "g1"}]}
        assert session.post.call_count == 2
        assert session.get.call_args_list[0].kwargs["headers"]["Authorization"] == "Bearer first"
        assert session.get.call_args_list[1].kwargs["headers"]["Authorization"] == "Bearer second"

    def test_persistent_401_is_raised_after_the_remint(self) -> None:
        session = _session(
            [_response(401, text="denied"), _response(401, text="denied")],
            [_token_response("first"), _token_response("second")],
        )
        with mock.patch(f"{MODULE}.make_tracked_session", return_value=session):
            client = PowerBiAdminClient(TENANT_ID, CLIENT_ID, CLIENT_SECRET, mock.MagicMock())
            try:
                client.get("/groups")
            except requests.HTTPError:
                pass
            else:
                raise AssertionError("expected the second 401 to raise")

        assert session.get.call_count == 2


@freeze_time("2026-07-26T12:00:00Z")
class TestActivityEvents:
    def test_full_refresh_walks_the_whole_retention_window_one_day_per_request(self) -> None:
        session = _session([_response(200, {"activityEventEntities": []}) for _ in range(28)])

        batches = _run(ACTIVITY_EVENTS_ENDPOINT, session)

        assert batches == []
        params = _activity_params(session)
        assert len(params) == 28
        assert params[0]["startDateTime"] == "'2026-06-29T00:00:00'"
        assert params[0]["endDateTime"] == "'2026-06-29T23:59:59'"
        assert params[-1]["startDateTime"] == "'2026-07-26T00:00:00'"

    def test_incremental_restarts_at_the_watermark_day(self) -> None:
        session = _session([_response(200, {"activityEventEntities": [_event("e1")]}) for _ in range(3)])

        batches = _run(
            ACTIVITY_EVENTS_ENDPOINT,
            session,
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-07-24T18:00:00Z",
        )

        assert len(batches) == 3
        assert [p["startDateTime"] for p in _activity_params(session)] == [
            "'2026-07-24T00:00:00'",
            "'2026-07-25T00:00:00'",
            "'2026-07-26T00:00:00'",
        ]

    def test_incremental_watermark_older_than_retention_is_clamped(self) -> None:
        session = _session([_response(200, {"activityEventEntities": []}) for _ in range(28)])

        _run(
            ACTIVITY_EVENTS_ENDPOINT,
            session,
            should_use_incremental_field=True,
            db_incremental_field_last_value="2024-01-01T00:00:00Z",
        )

        assert _activity_params(session)[0]["startDateTime"] == "'2026-06-29T00:00:00'"

    def test_creation_time_is_typed_as_a_datetime(self) -> None:
        session = _session(
            [_response(200, {"activityEventEntities": [_event("e1", "2026-07-26T09:15:00Z")]})]
            + [_response(200, {"activityEventEntities": []}) for _ in range(27)]
        )

        batches = _run(ACTIVITY_EVENTS_ENDPOINT, session)

        assert batches[0][0]["CreationTime"] == datetime(2026, 7, 26, 9, 15, tzinfo=UTC)

    def test_continuation_token_loop_ends_on_a_missing_token_not_on_empty_rows(self) -> None:
        session = _session(
            [
                _response(200, {"activityEventEntities": [_event("e1")], "continuationToken": "t1"}),
                # Empty page that still carries a token: the loop must keep going.
                _response(200, {"activityEventEntities": [], "continuationToken": "t2"}),
                _response(200, {"activityEventEntities": [_event("e2")]}),
            ]
            + [_response(200, {"activityEventEntities": []}) for _ in range(27)]
        )

        batches = _run(ACTIVITY_EVENTS_ENDPOINT, session)

        assert [row["Id"] for batch in batches for row in batch] == ["e1", "e2"]
        params = _activity_params(session)
        assert params[1] == {"continuationToken": "'t1'"}
        assert params[2] == {"continuationToken": "'t2'"}
        # After the day drained, the next request windows the following day again.
        assert "startDateTime" in params[3]

    def test_repeated_continuation_token_stops_the_day_instead_of_looping(self) -> None:
        session = _session(
            [_response(200, {"activityEventEntities": [_event("e1")], "continuationToken": "same"}) for _ in range(2)]
            + [_response(200, {"activityEventEntities": []}) for _ in range(27)]
        )

        batches = _run(ACTIVITY_EVENTS_ENDPOINT, session)

        assert len(batches) == 2
        # 2 pages of the first day + one windowed request for each of the 27 remaining days.
        assert session.get.call_count == 29

    def test_state_is_saved_after_each_page_and_after_each_day(self) -> None:
        manager = _manager()
        session = _session(
            [
                _response(200, {"activityEventEntities": [_event("e1")], "continuationToken": "t1"}),
                _response(200, {"activityEventEntities": [_event("e2")]}),
            ]
            + [_response(200, {"activityEventEntities": []}) for _ in range(27)]
        )

        _run(ACTIVITY_EVENTS_ENDPOINT, session, manager=manager)

        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved[0] == PowerBiAdminResumeConfig(next_day="2026-06-29", continuation_token="t1")
        assert saved[1] == PowerBiAdminResumeConfig(next_day="2026-06-30")
        assert saved[-1] == PowerBiAdminResumeConfig(next_day="2026-07-27")

    def test_resume_starts_from_the_saved_day_and_continuation_token(self) -> None:
        manager = _manager(PowerBiAdminResumeConfig(next_day="2026-07-25", continuation_token="saved-token"))
        session = _session([_response(200, {"activityEventEntities": [_event("e1")]}) for _ in range(2)])

        batches = _run(ACTIVITY_EVENTS_ENDPOINT, session, manager=manager)

        assert len(batches) == 2
        params = _activity_params(session)
        assert params[0] == {"continuationToken": "'saved-token'"}
        assert params[1]["startDateTime"] == "'2026-07-26T00:00:00'"

    def test_resume_takes_precedence_over_the_incremental_watermark(self) -> None:
        manager = _manager(PowerBiAdminResumeConfig(next_day="2026-07-26"))
        session = _session([_response(200, {"activityEventEntities": []})])

        _run(
            ACTIVITY_EVENTS_ENDPOINT,
            session,
            manager=manager,
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-07-01T00:00:00Z",
        )

        assert _activity_params(session)[0]["startDateTime"] == "'2026-07-26T00:00:00'"

    def test_stale_resume_day_drops_its_continuation_token(self) -> None:
        # A token issued before the retention window rolled over is no longer valid, so the
        # clamped day must be re-windowed rather than resumed from the token.
        manager = _manager(PowerBiAdminResumeConfig(next_day="2024-01-01", continuation_token="stale"))
        session = _session([_response(200, {"activityEventEntities": []}) for _ in range(28)])

        _run(ACTIVITY_EVENTS_ENDPOINT, session, manager=manager)

        assert _activity_params(session)[0]["startDateTime"] == "'2026-06-29T00:00:00'"


class TestInventoryEndpoints:
    @parameterized.expand([("groups",), ("datasets",), ("reports",), ("dashboards",), ("dataflows",)])
    def test_short_page_terminates_the_odata_walk(self, endpoint: str) -> None:
        session = _session([_response(200, {"value": [{"id": "a"}, {"id": "b"}]})])

        batches = _run(endpoint, session)

        assert batches == [[{"id": "a"}, {"id": "b"}]]
        assert session.get.call_count == 1
        params = session.get.call_args.kwargs["params"]
        assert params == {"$top": str(ODATA_PAGE_SIZE), "$skip": "0"}

    def test_full_page_advances_skip_until_a_short_page(self) -> None:
        full_page = [{"id": str(i)} for i in range(ODATA_PAGE_SIZE)]
        manager = _manager()
        session = _session([_response(200, {"value": full_page}), _response(200, {"value": [{"id": "last"}]})])

        batches = _run("groups", session, manager=manager)

        assert len(batches) == 2
        assert [call.kwargs["params"]["$skip"] for call in session.get.call_args_list] == ["0", str(ODATA_PAGE_SIZE)]
        assert manager.save_state.call_args_list[0].args[0] == PowerBiAdminResumeConfig(skip=ODATA_PAGE_SIZE)

    def test_resume_starts_from_the_saved_skip(self) -> None:
        manager = _manager(PowerBiAdminResumeConfig(skip=10000))
        session = _session([_response(200, {"value": [{"id": "a"}]})])

        _run("groups", session, manager=manager)

        assert session.get.call_args.kwargs["params"]["$skip"] == "10000"

    def test_capacities_is_a_single_unpaged_request(self) -> None:
        session = _session([_response(200, {"value": [{"id": "c1"}]})])

        batches = _run("capacities", session)

        assert batches == [[{"id": "c1"}]]
        assert session.get.call_args.kwargs["params"] is None

    def test_empty_response_yields_nothing(self) -> None:
        session = _session([_response(200, {"value": []})])

        assert _run("groups", session) == []


class TestSourceResponse:
    @parameterized.expand([(name,) for name in POWER_BI_ADMIN_ENDPOINTS])
    def test_response_carries_the_endpoint_primary_keys(self, endpoint: str) -> None:
        response = power_bi_admin_source(
            tenant_id=TENANT_ID,
            client_id=CLIENT_ID,
            client_secret=CLIENT_SECRET,
            endpoint=endpoint,
            logger=mock.MagicMock(),
            resumable_source_manager=_manager(),
        )

        assert response.name == endpoint
        assert response.primary_keys == POWER_BI_ADMIN_ENDPOINTS[endpoint].primary_keys
        assert response.sort_mode == "asc"

    def test_activity_events_partition_on_creation_time(self) -> None:
        response = power_bi_admin_source(
            tenant_id=TENANT_ID,
            client_id=CLIENT_ID,
            client_secret=CLIENT_SECRET,
            endpoint=ACTIVITY_EVENTS_ENDPOINT,
            logger=mock.MagicMock(),
            resumable_source_manager=_manager(),
        )

        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["CreationTime"]

    def test_inventory_endpoints_have_no_datetime_partitioning(self) -> None:
        response = power_bi_admin_source(
            tenant_id=TENANT_ID,
            client_id=CLIENT_ID,
            client_secret=CLIENT_SECRET,
            endpoint="groups",
            logger=mock.MagicMock(),
            resumable_source_manager=_manager(),
        )

        assert response.partition_mode is None
        assert response.partition_keys is None

    def test_items_is_lazy_and_iterates_the_endpoint(self) -> None:
        session = _session([_response(200, {"value": [{"id": "g1"}]})])
        response = power_bi_admin_source(
            tenant_id=TENANT_ID,
            client_id=CLIENT_ID,
            client_secret=CLIENT_SECRET,
            endpoint="groups",
            logger=mock.MagicMock(),
            resumable_source_manager=_manager(),
        )

        assert session.get.call_count == 0
        with mock.patch(f"{MODULE}.make_tracked_session", return_value=session):
            batches = list(cast("Iterable[Any]", response.items()))

        assert batches == [[{"id": "g1"}]]


class TestValidateCredentials:
    def test_valid_credentials_probe_the_admin_groups_endpoint(self) -> None:
        session = _session([_response(200, {"value": [{"id": "g1"}]})])

        with mock.patch(f"{MODULE}.make_tracked_session", return_value=session):
            is_valid, message = validate_credentials(TENANT_ID, CLIENT_ID, CLIENT_SECRET)

        assert (is_valid, message) == (True, None)
        assert session.get.call_args.kwargs["params"] == {"$top": "1"}

    def test_blank_tenant_id_fails_without_a_request(self) -> None:
        session = _session([])

        with mock.patch(f"{MODULE}.make_tracked_session", return_value=session):
            is_valid, message = validate_credentials("   ", CLIENT_ID, CLIENT_SECRET)

        assert is_valid is False
        assert message is not None and "tenant" in message.lower()
        assert session.post.call_count == 0

    @parameterized.expand([(400,), (401,)])
    def test_rejected_token_reports_bad_service_principal(self, status: int) -> None:
        session = _session([], [_response(status, text="invalid_client")])

        with mock.patch(f"{MODULE}.make_tracked_session", return_value=session):
            is_valid, message = validate_credentials(TENANT_ID, CLIENT_ID, CLIENT_SECRET)

        assert is_valid is False
        assert message is not None and "client secret" in message

    @parameterized.expand([(401,), (403,)])
    def test_denied_admin_api_reports_the_tenant_grant(self, status: int) -> None:
        # A 401 gets one re-mint before it is treated as a denial, so both attempts fail here.
        session = _session(
            [_response(status, text="denied"), _response(status, text="denied")],
            [_token_response("a"), _token_response("b")],
        )

        with mock.patch(f"{MODULE}.make_tracked_session", return_value=session):
            is_valid, message = validate_credentials(TENANT_ID, CLIENT_ID, CLIENT_SECRET)

        assert (is_valid, message) == (False, ADMIN_API_DENIED_ERROR)

    def test_unexpected_admin_api_status_is_reported_with_the_status(self) -> None:
        session = _session([_response(500, text="boom")])

        with mock.patch(f"{MODULE}.make_tracked_session", return_value=session):
            is_valid, message = validate_credentials(TENANT_ID, CLIENT_ID, CLIENT_SECRET)

        assert is_valid is False
        assert message is not None and "500" in message

    def test_network_failure_asks_for_a_retry(self) -> None:
        session = mock.MagicMock(spec=requests.Session)
        session.post.side_effect = requests.ConnectionError("no route to host")

        with mock.patch(f"{MODULE}.make_tracked_session", return_value=session):
            is_valid, message = validate_credentials(TENANT_ID, CLIENT_ID, CLIENT_SECRET)

        assert is_valid is False
        assert message is not None and "retry" in message.lower()
