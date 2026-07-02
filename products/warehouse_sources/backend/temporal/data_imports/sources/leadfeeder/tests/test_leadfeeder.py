from datetime import UTC, date, datetime
from typing import Any

import pytest
from freezegun import freeze_time
from unittest import mock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.leadfeeder import leadfeeder
from products.warehouse_sources.backend.temporal.data_imports.sources.leadfeeder.leadfeeder import (
    LEADFEEDER_BASE_URL,
    LeadfeederResumeConfig,
    LeadfeederRetryableError,
    _build_url,
    _compute_date_range,
    _flatten_item,
    _to_date_str,
    get_rows,
    leadfeeder_source,
    validate_credentials,
)


class _FakeResponse:
    def __init__(self, status_code: int = 200, json_data: Any = None, text: str = ""):
        self.status_code = status_code
        self._json_data = json_data
        self.text = text

    @property
    def ok(self) -> bool:
        return self.status_code < 400

    def json(self) -> Any:
        return self._json_data

    def raise_for_status(self) -> None:
        if not self.ok:
            raise requests.HTTPError(f"{self.status_code} Client Error", response=self)  # type: ignore[arg-type]


class _FakeSession:
    """Returns queued responses in order; records the URLs requested."""

    def __init__(self, responses: list[_FakeResponse]):
        self._responses = list(responses)
        self.requested_urls: list[str] = []

    def get(self, url: str, **kwargs: Any) -> _FakeResponse:
        self.requested_urls.append(url)
        return self._responses.pop(0)


def _manager(can_resume: bool = False, state: LeadfeederResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = can_resume
    manager.load_state.return_value = state
    return manager


def _run(
    endpoint: str, responses: list[_FakeResponse], manager: mock.MagicMock, **kwargs: Any
) -> tuple[list[list[dict]], _FakeSession]:
    session = _FakeSession(responses)
    with mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.leadfeeder.leadfeeder.make_tracked_session",
        return_value=session,
    ):
        return list(get_rows("token", endpoint, mock.MagicMock(), manager, **kwargs)), session


def _item(id_: str, type_: str, **attributes: Any) -> dict[str, Any]:
    return {"id": id_, "type": type_, "attributes": attributes}


class TestFlattenItem:
    def test_lifts_attributes_and_keeps_id_type(self) -> None:
        row = _flatten_item(_item("1", "leads", name="Acme", last_visit_date="2024-06-01"), account_id=None)
        assert row == {"id": "1", "type": "leads", "name": "Acme", "last_visit_date": "2024-06-01"}

    def test_injects_account_id_for_fan_out(self) -> None:
        row = _flatten_item(_item("9", "visits", started_at="2024-06-01T10:00:00Z"), account_id="42")
        assert row["account_id"] == "42"
        assert row["id"] == "9"

    def test_handles_missing_attributes(self) -> None:
        assert _flatten_item({"id": "1", "type": "accounts"}, account_id=None) == {"id": "1", "type": "accounts"}

    def test_missing_id_fails_loudly(self) -> None:
        # `id` is the primary key: a missing one must raise rather than seed a row under a None key.
        with pytest.raises(KeyError):
            _flatten_item({"type": "leads", "attributes": {"name": "Acme"}}, account_id="1")


class TestToDateStr:
    @parameterized.expand(
        [
            (datetime(2024, 6, 1, 15, 30, tzinfo=UTC), "2024-06-01"),
            (date(2024, 6, 1), "2024-06-01"),
            ("2024-06-01T09:00:00Z", "2024-06-01"),
            ("2024-06-01", "2024-06-01"),
        ]
    )
    def test_coerces_to_day_granular_string(self, value: Any, expected: str) -> None:
        assert _to_date_str(value) == expected


