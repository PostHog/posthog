from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from unittest.mock import MagicMock, patch

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.sendgrid.sendgrid import (
    SendGridResumeConfig,
    _build_base_params,
    _offset_from_url,
    _select_items,
    _to_epoch_seconds,
    get_rows,
    get_status_code,
    sendgrid_source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sendgrid.settings import SENDGRID_ENDPOINTS

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.sendgrid.sendgrid"


class _FakeResponse:
    def __init__(self, status_code: int, body: Any) -> None:
        self.status_code = status_code
        self._body = body
        self.text = str(body)

    @property
    def ok(self) -> bool:
        return self.status_code < 400

    def json(self) -> Any:
        return self._body

    def raise_for_status(self) -> None:
        if not self.ok:
            raise AssertionError(f"HTTP {self.status_code}")


def _session_returning(*responses: _FakeResponse) -> MagicMock:
    session = MagicMock()
    session.get.side_effect = list(responses)
    return session


def _manager(can_resume: bool = False, resume_state: SendGridResumeConfig | None = None) -> MagicMock:
    manager = MagicMock(spec=ResumableSourceManager)
    manager.can_resume.return_value = can_resume
    manager.load_state.return_value = resume_state
    return manager


class TestToEpochSeconds:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (1700000000, 1700000000),
            ("1700000000", 1700000000),
            (datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC), 1700000000),
            (date(1970, 1, 2), 86400),
        ],
    )
    def test_to_epoch_seconds(self, value: Any, expected: int) -> None:
        assert _to_epoch_seconds(value) == expected

    def test_naive_datetime_treated_as_utc(self) -> None:
        assert _to_epoch_seconds(datetime(2023, 11, 14, 22, 13, 20)) == 1700000000


