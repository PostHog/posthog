from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any, Optional, cast

import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.toast.settings import (
    RESTAURANT_GUID_FIELD,
    TOAST_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.toast.toast import (
    NEXT_PAGE_TOKEN_HEADER,
    RESTAURANT_HEADER,
    TOAST_LOGIN_FAILED_MESSAGE,
    ToastAuthenticationError,
    ToastClient,
    ToastResumeConfig,
    base_url_for,
    coerce_datetime,
    extract_rows,
    format_toast_datetime,
    get_rows,
    iter_request_units,
    parse_restaurant_guids,
    resolve_window,
    toast_source,
    validate_credentials,
)

BASE_URL = "https://ws-api.toasttab.com"
GUID_A = "aaaaaaaa-1111-2222-3333-444444444444"
GUID_B = "bbbbbbbb-1111-2222-3333-444444444444"


class FakeResponse:
    def __init__(self, body: Any, headers: Optional[dict[str, str]] = None, status_code: int = 200) -> None:
        self._body = body
        self.headers = headers or {}
        self.status_code = status_code

    def json(self) -> Any:
        if isinstance(self._body, Exception):
            raise self._body
        return self._body

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(
                f"{self.status_code} Client Error for url: {BASE_URL}",
                response=cast(requests.Response, self),
            )


def as_response(body: Any, headers: Optional[dict[str, str]] = None) -> requests.Response:
    return cast(requests.Response, FakeResponse(body, headers))


class FakeResumableSourceManager(ResumableSourceManager[ToastResumeConfig]):
    def __init__(self, state: Optional[ToastResumeConfig] = None) -> None:
        self.state = state
        self.saved: list[ToastResumeConfig] = []
        self.cleared = False

    def can_resume(self) -> bool:
        return self.state is not None

    def load_state(self) -> Optional[ToastResumeConfig]:
        return self.state

    def save_state(self, data: ToastResumeConfig) -> None:
        self.saved.append(data)

    def clear_state(self) -> None:
        self.cleared = True


def make_client() -> ToastClient:
    client = ToastClient(BASE_URL, "client-id", "client-secret")
    client._token = "minted-token"
    client._token_expires_at = float("inf")
    return client


def drain(
    client: ToastClient,
    endpoint: str,
    restaurant_guids: list[str],
    manager: FakeResumableSourceManager,
    window_start: datetime = datetime(2024, 1, 1, tzinfo=UTC),
    window_end: datetime = datetime(2024, 1, 5, tzinfo=UTC),
    use_modified_window: bool = False,
) -> list[list[dict[str, Any]]]:
    batches: Iterator[list[dict[str, Any]]] = get_rows(
        client=client,
        endpoint=endpoint,
        restaurant_guids=restaurant_guids,
        window_start=window_start,
        window_end=window_end,
        use_modified_window=use_modified_window,
        resumable_source_manager=manager,
        logger=mock.MagicMock(),
    )
    return list(batches)


class TestToast:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("a,b", ["a", "b"]),
            ("a, b ,c", ["a", "b", "c"]),
            ("a\nb\n\nc", ["a", "b", "c"]),
            ("a,a,b", ["a", "b"]),
            ("  ", []),
            (None, []),
            (f"{GUID_A}", [GUID_A]),
        ],
    )
    def test_parse_restaurant_guids(self, raw: Optional[str], expected: list[str]) -> None:
        assert parse_restaurant_guids(raw) == expected

    def test_base_url_for_known_environments(self) -> None:
        assert base_url_for("production") == BASE_URL
        assert base_url_for("sandbox") == "https://ws-sandbox-api.toasttab.com"

    def test_base_url_for_rejects_unknown_environment(self) -> None:
        with pytest.raises(ValueError):
            base_url_for("staging")

    def test_format_toast_datetime_uses_numeric_utc_offset(self) -> None:
        assert format_toast_datetime(datetime(2024, 3, 1, 12, 30, tzinfo=UTC)) == "2024-03-01T12:30:00.000+0000"

    @pytest.mark.parametrize(
        "value,expected",
        [
            ("2024-03-01", datetime(2024, 3, 1, tzinfo=UTC)),
            ("2024-03-01T05:00:00Z", datetime(2024, 3, 1, 5, tzinfo=UTC)),
            ("2024-03-01T05:00:00.000+0000", datetime(2024, 3, 1, 5, tzinfo=UTC)),
            (datetime(2024, 3, 1, 5), datetime(2024, 3, 1, 5, tzinfo=UTC)),
            ("not-a-date", None),
            ("", None),
            (None, None),
        ],
    )
    def test_coerce_datetime(self, value: Any, expected: Optional[datetime]) -> None:
        assert coerce_datetime(value) == expected

    def test_access_token_mints_machine_client_token_once(self) -> None:
        client = ToastClient(BASE_URL, "client-id", "client-secret")
        post = mock.MagicMock(return_value=as_response({"token": {"accessToken": "jwt", "expiresIn": 86400}}))
        with mock.patch.object(client, "_auth_session", mock.MagicMock(post=post)):
            assert client.access_token() == "jwt"
            assert client.access_token() == "jwt"

        assert post.call_count == 1
        assert post.call_args.kwargs["json"] == {
            "clientId": "client-id",
            "clientSecret": "client-secret",
            "userAccessType": "TOAST_MACHINE_CLIENT",
        }
        assert post.call_args.args[0] == f"{BASE_URL}/authentication/v1/authentication/login"

    def test_access_token_re_mints_once_the_token_expires(self) -> None:
        client = ToastClient(BASE_URL, "client-id", "client-secret")
        post = mock.MagicMock(
            side_effect=[
                as_response({"token": {"accessToken": "first", "expiresIn": 0}}),
                as_response({"token": {"accessToken": "second", "expiresIn": 86400}}),
            ]
        )
        with mock.patch.object(client, "_auth_session", mock.MagicMock(post=post)):
            assert client.access_token() == "first"
            assert client.access_token() == "second"

    @pytest.mark.parametrize("body", [{}, {"token": {}}, {"token": {"accessToken": ""}}, {"status": "SUCCESS"}])
    def test_access_token_raises_when_login_returns_no_token(self, body: dict[str, Any]) -> None:
        client = ToastClient(BASE_URL, "client-id", "client-secret")
        with mock.patch.object(
            client, "_auth_session", mock.MagicMock(post=mock.MagicMock(return_value=as_response(body)))
        ):
            with pytest.raises(ToastAuthenticationError, match=TOAST_LOGIN_FAILED_MESSAGE):
                client.access_token()

    def test_get_sends_bearer_token_and_restaurant_header(self) -> None:
        client = make_client()
        session_get = mock.MagicMock(return_value=as_response([]))
        with mock.patch.object(client, "_session", mock.MagicMock(get=session_get)):
            client.get("/labor/v1/jobs", GUID_A, {"pageSize": 100})

        headers = session_get.call_args.kwargs["headers"]
        assert headers["Authorization"] == "Bearer minted-token"
        assert headers[RESTAURANT_HEADER] == GUID_A
        assert session_get.call_args.kwargs["params"] == {"pageSize": 100}

    def test_get_re_mints_the_token_once_on_a_401(self) -> None:
        client = make_client()
        session_get = mock.MagicMock(
            side_effect=[
                cast(requests.Response, FakeResponse([], status_code=401)),
                as_response([{"guid": "1"}]),
            ]
        )
        mint = mock.MagicMock(side_effect=lambda: setattr(client, "_token", "re-minted"))
        with (
            mock.patch.object(client, "_session", mock.MagicMock(get=session_get)),
            mock.patch.object(client, "_mint_token", mint),
        ):
            client.get("/labor/v1/jobs", GUID_A)

        assert mint.call_count == 1
        assert session_get.call_count == 2
        assert session_get.call_args_list[1].kwargs["headers"]["Authorization"] == "Bearer re-minted"

    def test_get_raises_when_the_retry_also_fails(self) -> None:
        client = make_client()
        session_get = mock.MagicMock(return_value=cast(requests.Response, FakeResponse([], status_code=401)))
        mint = mock.MagicMock(side_effect=lambda: setattr(client, "_token", "re-minted"))
        with (
            mock.patch.object(client, "_session", mock.MagicMock(get=session_get)),
            mock.patch.object(client, "_mint_token", mint),
        ):
            with pytest.raises(requests.HTTPError):
                client.get("/labor/v1/jobs", GUID_A)

    def test_date_range_units_chunk_to_the_endpoints_window(self) -> None:
        units = list(
            iter_request_units(
                TOAST_ENDPOINTS["orders"],
                datetime(2024, 1, 1, tzinfo=UTC),
                datetime(2024, 4, 1, tzinfo=UTC),
                use_modified_window=False,
            )
        )

        assert len(units) == 4  # 91 days at 30 days per request
        assert units[0][1] == {
            "startDate": "2024-01-01T00:00:00.000+0000",
            "endDate": "2024-01-31T00:00:00.000+0000",
        }
        assert units[-1][1]["endDate"] == "2024-04-01T00:00:00.000+0000"

    def test_date_range_units_switch_to_the_modified_filter_when_incremental(self) -> None:
        units = list(
            iter_request_units(
                TOAST_ENDPOINTS["orders"],
                datetime(2024, 1, 1, tzinfo=UTC),
                datetime(2024, 1, 10, tzinfo=UTC),
                use_modified_window=True,
            )
        )

        assert list(units[0][1]) == ["modifiedStartDate", "modifiedEndDate"]

    def test_shifts_keep_the_plain_window_because_they_have_no_modified_filter(self) -> None:
        units = list(
            iter_request_units(
                TOAST_ENDPOINTS["shifts"],
                datetime(2024, 1, 1, tzinfo=UTC),
                datetime(2024, 1, 10, tzinfo=UTC),
                use_modified_window=False,
            )
        )

        assert list(units[0][1]) == ["startDate", "endDate"]

    def test_business_date_units_are_one_request_per_day(self) -> None:
        units = list(
            iter_request_units(
                TOAST_ENDPOINTS["cash_entries"],
                datetime(2024, 1, 1, 18, tzinfo=UTC),
                datetime(2024, 1, 3, 6, tzinfo=UTC),
                use_modified_window=False,
            )
        )

        assert [key for key, _ in units] == ["2024-01-01", "2024-01-02", "2024-01-03"]
        assert [params["businessDate"] for _, params in units] == ["20240101", "20240102", "20240103"]

    def test_unwindowed_endpoints_make_a_single_unfiltered_request(self) -> None:
        units = list(
            iter_request_units(
                TOAST_ENDPOINTS["employees"],
                datetime(2024, 1, 1, tzinfo=UTC),
                datetime(2024, 4, 1, tzinfo=UTC),
                use_modified_window=False,
            )
        )

        assert units == [("", {})]

    @pytest.mark.parametrize(
        "endpoint,body,expected_guids",
        [
            ("employees", [{"guid": "1"}, {"guid": "2"}], ["1", "2"]),
            ("employees", {"data": [{"guid": "1"}]}, ["1"]),
            ("employees", {"guid": "1"}, []),
            ("employees", None, []),
            ("restaurants", {"guid": "1"}, ["1"]),
            ("restaurants", [{"guid": "1"}], []),
        ],
    )
    def test_extract_rows_handles_each_response_shape(
        self, endpoint: str, body: Any, expected_guids: list[str]
    ) -> None:
        rows = extract_rows(as_response(body), TOAST_ENDPOINTS[endpoint], GUID_A)

        assert [row["guid"] for row in rows] == expected_guids
        assert all(row[RESTAURANT_GUID_FIELD] == GUID_A for row in rows)

    def test_extract_rows_survives_a_non_json_body(self) -> None:
        assert extract_rows(as_response(ValueError("not json")), TOAST_ENDPOINTS["employees"], GUID_A) == []

    def test_page_pagination_stops_on_a_short_page(self) -> None:
        client = make_client()
        full_page = [{"guid": str(i)} for i in range(100)]
        responses = [as_response(full_page), as_response([{"guid": "last"}])]
        manager = FakeResumableSourceManager()

        with mock.patch.object(client, "get", mock.MagicMock(side_effect=responses)) as client_get:
            batches = drain(client, "orders", [GUID_A], manager)

        assert client_get.call_count == 2
        assert [call.args[2]["page"] for call in client_get.call_args_list] == [1, 2]
        assert len(batches) == 2
        assert manager.cleared is True

    def test_token_pagination_follows_the_next_page_header_until_it_disappears(self) -> None:
        client = make_client()
        responses = [
            as_response([{"guid": "1"}], {NEXT_PAGE_TOKEN_HEADER: "token-2"}),
            as_response([{"guid": "2"}], {}),
        ]
        manager = FakeResumableSourceManager()

        with mock.patch.object(client, "get", mock.MagicMock(side_effect=responses)) as client_get:
            batches = drain(client, "employees", [GUID_A], manager)

        assert client_get.call_count == 2
        assert "pageToken" not in client_get.call_args_list[0].args[2]
        assert client_get.call_args_list[1].args[2]["pageToken"] == "token-2"
        assert [row["guid"] for batch in batches for row in batch] == ["1", "2"]

    def test_token_pagination_stops_on_an_empty_page_even_with_a_next_token(self) -> None:
        client = make_client()
        responses = [as_response([], {NEXT_PAGE_TOKEN_HEADER: "token-2"})]
        manager = FakeResumableSourceManager()

        with mock.patch.object(client, "get", mock.MagicMock(side_effect=responses)) as client_get:
            batches = drain(client, "employees", [GUID_A], manager)

        assert client_get.call_count == 1
        assert batches == []

    def test_every_restaurant_is_walked_and_stamped_onto_its_rows(self) -> None:
        client = make_client()
        responses = [as_response([{"guid": "1"}]), as_response([{"guid": "2"}])]
        manager = FakeResumableSourceManager()

        with mock.patch.object(client, "get", mock.MagicMock(side_effect=responses)) as client_get:
            batches = drain(client, "employees", [GUID_A, GUID_B], manager)

        assert [call.args[1] for call in client_get.call_args_list] == [GUID_A, GUID_B]
        assert [row[RESTAURANT_GUID_FIELD] for batch in batches for row in batch] == [GUID_A, GUID_B]

    def test_state_is_saved_after_each_batch_with_the_position_that_produced_it(self) -> None:
        client = make_client()
        full_page = [{"guid": str(i)} for i in range(100)]
        responses = [as_response(full_page), as_response([{"guid": "last"}])]
        manager = FakeResumableSourceManager()

        with mock.patch.object(client, "get", mock.MagicMock(side_effect=responses)):
            drain(client, "orders", [GUID_A], manager, window_end=datetime(2024, 1, 5, tzinfo=UTC))

        assert [(state.restaurant_guid, state.page) for state in manager.saved] == [(GUID_A, 1), (GUID_A, 2)]
        assert manager.saved[0].window_start == "2024-01-01T00:00:00+00:00"

    def test_resume_skips_earlier_restaurants_windows_and_pages(self) -> None:
        client = make_client()
        manager = FakeResumableSourceManager(
            ToastResumeConfig(restaurant_guid=GUID_B, window_start="2024-01-02", page=None)
        )

        with mock.patch.object(client, "get", mock.MagicMock(return_value=as_response([]))) as client_get:
            drain(
                client,
                "cash_entries",
                [GUID_A, GUID_B],
                manager,
                window_start=datetime(2024, 1, 1, tzinfo=UTC),
                window_end=datetime(2024, 1, 3, tzinfo=UTC),
            )

        assert [call.args[1] for call in client_get.call_args_list] == [GUID_B, GUID_B]
        assert [call.args[2]["businessDate"] for call in client_get.call_args_list] == ["20240102", "20240103"]

    def test_resume_restarts_pagination_for_windows_after_the_checkpoint(self) -> None:
        client = make_client()
        manager = FakeResumableSourceManager(
            ToastResumeConfig(restaurant_guid=GUID_A, window_start="2024-01-01T00:00:00+00:00", page=7)
        )
        responses = [as_response([{"guid": "1"}]), as_response([{"guid": "2"}])]

        with mock.patch.object(client, "get", mock.MagicMock(side_effect=responses)) as client_get:
            drain(client, "orders", [GUID_A], manager, window_end=datetime(2024, 2, 15, tzinfo=UTC))

        # First window resumes at the saved page; the next window starts from page 1 again.
        assert [call.args[2]["page"] for call in client_get.call_args_list] == [7, 1]

    def test_resume_state_for_an_unknown_restaurant_is_discarded(self) -> None:
        client = make_client()
        manager = FakeResumableSourceManager(ToastResumeConfig(restaurant_guid="gone", window_start=None, page=3))

        with mock.patch.object(client, "get", mock.MagicMock(return_value=as_response([]))) as client_get:
            drain(client, "employees", [GUID_A], manager)

        assert [call.args[1] for call in client_get.call_args_list] == [GUID_A]

    def test_single_object_endpoints_format_the_restaurant_into_the_path(self) -> None:
        client = make_client()
        manager = FakeResumableSourceManager()

        with mock.patch.object(client, "get", mock.MagicMock(return_value=as_response({"guid": GUID_A}))) as client_get:
            batches = drain(client, "restaurants", [GUID_A], manager)

        assert client_get.call_args.args[0] == f"/restaurants/v1/restaurants/{GUID_A}"
        assert batches == [[{"guid": GUID_A, RESTAURANT_GUID_FIELD: GUID_A}]]

    @pytest.mark.parametrize(
        "should_use_incremental,last_value,start_date,expected_start,expected_modified",
        [
            (True, "2024-05-01T00:00:00Z", "2024-01-01", datetime(2024, 5, 1, tzinfo=UTC), True),
            (False, None, "2024-01-01", datetime(2024, 1, 1, tzinfo=UTC), False),
            (True, None, "2024-01-01", datetime(2024, 1, 1, tzinfo=UTC), True),
            (False, "2024-05-01T00:00:00Z", "2024-01-01", datetime(2024, 1, 1, tzinfo=UTC), False),
        ],
    )
    def test_resolve_window_picks_the_watermark_then_the_start_date(
        self,
        should_use_incremental: bool,
        last_value: Optional[str],
        start_date: Optional[str],
        expected_start: datetime,
        expected_modified: bool,
    ) -> None:
        now = datetime(2024, 6, 1, tzinfo=UTC)
        start, end, use_modified = resolve_window(
            TOAST_ENDPOINTS["orders"], start_date, should_use_incremental, last_value, now=now
        )

        assert (start, end, use_modified) == (expected_start, now, expected_modified)

    def test_resolve_window_falls_back_to_the_default_backfill(self) -> None:
        now = datetime(2024, 6, 1, tzinfo=UTC)
        start, _, _ = resolve_window(TOAST_ENDPOINTS["orders"], None, False, None, now=now)

        assert (now - start).days == 365

    def test_resolve_window_caps_an_arbitrarily_old_start_date(self) -> None:
        now = datetime(2024, 6, 1, tzinfo=UTC)
        start, _, _ = resolve_window(TOAST_ENDPOINTS["cash_entries"], "0001-01-01", False, None, now=now)

        assert (now - start).days == 730

    def test_resolve_window_never_starts_after_it_ends(self) -> None:
        now = datetime(2024, 6, 1, tzinfo=UTC)
        start, end, _ = resolve_window(TOAST_ENDPOINTS["orders"], None, True, "2030-01-01T00:00:00Z", now=now)

        assert start == end

    def test_endpoints_without_a_modified_filter_never_use_the_modified_window(self) -> None:
        _, _, use_modified = resolve_window(TOAST_ENDPOINTS["shifts"], None, True, "2024-01-01T00:00:00Z")

        assert use_modified is False

    @pytest.mark.parametrize("endpoint", sorted(TOAST_ENDPOINTS))
    def test_toast_source_shape_matches_the_endpoint_settings(self, endpoint: str) -> None:
        config = TOAST_ENDPOINTS[endpoint]
        response = toast_source(
            environment="production",
            client_id="client-id",
            client_secret="client-secret",
            restaurant_guids=f"{GUID_A},{GUID_B}",
            start_date="2024-01-01",
            endpoint=endpoint,
            resumable_source_manager=FakeResumableSourceManager(),
            logger=mock.MagicMock(),
        )

        assert response.name == endpoint
        assert response.primary_keys == config.primary_key
        assert response.sort_mode == "asc"
        assert response.partition_keys == ([config.partition_key] if config.partition_key else None)
        assert response.partition_mode == ("datetime" if config.partition_key else None)

    def test_toast_source_items_walk_every_configured_restaurant(self) -> None:
        response = toast_source(
            environment="production",
            client_id="client-id",
            client_secret="client-secret",
            restaurant_guids=f"{GUID_A}\n{GUID_B}",
            start_date="2024-01-01",
            endpoint="jobs",
            resumable_source_manager=FakeResumableSourceManager(),
            logger=mock.MagicMock(),
        )

        with mock.patch.object(ToastClient, "get", mock.MagicMock(return_value=as_response([{"guid": "1"}]))):
            rows = [row for batch in cast("Iterator[list[dict[str, Any]]]", response.items()) for row in batch]

        assert [row[RESTAURANT_GUID_FIELD] for row in rows] == [GUID_A, GUID_B]

    def test_validate_credentials_succeeds_when_a_token_mints(self) -> None:
        with mock.patch.object(ToastClient, "access_token", mock.MagicMock(return_value="jwt")):
            assert validate_credentials("production", "client-id", "client-secret", GUID_A) == (True, None)

    @pytest.mark.parametrize(
        "error",
        [
            ToastAuthenticationError(TOAST_LOGIN_FAILED_MESSAGE),
            requests.HTTPError("401 Client Error: Unauthorized", response=as_response({})),
            requests.ConnectionError("boom"),
        ],
    )
    def test_validate_credentials_fails_on_any_login_error(self, error: Exception) -> None:
        with mock.patch.object(ToastClient, "access_token", mock.MagicMock(side_effect=error)):
            valid, message = validate_credentials("production", "client-id", "client-secret", GUID_A)

        assert valid is False
        assert message is not None

    @pytest.mark.parametrize("guids", ["", "   ", None])
    def test_validate_credentials_requires_a_restaurant_guid(self, guids: Optional[str]) -> None:
        valid, message = validate_credentials("production", "client-id", "client-secret", guids)

        assert valid is False
        assert message == "Enter at least one Toast restaurant GUID."

    def test_validate_credentials_rejects_an_unknown_environment(self) -> None:
        valid, message = validate_credentials("staging", "client-id", "client-secret", GUID_A)

        assert valid is False
        assert message is not None and "staging" in message