class TestComputeDateRange:
    @freeze_time("2026-07-02")
    def test_incremental_uses_watermark_as_start(self) -> None:
        start, end = _compute_date_range(True, date(2024, 5, 1), "2020-01-01")
        assert start == "2024-05-01"
        assert end == "2026-07-02"

    @freeze_time("2026-07-02")
    def test_incremental_floors_datetime_watermark_to_day(self) -> None:
        start, _ = _compute_date_range(True, datetime(2024, 5, 1, 23, 59, tzinfo=UTC), "")
        assert start == "2024-05-01"

    @freeze_time("2026-07-02")
    def test_full_refresh_uses_config_start_date(self) -> None:
        start, end = _compute_date_range(False, None, "2023-01-01")
        assert start == "2023-01-01"
        assert end == "2026-07-02"

    @freeze_time("2026-07-02")
    def test_full_refresh_defaults_to_lookback_window(self) -> None:
        start, _ = _compute_date_range(False, None, "")
        assert start == "2025-07-02"


class TestParseResponse:
    @parameterized.expand([(429,), (500,), (503,)])
    def test_retryable_statuses_raise_retryable_error(self, status: int) -> None:
        with pytest.raises(LeadfeederRetryableError):
            leadfeeder._parse_response(_FakeResponse(status_code=status), "http://x", mock.MagicMock())  # type: ignore[arg-type]

    @parameterized.expand([(401,), (403,), (404,)])
    def test_client_errors_raise_http_error(self, status: int) -> None:
        with pytest.raises(requests.HTTPError):
            leadfeeder._parse_response(_FakeResponse(status_code=status, text="nope"), "http://x", mock.MagicMock())  # type: ignore[arg-type]

    def test_ok_returns_json_body(self) -> None:
        body = {"data": [{"id": "1"}]}
        assert leadfeeder._parse_response(_FakeResponse(json_data=body), "http://x", mock.MagicMock()) == body  # type: ignore[arg-type]


class TestValidateCredentials:
    @parameterized.expand([("valid", 200, True), ("unauthorized", 401, False), ("server_error", 500, False)])
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.leadfeeder.leadfeeder.make_tracked_session"
    )
    def test_status_mapping(self, _name: str, status: int, expected: bool, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.return_value = _FakeResponse(status_code=status)
        assert validate_credentials("token") is expected

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.leadfeeder.leadfeeder.make_tracked_session"
    )
    def test_exception_returns_false(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.side_effect = requests.ConnectionError("boom")
        assert validate_credentials("token") is False

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.leadfeeder.leadfeeder.make_tracked_session"
    )
    def test_sends_token_auth_header(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.return_value = _FakeResponse(status_code=200)
        validate_credentials("secret")
        assert mock_session.return_value.get.call_args.kwargs["headers"]["Authorization"] == "Token token=secret"

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.leadfeeder.leadfeeder.make_tracked_session"
    )
    def test_session_redacts_token_and_blocks_redirects(self, mock_session: mock.MagicMock) -> None:
        # The token rides in a custom `Authorization: Token token=...` header the denylist can't see,
        # so it must be registered for value-based redaction; redirects must not be followed or the
        # credentialed request could resend the token off-origin.
        mock_session.return_value.get.return_value = _FakeResponse(status_code=200)
        validate_credentials("secret")
        assert mock_session.call_args.kwargs["redact_values"] == ("secret",)
        assert mock_session.call_args.kwargs["allow_redirects"] is False


class TestTopLevelPagination:
    def test_follows_next_link_and_saves_state_after_batch(self) -> None:
        page2_url = f"{LEADFEEDER_BASE_URL}/accounts?page[number]=2&page[size]=100"
        responses = [
            _FakeResponse(json_data={"data": [_item("1", "accounts", name="A")], "links": {"next": page2_url}}),
            _FakeResponse(json_data={"data": [_item("2", "accounts", name="B")], "links": {}}),
        ]
        manager = _manager()
        batches, session = _run("accounts", responses, manager)

        assert batches == [
            [{"id": "1", "type": "accounts", "name": "A"}],
            [{"id": "2", "type": "accounts", "name": "B"}],
        ]
        # State is saved once, pointing at the next page, only after the first batch is yielded.
        manager.save_state.assert_called_once_with(LeadfeederResumeConfig(next_url=page2_url))
        # The second page is fetched from the URL the API handed back.
        assert session.requested_urls[1] == page2_url

    def test_resumes_from_saved_next_url(self) -> None:
        resume_url = f"{LEADFEEDER_BASE_URL}/accounts?page[number]=5&page[size]=100"
        manager = _manager(can_resume=True, state=LeadfeederResumeConfig(next_url=resume_url))
        responses = [_FakeResponse(json_data={"data": [_item("7", "accounts")], "links": {}})]
        _batches, session = _run("accounts", responses, manager)
        assert session.requested_urls[0] == resume_url

    def test_empty_page_yields_nothing(self) -> None:
        batches, _ = _run("accounts", [_FakeResponse(json_data={"data": [], "links": {}})], _manager())
        assert batches == []


