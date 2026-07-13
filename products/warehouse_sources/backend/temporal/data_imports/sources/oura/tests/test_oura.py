from datetime import UTC, date, datetime
from typing import Any

from freezegun import freeze_time
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.oura import oura
from products.warehouse_sources.backend.temporal.data_imports.sources.oura.oura import (
    DEFAULT_START_DATE,
    OuraResumeConfig,
    _build_initial_params,
    _build_url,
    _clamp_date_to_today,
    _clamp_datetime_to_now,
    _format_date,
    _format_datetime,
    get_rows,
    oura_source,
    probe_endpoint,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.oura.settings import OURA_ENDPOINTS


class _FakeResumableManager:
    def __init__(self, state: OuraResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[OuraResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> OuraResumeConfig | None:
        return self._state

    def save_state(self, data: OuraResumeConfig) -> None:
        self.saved.append(data)


class TestFormatHelpers:
    @parameterized.expand(
        [
            ("datetime", datetime(2021, 5, 1, 12, 30, tzinfo=UTC), "2021-05-01"),
            ("date", date(2021, 5, 1), "2021-05-01"),
            ("iso_string", "2021-05-01T00:00:00+00:00", "2021-05-01"),
        ]
    )
    def test_format_date(self, _name: str, value: Any, expected: str) -> None:
        assert _format_date(value) == expected

    @parameterized.expand(
        [
            ("aware_datetime", datetime(2021, 5, 1, 12, 0, tzinfo=UTC), "2021-05-01T12:00:00+00:00"),
            ("naive_datetime_assumed_utc", datetime(2021, 5, 1, 12, 0), "2021-05-01T12:00:00+00:00"),
            ("date_to_midnight", date(2021, 5, 1), "2021-05-01T00:00:00+00:00"),
        ]
    )
    def test_format_datetime(self, _name: str, value: Any, expected: str) -> None:
        assert _format_datetime(value) == expected


class TestClamp:
    @freeze_time("2026-06-15T12:00:00Z")
    def test_future_date_clamped_to_today(self) -> None:
        assert _clamp_date_to_today("2099-01-01") == "2026-06-15"

    @freeze_time("2026-06-15T12:00:00Z")
    def test_past_date_unchanged(self) -> None:
        assert _clamp_date_to_today("2021-05-01") == "2021-05-01"

    @freeze_time("2026-06-15T12:00:00Z")
    def test_future_datetime_clamped_to_now(self) -> None:
        assert _clamp_datetime_to_now("2099-01-01T00:00:00+00:00") == "2026-06-15T12:00:00+00:00"


class TestBuildInitialParams:
    def test_date_endpoint_first_sync_uses_default_start(self) -> None:
        params = _build_initial_params(
            OURA_ENDPOINTS["daily_sleep"], should_use_incremental_field=False, db_incremental_field_last_value=None
        )
        assert params == {"start_date": DEFAULT_START_DATE}

    def test_date_endpoint_incremental_uses_cursor(self) -> None:
        params = _build_initial_params(
            OURA_ENDPOINTS["daily_sleep"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=date(2021, 5, 1),
        )
        assert params == {"start_date": "2021-05-01"}

    def test_datetime_endpoint_incremental_uses_start_datetime(self) -> None:
        params = _build_initial_params(
            OURA_ENDPOINTS["heartrate"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2021, 5, 1, 12, 0, tzinfo=UTC),
        )
        assert params == {"start_datetime": "2021-05-01T12:00:00+00:00"}

    def test_datetime_endpoint_first_sync_uses_default(self) -> None:
        params = _build_initial_params(
            OURA_ENDPOINTS["heartrate"], should_use_incremental_field=False, db_incremental_field_last_value=None
        )
        assert params == {"start_datetime": f"{DEFAULT_START_DATE}T00:00:00+00:00"}

    @parameterized.expand([("personal_info",), ("ring_configuration",)])
    def test_full_refresh_endpoints_send_no_date_params(self, endpoint: str) -> None:
        params = _build_initial_params(
            OURA_ENDPOINTS[endpoint], should_use_incremental_field=False, db_incremental_field_last_value=None
        )
        assert params == {}

    @freeze_time("2026-06-15T12:00:00Z")
    def test_future_cursor_is_clamped(self) -> None:
        # A future-dated record could push the cursor past today; Oura 400s when start_date > end_date.
        params = _build_initial_params(
            OURA_ENDPOINTS["daily_sleep"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=date(2099, 1, 1),
        )
        assert params == {"start_date": "2026-06-15"}


class TestBuildUrl:
    def test_no_params(self) -> None:
        assert _build_url("/usercollection/personal_info", {}) == (
            "https://api.ouraring.com/v2/usercollection/personal_info"
        )

    def test_with_params(self) -> None:
        url = _build_url("/usercollection/daily_sleep", {"start_date": "2021-05-01", "next_token": "abc"})
        assert url == "https://api.ouraring.com/v2/usercollection/daily_sleep?start_date=2021-05-01&next_token=abc"


class TestGetRows:
    @staticmethod
    def _collect(manager: _FakeResumableManager, pages: dict[str, Any], **kwargs: Any) -> list[list[dict]]:
        def fake_fetch(session: Any, url: str, headers: dict[str, str], logger: Any) -> dict:
            return pages[url]

        with patch.object(oura, "_fetch_page", fake_fetch):
            return list(
                get_rows(
                    token="tok",
                    endpoint=kwargs.pop("endpoint", "daily_sleep"),
                    logger=MagicMock(),
                    resumable_source_manager=manager,  # type: ignore[arg-type]
                    **kwargs,
                )
            )

    def test_follows_next_token_pagination(self) -> None:
        base = "https://api.ouraring.com/v2/usercollection/daily_sleep"
        pages = {
            f"{base}?start_date={DEFAULT_START_DATE}": {
                "data": [{"id": "a"}, {"id": "b"}],
                "next_token": "tok1",
            },
            f"{base}?start_date={DEFAULT_START_DATE}&next_token=tok1": {
                "data": [{"id": "c"}],
                "next_token": None,
            },
        }
        manager = _FakeResumableManager()
        batches = self._collect(manager, pages)
        assert batches == [[{"id": "a"}, {"id": "b"}], [{"id": "c"}]]

    def test_saves_state_after_each_yielded_page(self) -> None:
        base = "https://api.ouraring.com/v2/usercollection/daily_sleep"
        pages = {
            f"{base}?start_date={DEFAULT_START_DATE}": {"data": [{"id": "a"}], "next_token": "tok1"},
            f"{base}?start_date={DEFAULT_START_DATE}&next_token=tok1": {"data": [{"id": "b"}], "next_token": None},
        }
        manager = _FakeResumableManager()
        self._collect(manager, pages)
        # State saved only after the first page (which had a next_token); the terminal page saves nothing.
        assert manager.saved == [OuraResumeConfig(next_token="tok1")]

    def test_resumes_from_saved_next_token(self) -> None:
        base = "https://api.ouraring.com/v2/usercollection/daily_sleep"
        resume_url = f"{base}?start_date={DEFAULT_START_DATE}&next_token=saved"
        pages = {resume_url: {"data": [{"id": "z"}], "next_token": None}}
        manager = _FakeResumableManager(OuraResumeConfig(next_token="saved"))
        batches = self._collect(manager, pages)
        assert batches == [[{"id": "z"}]]

    def test_personal_info_yields_single_document(self) -> None:
        url = "https://api.ouraring.com/v2/usercollection/personal_info"
        pages = {url: {"id": "u1", "age": 30, "email": "a@b.com"}}
        manager = _FakeResumableManager()
        batches = self._collect(manager, pages, endpoint="personal_info")
        assert batches == [[{"id": "u1", "age": 30, "email": "a@b.com"}]]
        assert manager.saved == []

    def test_empty_page_is_not_yielded(self) -> None:
        base = "https://api.ouraring.com/v2/usercollection/daily_sleep"
        pages: dict[str, Any] = {f"{base}?start_date={DEFAULT_START_DATE}": {"data": [], "next_token": None}}
        batches = self._collect(_FakeResumableManager(), pages)
        assert batches == []


class TestProbeEndpoint:
    @parameterized.expand([(200,), (401,), (403,), (404,)])
    def test_returns_status_code(self, status: int) -> None:
        response = MagicMock(status_code=status)
        session = MagicMock()
        session.get.return_value = response
        with patch.object(oura, "make_tracked_session", return_value=session):
            assert probe_endpoint("tok", "/usercollection/personal_info") == status

    def test_transport_failure_returns_minus_one(self) -> None:
        session = MagicMock()
        session.get.side_effect = Exception("boom")
        with patch.object(oura, "make_tracked_session", return_value=session):
            assert probe_endpoint("tok", "/usercollection/personal_info") == -1


class TestOuraSourceResponse:
    def test_daily_endpoint_partitions_on_day(self) -> None:
        response = oura_source("tok", "daily_sleep", MagicMock(), MagicMock())
        assert response.name == "daily_sleep"
        assert response.primary_keys == ["id"]
        assert response.partition_keys == ["day"]
        assert response.partition_mode == "datetime"
        assert response.partition_format == "month"
        assert response.sort_mode == "asc"

    def test_heartrate_uses_composite_key_and_timestamp_partition(self) -> None:
        response = oura_source("tok", "heartrate", MagicMock(), MagicMock())
        assert response.primary_keys == ["timestamp", "source"]
        assert response.partition_keys == ["timestamp"]

    def test_enhanced_tag_partitions_on_start_day(self) -> None:
        response = oura_source("tok", "enhanced_tag", MagicMock(), MagicMock())
        assert response.partition_keys == ["start_day"]

    @parameterized.expand([("personal_info",), ("ring_configuration",)])
    def test_full_refresh_endpoints_are_unpartitioned(self, endpoint: str) -> None:
        response = oura_source("tok", endpoint, MagicMock(), MagicMock())
        assert response.partition_keys is None
        assert response.partition_mode is None
