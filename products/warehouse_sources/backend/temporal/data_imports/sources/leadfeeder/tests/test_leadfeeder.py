import json
from datetime import UTC, date, datetime
from typing import Any

import pytest
from freezegun import freeze_time
from unittest import mock

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.leadfeeder.leadfeeder import (
    LEADFEEDER_BASE_URL,
    LeadfeederResumeConfig,
    _default_start_date,
    _flatten_item,
    _to_date_str,
    leadfeeder_source,
    validate_credentials,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the leadfeeder module.
LEADFEEDER_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.leadfeeder.leadfeeder.make_tracked_session"
)


def _item(id_: str, type_: str, **attributes: Any) -> dict[str, Any]:
    return {"id": id_, "type": type_, "attributes": attributes}


def _response(items: list[dict[str, Any]], next_url: str | None = None) -> Response:
    body: dict[str, Any] = {"data": items, "links": {"next": next_url} if next_url else {}}
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: LeadfeederResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> tuple[list[str], list[dict[str, Any]]]:
    """Wire a mock session, capturing the URL and params of each request AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so snapshot a copy when each
    request is prepared; the prepared mock also needs a real ``.url`` for the host-pinning check.
    """
    session.headers = {}
    urls: list[str] = []
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        urls.append(request.url)
        param_snapshots.append(dict(request.params or {}))
        prepared = mock.MagicMock()
        prepared.url = request.url
        return prepared

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return urls, param_snapshots


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(endpoint: str, manager: mock.MagicMock, **kwargs: Any):
    return leadfeeder_source("token", endpoint, manager, team_id=1, job_id="j", **kwargs)


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


class TestDefaultStartDate:
    @freeze_time("2026-07-02")
    def test_uses_config_start_date_floored(self) -> None:
        assert _default_start_date("2023-01-01T12:00:00Z") == "2023-01-01"

    @freeze_time("2026-07-02")
    def test_defaults_to_lookback_window_when_blank(self) -> None:
        assert _default_start_date("") == "2025-07-02"


class TestTopLevelPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_follows_next_link_and_saves_state_after_batch(self, MockSession) -> None:
        session = MockSession.return_value
        page2_url = f"{LEADFEEDER_BASE_URL}/accounts?page[number]=2&page[size]=100"
        urls, _ = _wire(
            session,
            [
                _response([_item("1", "accounts", name="A")], next_url=page2_url),
                _response([_item("2", "accounts", name="B")]),
            ],
        )
        manager = _make_manager()
        rows = _rows(_source("accounts", manager))

        assert rows == [
            {"id": "1", "type": "accounts", "name": "A"},
            {"id": "2", "type": "accounts", "name": "B"},
        ]
        # State is saved once, pointing at the next page, only while a next link remains.
        manager.save_state.assert_called_once_with(LeadfeederResumeConfig(next_url=page2_url))
        # The second page is fetched from the URL the API handed back.
        assert urls[1] == page2_url

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_next_url(self, MockSession) -> None:
        session = MockSession.return_value
        resume_url = f"{LEADFEEDER_BASE_URL}/accounts?page[number]=5&page[size]=100"
        urls, _ = _wire(session, [_response([_item("7", "accounts")])])
        manager = _make_manager(LeadfeederResumeConfig(next_url=resume_url))

        _rows(_source("accounts", manager))
        assert urls[0] == resume_url

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_page_yields_nothing_and_no_checkpoint(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([])])
        manager = _make_manager()

        assert _rows(_source("accounts", manager)) == []
        manager.save_state.assert_not_called()