class TestFanOut:
    def _accounts_response(self, *ids: str) -> _FakeResponse:
        return _FakeResponse(json_data={"data": [_item(i, "accounts") for i in ids], "links": {}})

    def test_iterates_every_account_and_injects_account_id(self) -> None:
        responses = [
            self._accounts_response("1", "2"),
            _FakeResponse(json_data={"data": [_item("100", "leads", name="Acme")], "links": {}}),
            _FakeResponse(json_data={"data": [_item("200", "leads", name="Globex")], "links": {}}),
        ]
        batches, session = _run("leads", responses, _manager())

        assert batches == [
            [{"id": "100", "type": "leads", "name": "Acme", "account_id": "1"}],
            [{"id": "200", "type": "leads", "name": "Globex", "account_id": "2"}],
        ]
        # The lead request carries the server-side date-range filter.
        leads_url = next(u for u in session.requested_urls if "/accounts/1/leads" in u)
        assert "start_date=" in leads_url and "end_date=" in leads_url

    def test_resume_skips_already_processed_accounts(self) -> None:
        manager = _manager(can_resume=True, state=LeadfeederResumeConfig(account_id="2", next_url=None))
        responses = [
            self._accounts_response("1", "2"),
            _FakeResponse(json_data={"data": [_item("200", "leads")], "links": {}}),
        ]
        batches, session = _run("leads", responses, manager)

        assert batches == [[{"id": "200", "type": "leads", "account_id": "2"}]]
        assert not any("/accounts/1/leads" in u for u in session.requested_urls)

    def test_unknown_account_in_saved_state_restarts_from_first(self) -> None:
        # An account deleted between runs must not wedge the sync — fall back to the full list.
        manager = _manager(can_resume=True, state=LeadfeederResumeConfig(account_id="999", next_url=None))
        responses = [
            self._accounts_response("1"),
            _FakeResponse(json_data={"data": [_item("100", "leads")], "links": {}}),
        ]
        batches, _ = _run("leads", responses, manager)
        assert batches == [[{"id": "100", "type": "leads", "account_id": "1"}]]


class TestBuildUrl:
    def test_no_params(self) -> None:
        assert _build_url("/accounts", {}) == f"{LEADFEEDER_BASE_URL}/accounts"

    def test_keeps_literal_brackets(self) -> None:
        url = _build_url("/accounts", {"page[number]": 1, "page[size]": 100})
        assert url == f"{LEADFEEDER_BASE_URL}/accounts?page[number]=1&page[size]=100"


class TestSourceResponse:
    def test_accounts_is_full_refresh_without_partitioning(self) -> None:
        response = leadfeeder_source("token", "accounts", mock.MagicMock(), _manager())
        assert response.name == "accounts"
        assert response.primary_keys == ["id"]
        assert response.partition_mode is None

    @parameterized.expand(
        [
            ("leads", ["account_id", "id"], "first_visit_date"),
            ("visits", ["account_id", "id"], "started_at"),
        ]
    )
    def test_fan_out_endpoints_have_composite_key_and_partition(
        self, endpoint: str, primary_keys: list[str], partition_key: str
    ) -> None:
        response = leadfeeder_source("token", endpoint, mock.MagicMock(), _manager())
        assert response.primary_keys == primary_keys
        assert response.partition_mode == "datetime"
        assert response.partition_keys == [partition_key]
