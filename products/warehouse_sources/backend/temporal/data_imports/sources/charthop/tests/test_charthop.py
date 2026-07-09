from datetime import UTC, date, datetime
from typing import Any, Optional

import pytest
from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.charthop.charthop import (
    CHARTHOP_BASE_URL,
    PAGE_SIZE,
    ChartHopAPIError,
    ChartHopResumeConfig,
    _to_charthop_date,
    charthop_source,
    get_rows,
    resolve_org_id,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.charthop.settings import ENDPOINTS

SESSION_PATH = "products.warehouse_sources.backend.temporal.data_imports.sources.charthop.charthop.make_tracked_session"


class FakeResponse:
    def __init__(self, status_code: int = 200, json_data: Optional[dict[str, Any]] = None) -> None:
        self.status_code = status_code
        self._json = json_data if json_data is not None else {}
        self.text = str(self._json)
        self.headers: dict[str, str] = {}

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300

    def json(self) -> dict[str, Any]:
        return self._json

    def raise_for_status(self) -> None:
        if not self.ok:
            raise Exception(f"{self.status_code} Client Error")


class FakeSession:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[str] = []

    def get(self, url: str, headers: Any = None, timeout: Any = None):
        self.calls.append(url)
        return self._responses[0] if len(self._responses) == 1 else self._responses.pop(0)


def _manager(can_resume: bool = False, state: Optional[ChartHopResumeConfig] = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = can_resume
    manager.load_state.return_value = state
    return manager


class TestToChartHopDate:
    @parameterized.expand(
        [
            ("date", date(2026, 1, 15), "2026-01-15"),
            ("aware_datetime", datetime(2026, 1, 15, 12, 30, tzinfo=UTC), "2026-01-15"),
            ("naive_datetime", datetime(2026, 1, 15, 12, 30), "2026-01-15"),
            ("date_string", "2026-01-15", "2026-01-15"),
            ("datetime_string", "2026-01-15T12:30:00Z", "2026-01-15"),
            ("garbage_string", "not-a-date", None),
            ("non_date_type", 12345, None),
        ]
    )
    def test_coercion(self, _name: str, value: Any, expected: Optional[str]) -> None:
        assert _to_charthop_date(value) == expected

    def test_future_date_clamped_to_today(self) -> None:
        future = date.today().replace(year=date.today().year + 1)
        assert _to_charthop_date(future) == datetime.now(UTC).date().isoformat()


class TestGetRows:
    def test_paginates_forwarding_from_token(self) -> None:
        responses = [
            FakeResponse(json_data={"data": [{"id": "1"}], "next": "1"}),
            FakeResponse(json_data={"data": [{"id": "2"}]}),
        ]
        session = FakeSession(responses)
        manager = _manager()

        with mock.patch(SESSION_PATH, return_value=session):
            batches = list(get_rows("key", "org-1", "jobs", mock.MagicMock(), manager))

        assert batches == [[{"id": "1"}], [{"id": "2"}]]
        assert session.calls[0] == f"{CHARTHOP_BASE_URL}/v2/org/org-1/job?limit={PAGE_SIZE}"
        assert session.calls[1] == f"{CHARTHOP_BASE_URL}/v2/org/org-1/job?limit={PAGE_SIZE}&from=1"

    def test_org_id_is_encoded_as_single_path_segment(self) -> None:
        responses = [FakeResponse(json_data={"data": []})]
        session = FakeSession(responses)

        with mock.patch(SESSION_PATH, return_value=session):
            list(get_rows("key", "org/../evil?x=1", "jobs", mock.MagicMock(), _manager()))

        assert session.calls[0].startswith(f"{CHARTHOP_BASE_URL}/v2/org/org%2F..%2Fevil%3Fx%3D1/job?")

    def test_saves_state_after_yielding_each_page(self) -> None:
        responses = [
            FakeResponse(json_data={"data": [{"id": "1"}], "next": "1"}),
            FakeResponse(json_data={"data": [{"id": "2"}]}),
        ]
        manager = _manager()

        with mock.patch(SESSION_PATH, return_value=FakeSession(responses)):
            list(get_rows("key", "org-1", "jobs", mock.MagicMock(), manager))

        manager.save_state.assert_called_once_with(ChartHopResumeConfig(from_token="1", start_date=None))

    def test_resumes_from_saved_cursor_and_start_date(self) -> None:
        responses = [FakeResponse(json_data={"data": [{"id": "9"}]})]
        session = FakeSession(responses)
        manager = _manager(can_resume=True, state=ChartHopResumeConfig(from_token="8", start_date="2026-01-01"))

        with mock.patch(SESSION_PATH, return_value=session):
            batches = list(
                get_rows(
                    "key",
                    "org-1",
                    "changes",
                    mock.MagicMock(),
                    manager,
                    should_use_incremental_field=True,
                    # The saved window must win over the advanced watermark on resume.
                    db_incremental_field_last_value=date(2026, 2, 1),
                )
            )

        assert batches == [[{"id": "9"}]]
        assert "from=8" in session.calls[0]
        assert "date=2026-01-01" in session.calls[0]

    def test_incremental_date_filter_sent_on_every_page(self) -> None:
        responses = [
            FakeResponse(json_data={"data": [{"id": "1"}], "next": "1"}),
            FakeResponse(json_data={"data": [{"id": "2"}]}),
        ]
        session = FakeSession(responses)

        with mock.patch(SESSION_PATH, return_value=session):
            list(
                get_rows(
                    "key",
                    "org-1",
                    "changes",
                    mock.MagicMock(),
                    _manager(),
                    should_use_incremental_field=True,
                    db_incremental_field_last_value=date(2026, 1, 15),
                )
            )

        assert all("date=2026-01-15" in url for url in session.calls)

    def test_full_refresh_endpoint_never_sends_date_filter(self) -> None:
        responses = [FakeResponse(json_data={"data": [{"id": "1"}]})]
        session = FakeSession(responses)

        with mock.patch(SESSION_PATH, return_value=session):
            list(
                get_rows(
                    "key",
                    "org-1",
                    "jobs",
                    mock.MagicMock(),
                    _manager(),
                    should_use_incremental_field=True,
                    db_incremental_field_last_value=date(2026, 1, 15),
                )
            )

        assert "date=" not in session.calls[0]

    def test_persons_includes_ex_employees(self) -> None:
        responses = [FakeResponse(json_data={"data": []})]
        session = FakeSession(responses)

        with mock.patch(SESSION_PATH, return_value=session):
            batches = list(get_rows("key", "org-1", "persons", mock.MagicMock(), _manager()))

        assert batches == []
        assert "includeAll=true" in session.calls[0]

    @parameterized.expand([(401,), (403,)])
    def test_http_auth_errors_raise_matchable_api_error(self, status_code: int) -> None:
        with mock.patch(SESSION_PATH, return_value=FakeSession([FakeResponse(status_code=status_code)])):
            with pytest.raises(ChartHopAPIError) as exc:
                list(get_rows("key", "org-1", "jobs", mock.MagicMock(), _manager()))
        assert f"{status_code} Client Error" in str(exc.value)


class TestResolveOrgId:
    @parameterized.expand([("plain", "org-1"), ("padded", "  org-1  ")])
    def test_configured_org_id_skips_lookup(self, _name: str, configured: str) -> None:
        session = mock.MagicMock()
        with mock.patch(SESSION_PATH, return_value=session):
            assert resolve_org_id("key", configured) == "org-1"
        session.get.assert_not_called()

    def test_single_org_auto_detected(self) -> None:
        response = FakeResponse(json_data={"data": [{"id": "org-9"}]})
        with mock.patch(SESSION_PATH, return_value=FakeSession([response])):
            assert resolve_org_id("key", None) == "org-9"

    @parameterized.expand(
        [
            ("no_orgs", [], "has no access to any organization"),
            ("multiple_orgs", [{"id": "a"}, {"id": "b"}], "can access multiple organizations"),
        ]
    )
    def test_zero_or_multiple_orgs_raise(self, _name: str, orgs: list[dict[str, Any]], expected_message: str) -> None:
        response = FakeResponse(json_data={"data": orgs})
        with mock.patch(SESSION_PATH, return_value=FakeSession([response])):
            with pytest.raises(ChartHopAPIError) as exc:
                resolve_org_id("key", "")
        assert expected_message in str(exc.value)

    def test_auth_error_raises_matchable_api_error(self) -> None:
        with mock.patch(SESSION_PATH, return_value=FakeSession([FakeResponse(status_code=401)])):
            with pytest.raises(ChartHopAPIError) as exc:
                resolve_org_id("key", None)
        assert "401 Client Error" in str(exc.value)


class TestChartHopSource:
    def test_changes_partitioned_by_effective_date(self) -> None:
        response = charthop_source("key", "org-1", "changes", mock.MagicMock(), _manager())
        assert response.name == "changes"
        assert response.primary_keys == ["id"]
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["date"]

    def test_full_refresh_endpoint_is_unpartitioned(self) -> None:
        response = charthop_source("key", "org-1", "persons", mock.MagicMock(), _manager())
        assert response.partition_mode is None
        assert response.partition_keys is None

    def test_all_endpoints_buildable(self) -> None:
        for endpoint in ENDPOINTS:
            response = charthop_source("key", "org-1", endpoint, mock.MagicMock(), _manager())
            assert response.primary_keys == ["id"]