class TestFanOut:
    def _accounts_response(self, *ids: str, next_url: str | None = None) -> Response:
        return _response([_item(i, "accounts") for i in ids], next_url=next_url)

    @mock.patch(CLIENT_SESSION_PATCH)
    @freeze_time("2026-07-02")
    def test_iterates_every_account_and_injects_account_id(self, MockSession) -> None:
        session = MockSession.return_value
        urls, params = _wire(
            session,
            [
                self._accounts_response("1", "2"),
                _response([_item("100", "leads", name="Acme")]),
                _response([_item("200", "leads", name="Globex")]),
            ],
        )
        rows = _rows(_source("leads", _make_manager(), start_date_config="2024-01-01"))

        assert rows == [
            {"id": "100", "type": "leads", "name": "Acme", "account_id": "1"},
            {"id": "200", "type": "leads", "name": "Globex", "account_id": "2"},
        ]
        # Each account is fetched at its own fan-out path.
        assert any("/accounts/1/leads" in u for u in urls)
        assert any("/accounts/2/leads" in u for u in urls)
        # The lead request carries the server-side date-range filter.
        lead_params = next(p for p in params if "start_date" in p)
        assert lead_params["start_date"] == "2024-01-01"
        assert lead_params["end_date"] == "2026-07-02"

    @mock.patch(CLIENT_SESSION_PATCH)
    @freeze_time("2026-07-02")
    def test_incremental_watermark_sets_start_date(self, MockSession) -> None:
        session = MockSession.return_value
        _, params = _wire(session, [self._accounts_response("1"), _response([_item("100", "leads")])])

        rows = _rows(
            _source(
                "leads",
                _make_manager(),
                start_date_config="2020-01-01",
                should_use_incremental_field=True,
                db_incremental_field_last_value=date(2024, 5, 1),
            )
        )
        assert rows == [{"id": "100", "type": "leads", "account_id": "1"}]
        lead_params = next(p for p in params if "start_date" in p)
        # The watermark wins over the configured start date, floored to a day.
        assert lead_params["start_date"] == "2024-05-01"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resume_skips_completed_accounts(self, MockSession) -> None:
        session = MockSession.return_value
        urls, _ = _wire(session, [self._accounts_response("1", "2"), _response([_item("200", "leads")])])
        manager = _make_manager(
            LeadfeederResumeConfig(
                fanout_state={"completed": ["/accounts/1/leads"], "current": None, "child_state": None}
            )
        )
        rows = _rows(_source("leads", manager))

        assert rows == [{"id": "200", "type": "leads", "account_id": "2"}]
        assert not any("/accounts/1/leads" in u for u in urls)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_unknown_completed_account_does_not_wedge_sync(self, MockSession) -> None:
        # A completed path for an account that no longer exists must not stop the remaining accounts.
        session = MockSession.return_value
        _wire(session, [self._accounts_response("1"), _response([_item("100", "leads")])])
        manager = _make_manager(
            LeadfeederResumeConfig(
                fanout_state={"completed": ["/accounts/999/leads"], "current": None, "child_state": None}
            )
        )
        assert _rows(_source("leads", manager)) == [{"id": "100", "type": "leads", "account_id": "1"}]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_old_shape_resume_starts_fresh(self, MockSession) -> None:
        # A pre-migration state (account_id/next_url, no fanout_state) still parses and starts fresh.
        session = MockSession.return_value
        urls, _ = _wire(
            session,
            [self._accounts_response("1", "2"), _response([_item("100", "leads")]), _response([_item("200", "leads")])],
        )
        manager = _make_manager(LeadfeederResumeConfig(account_id="2", next_url=None))
        rows = _rows(_source("leads", manager))

        assert {r["account_id"] for r in rows} == {"1", "2"}
        assert any("/accounts/1/leads" in u for u in urls)


class TestSourceResponse:
    def test_accounts_is_full_refresh_without_partitioning(self) -> None:
        response = _source("accounts", _make_manager())
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
        response = _source(endpoint, _make_manager())
        assert response.primary_keys == primary_keys
        assert response.partition_mode == "datetime"
        assert response.partition_keys == [partition_key]


class TestValidateCredentials:
    @parameterized.expand([("valid", 200, True), ("unauthorized", 401, False), ("server_error", 500, False)])
    @mock.patch(LEADFEEDER_SESSION_PATCH)
    def test_status_mapping(self, _name: str, status: int, expected: bool, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status)
        assert validate_credentials("token") is expected

    @mock.patch(LEADFEEDER_SESSION_PATCH)
    def test_exception_returns_false(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("token") is False

    @mock.patch(LEADFEEDER_SESSION_PATCH)
    def test_sends_token_auth_header(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)
        validate_credentials("secret")
        assert mock_session.return_value.get.call_args.kwargs["headers"]["Authorization"] == "Token token=secret"

    @mock.patch(LEADFEEDER_SESSION_PATCH)
    def test_session_redacts_token_and_blocks_redirects(self, mock_session: mock.MagicMock) -> None:
        # The token rides in a custom `Authorization: Token token=...` header the denylist can't see,
        # so it must be registered for value-based redaction; redirects must not be followed or the
        # credentialed request could resend the token off-origin.
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)
        validate_credentials("secret")
        assert mock_session.call_args.kwargs["redact_values"] == ("secret",)
        assert mock_session.call_args.kwargs["allow_redirects"] is False