class TestBuildBaseParams:
    def test_incremental_sets_start_time(self) -> None:
        params = _build_base_params(
            SENDGRID_ENDPOINTS["bounces"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=1700000000,
            incremental_field="created",
        )
        assert params == {"start_time": 1700000000}

    def test_no_start_time_without_incremental(self) -> None:
        params = _build_base_params(
            SENDGRID_ENDPOINTS["bounces"],
            should_use_incremental_field=False,
            db_incremental_field_last_value=1700000000,
            incremental_field="created",
        )
        assert params == {}

    def test_full_refresh_endpoint_keeps_extra_params(self) -> None:
        params = _build_base_params(
            SENDGRID_ENDPOINTS["templates"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=1700000000,
            incremental_field="created",
        )
        # templates has no incremental_param, so the cursor is ignored but static params remain.
        assert params == {"generations": "legacy,dynamic"}


class TestSelectItems:
    def test_bare_array(self) -> None:
        config = SENDGRID_ENDPOINTS["bounces"]
        assert _select_items(config, [{"email": "a@x.com"}]) == [{"email": "a@x.com"}]

    def test_result_key(self) -> None:
        config = SENDGRID_ENDPOINTS["marketing_lists"]
        assert _select_items(config, {"result": [{"id": 1}], "_metadata": {}}) == [{"id": 1}]

    def test_bare_array_raises_on_shape_change(self) -> None:
        with pytest.raises(ValueError):
            _select_items(SENDGRID_ENDPOINTS["bounces"], {"unexpected": "dict"})

    def test_result_key_raises_on_missing_key(self) -> None:
        with pytest.raises(KeyError):
            _select_items(SENDGRID_ENDPOINTS["marketing_lists"], {"_metadata": {}})


class TestOffsetFromUrl:
    @pytest.mark.parametrize(
        ("url", "expected"),
        [
            ("https://api.sendgrid.com/v3/suppression/bounces?limit=500&offset=500", 500),
            ("https://api.sendgrid.com/v3/suppression/bounces?limit=500", 0),
            ("https://api.sendgrid.com/v3/suppression/bounces", 0),
        ],
    )
    def test_offset_from_url(self, url: str, expected: int) -> None:
        assert _offset_from_url(url) == expected


class TestGetRowsOffsetPagination:
    def test_paginates_until_short_page_and_saves_state(self) -> None:
        page_size = SENDGRID_ENDPOINTS["bounces"].page_size
        page1 = [{"email": f"a{i}@x.com", "created": i} for i in range(page_size)]
        page2 = [{"email": "b@x.com", "created": 1}]
        session = _session_returning(_FakeResponse(200, page1), _FakeResponse(200, page2))
        manager = _manager()

        with patch(f"{MODULE}.make_tracked_session", return_value=session):
            batches = list(get_rows("k", "bounces", MagicMock(), manager))

        assert batches == [page1, page2]
        # State saved once (after the full first page); not after the terminal short page.
        assert manager.save_state.call_count == 1
        saved_url = manager.save_state.call_args[0][0].next_url
        assert _offset_from_url(saved_url) == page_size
        session.close.assert_called_once()

    def test_resumes_from_saved_url(self) -> None:
        resume_url = "https://api.sendgrid.com/v3/suppression/bounces?limit=500&offset=500"
        session = _session_returning(_FakeResponse(200, [{"email": "b@x.com", "created": 1}]))
        manager = _manager(can_resume=True, resume_state=SendGridResumeConfig(next_url=resume_url))

        with patch(f"{MODULE}.make_tracked_session", return_value=session):
            batches = list(get_rows("k", "bounces", MagicMock(), manager))

        assert len(batches) == 1
        assert session.get.call_args_list[0][0][0] == resume_url

    def test_incremental_start_time_in_initial_url(self) -> None:
        session = _session_returning(_FakeResponse(200, [{"email": "b@x.com", "created": 1}]))
        with patch(f"{MODULE}.make_tracked_session", return_value=session):
            list(
                get_rows(
                    "k",
                    "bounces",
                    MagicMock(),
                    _manager(),
                    should_use_incremental_field=True,
                    db_incremental_field_last_value=1700000000,
                    incremental_field="created",
                )
            )

        query = parse_qs(urlparse(session.get.call_args_list[0][0][0]).query)
        assert query["start_time"] == ["1700000000"]
        assert query["offset"] == ["0"]


class TestGetRowsMetadataPagination:
    def test_follows_metadata_next(self) -> None:
        next_url = "https://api.sendgrid.com/v3/marketing/lists?page_token=tok&page_size=100"
        page1 = {"result": [{"id": 1}], "_metadata": {"next": next_url}}
        page2 = {"result": [{"id": 2}], "_metadata": {}}
        session = _session_returning(_FakeResponse(200, page1), _FakeResponse(200, page2))
        manager = _manager()

        with patch(f"{MODULE}.make_tracked_session", return_value=session):
            batches = list(get_rows("k", "marketing_lists", MagicMock(), manager))

        assert batches == [[{"id": 1}], [{"id": 2}]]
        assert session.get.call_args_list[1][0][0] == next_url
        assert manager.save_state.call_args[0][0].next_url == next_url


class TestGetRowsOffHostGuard:
    @pytest.mark.parametrize(
        "off_host_url",
        [
            "http://169.254.169.254/latest/meta-data/",
            "https://evil.example.com/v3/marketing/lists",
            "https://api.sendgrid.com.evil.com/v3/marketing/lists",
        ],
    )
    def test_off_host_metadata_next_is_ignored(self, off_host_url: str) -> None:
        page1 = {"result": [{"id": 1}], "_metadata": {"next": off_host_url}}
        session = _session_returning(_FakeResponse(200, page1))
        manager = _manager()

        with patch(f"{MODULE}.make_tracked_session", return_value=session):
            batches = list(get_rows("k", "marketing_lists", MagicMock(), manager))

        # The tampered next URL is dropped: we yield the first page and stop without following it.
        assert batches == [[{"id": 1}]]
        assert session.get.call_count == 1
        manager.save_state.assert_not_called()

    def test_off_host_resume_url_raises(self) -> None:
        manager = _manager(
            can_resume=True,
            resume_state=SendGridResumeConfig(next_url="http://169.254.169.254/latest/meta-data/"),
        )
        session = _session_returning()

        with patch(f"{MODULE}.make_tracked_session", return_value=session):
            with pytest.raises(ValueError, match="unexpected URL"):
                list(get_rows("k", "marketing_lists", MagicMock(), manager))


class TestGetRowsSingle:
    def test_single_request_no_pagination(self) -> None:
        groups = [{"id": 1}, {"id": 2}]
        session = _session_returning(_FakeResponse(200, groups))
        manager = _manager()

        with patch(f"{MODULE}.make_tracked_session", return_value=session):
            batches = list(get_rows("k", "unsubscribe_groups", MagicMock(), manager))

        assert batches == [groups]
        assert session.get.call_count == 1
        manager.save_state.assert_not_called()


class TestSendGridSourceResponse:
    def test_suppression_endpoint_partitioning_and_keys(self) -> None:
        response = sendgrid_source("k", "bounces", MagicMock(), _manager())
        assert response.name == "bounces"
        assert response.primary_keys == ["email"]
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["created"]
        assert response.sort_mode == "asc"

    def test_full_refresh_endpoint_has_no_partitioning(self) -> None:
        response = sendgrid_source("k", "marketing_lists", MagicMock(), _manager())
        assert response.primary_keys == ["id"]
        assert response.partition_mode is None
        assert response.partition_keys is None


class TestGetStatusCode:
    @pytest.mark.parametrize("status", [200, 401, 403, 404])
    def test_returns_status(self, status: int) -> None:
        session = MagicMock()
        session.get.return_value = _FakeResponse(status, {})
        with patch(f"{MODULE}.make_tracked_session", return_value=session):
            assert get_status_code("k", "/scopes") == status

    def test_returns_none_on_transport_error(self) -> None:
        session = MagicMock()
        session.get.side_effect = Exception("boom")
        with patch(f"{MODULE}.make_tracked_session", return_value=session):
            assert get_status_code("k", "/scopes") is None
