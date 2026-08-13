from datetime import UTC, date, datetime
from typing import Any, cast

from unittest import mock

from parameterized import parameterized
from requests import Request

from products.warehouse_sources.backend.temporal.data_imports.sources.wasabi.settings import (
    DEFAULT_UTILIZATION_START_DATE,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.wasabi.wasabi import (
    WasabiDateWindowPaginator,
    WasabiResumeConfig,
    _start_date,
    validate_credentials,
    wasabi_source,
)

TODAY = date(2026, 7, 21)


class _FixedTodayPaginator(WasabiDateWindowPaginator):
    # Pin "today" so window math is deterministic in tests.
    @staticmethod
    def _today() -> date:
        return TODAY


def _fixed_today_paginator(start: date, window_days: int = 30) -> WasabiDateWindowPaginator:
    return _FixedTodayPaginator(start_date=start, window_days=window_days)


class _FakeResumableSourceManager:
    def __init__(self, state: WasabiResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[WasabiResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> WasabiResumeConfig | None:
        return self._state

    def save_state(self, state: WasabiResumeConfig) -> None:
        self.saved.append(state)


class TestWasabiDateWindowPaginator:
    def test_first_window_sets_from_and_to(self) -> None:
        paginator = _fixed_today_paginator(date(2024, 1, 1))
        request = Request(method="GET", url="https://partner.wasabisys.com/v1/utilizations", params={})
        paginator.init_request(request)
        assert request.params == {"from": "2024-01-01", "to": "2024-01-30"}

    def test_windows_advance_without_overlap(self) -> None:
        paginator = _fixed_today_paginator(date(2024, 1, 1))
        request = Request(method="GET", url="x", params={})
        paginator.init_request(request)
        paginator.update_state(mock.Mock())
        paginator.update_request(request)
        assert request.params == {"from": "2024-01-31", "to": "2024-02-29"}
        assert paginator.has_next_page is True

    def test_empty_window_still_advances(self) -> None:
        paginator = _fixed_today_paginator(date(2024, 1, 1))
        request = Request(method="GET", url="x", params={})
        paginator.init_request(request)
        # No rows in the response — the walk must still move to the next window.
        paginator.update_state(mock.Mock(), data=[])
        assert paginator.has_next_page is True

    def test_terminates_once_window_reaches_today(self) -> None:
        paginator = _fixed_today_paginator(TODAY)
        request = Request(method="GET", url="x", params={})
        paginator.init_request(request)
        assert request.params == {"from": "2026-07-21", "to": "2026-07-21"}
        paginator.update_state(mock.Mock())
        assert paginator.has_next_page is False
        assert paginator.get_resume_state() is None

    def test_final_window_is_clamped_to_today(self) -> None:
        paginator = _fixed_today_paginator(date(2026, 7, 10))
        request = Request(method="GET", url="x", params={})
        paginator.init_request(request)
        assert request.params == {"from": "2026-07-10", "to": "2026-07-21"}
        paginator.update_state(mock.Mock())
        assert paginator.has_next_page is False

    def test_resume_state_points_at_next_window(self) -> None:
        paginator = _fixed_today_paginator(date(2024, 1, 1))
        request = Request(method="GET", url="x", params={})
        paginator.init_request(request)
        paginator.update_state(mock.Mock())
        paginator.update_request(request)
        assert paginator.get_resume_state() == {"next_from": "2024-01-31"}

    def test_set_resume_state_seeds_first_request(self) -> None:
        paginator = _fixed_today_paginator(date(2024, 1, 1))
        paginator.set_resume_state({"next_from": "2025-06-01"})
        request = Request(method="GET", url="x", params={})
        paginator.init_request(request)
        assert request.params == {"from": "2025-06-01", "to": "2025-06-30"}

    def test_future_start_date_is_clamped_to_today(self) -> None:
        paginator = _fixed_today_paginator(date(2024, 1, 1))
        paginator.set_resume_state({"next_from": "2027-01-01"})
        request = Request(method="GET", url="x", params={})
        paginator.init_request(request)
        assert request.params == {"from": "2026-07-21", "to": "2026-07-21"}


class TestStartDate:
    @parameterized.expand(
        [
            ("iso_string", True, "2024-03-05T00:00:00Z", date(2024, 3, 5)),
            ("datetime", True, datetime(2024, 3, 5, 12, 30, tzinfo=UTC), date(2024, 3, 5)),
            ("date", True, date(2024, 3, 5), date(2024, 3, 5)),
            ("first_sync", True, None, date.fromisoformat(DEFAULT_UTILIZATION_START_DATE)),
            ("full_refresh", False, datetime(2024, 3, 5), date.fromisoformat(DEFAULT_UTILIZATION_START_DATE)),
            ("unparseable_string", True, "not-a-date", date.fromisoformat(DEFAULT_UTILIZATION_START_DATE)),
        ]
    )
    def test_start_date(self, _name: str, should_use_incremental: bool, last_value: Any, expected: date) -> None:
        assert _start_date(should_use_incremental, last_value) == expected


class TestValidateCredentials:
    @parameterized.expand(
        [
            (200, True),
            (401, False),
            (403, False),
            (500, False),
        ]
    )
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.wasabi.wasabi.make_tracked_session")
    def test_status_code_mapping(self, status_code: int, expected_valid: bool, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.return_value = mock.Mock(status_code=status_code)
        is_valid, message = validate_credentials("wasabi-key")
        assert is_valid is expected_valid
        if expected_valid:
            assert message is None
        else:
            assert message

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.wasabi.wasabi.make_tracked_session")
    def test_probes_accounts_endpoint_with_raw_key_header(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.return_value = mock.Mock(status_code=200)
        validate_credentials("wasabi-key")
        args, kwargs = mock_session.return_value.get.call_args
        assert args[0] == "https://partner.wasabisys.com/v1/accounts"
        # WACA takes the raw key as the Authorization value, not a Bearer token.
        assert kwargs["headers"]["Authorization"] == "wasabi-key"


class TestWasabiSourceTransport:
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.wasabi.wasabi.rest_api_resource")
    def test_accounts_full_refresh(self, mock_rest_api_resource: mock.MagicMock) -> None:
        manager = _FakeResumableSourceManager()
        response = wasabi_source(
            api_key="key",
            endpoint="accounts",
            team_id=1,
            job_id="job-1",
            resumable_source_manager=cast(Any, manager),
        )

        assert response.name == "accounts"
        assert response.primary_keys == ["AcctNum"]
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["CreateTime"]

        config = mock_rest_api_resource.call_args.args[0]
        resource = config["resources"][0]
        assert resource["write_disposition"] == "replace"
        assert resource["endpoint"]["path"] == "/v1/accounts"
        # WACA list endpoints return a bare JSON array.
        assert resource["endpoint"]["data_selector"] == "$"
        assert config["client"]["base_url"] == "https://partner.wasabisys.com"
        assert config["client"]["auth"] == {
            "type": "api_key",
            "name": "Authorization",
            "api_key": "key",
            "location": "header",
        }

    @parameterized.expand(
        [
            ("utilizations", ["UtilizationNum"], "/v1/utilizations"),
            ("bucket_utilizations", ["BucketUtilizationNum"], "/v1/utilizations/buckets"),
        ]
    )
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.wasabi.wasabi.rest_api_resource")
    def test_utilization_endpoints_incremental_merge(
        self,
        endpoint: str,
        expected_primary_keys: list[str],
        expected_path: str,
        mock_rest_api_resource: mock.MagicMock,
    ) -> None:
        manager = _FakeResumableSourceManager()
        response = wasabi_source(
            api_key="key",
            endpoint=endpoint,
            team_id=1,
            job_id="job-1",
            resumable_source_manager=cast(Any, manager),
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 3, 5, tzinfo=UTC),
        )

        assert response.name == endpoint
        assert response.primary_keys == expected_primary_keys
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["StartTime"]
        assert response.sort_mode == "asc"

        config = mock_rest_api_resource.call_args.args[0]
        resource = config["resources"][0]
        assert resource["write_disposition"] == {"disposition": "merge", "strategy": "upsert"}
        assert resource["endpoint"]["path"] == expected_path
        paginator = resource["endpoint"]["paginator"]
        assert isinstance(paginator, WasabiDateWindowPaginator)
        # The window walk starts at the incremental watermark date.
        assert paginator._window_start == date(2024, 3, 5)

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.wasabi.wasabi.rest_api_resource")
    def test_utilizations_full_refresh_starts_at_default_date(self, mock_rest_api_resource: mock.MagicMock) -> None:
        manager = _FakeResumableSourceManager()
        wasabi_source(
            api_key="key",
            endpoint="utilizations",
            team_id=1,
            job_id="job-1",
            resumable_source_manager=cast(Any, manager),
        )

        config = mock_rest_api_resource.call_args.args[0]
        resource = config["resources"][0]
        assert resource["write_disposition"] == "replace"
        paginator = resource["endpoint"]["paginator"]
        assert paginator._window_start == date.fromisoformat(DEFAULT_UTILIZATION_START_DATE)

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.wasabi.wasabi.rest_api_resource")
    def test_resume_state_is_seeded_into_paginator(self, mock_rest_api_resource: mock.MagicMock) -> None:
        manager = _FakeResumableSourceManager(WasabiResumeConfig(paginator_state={"next_from": "2025-06-01"}))
        wasabi_source(
            api_key="key",
            endpoint="utilizations",
            team_id=1,
            job_id="job-1",
            resumable_source_manager=cast(Any, manager),
        )

        kwargs = mock_rest_api_resource.call_args.kwargs
        assert kwargs["initial_paginator_state"] == {"next_from": "2025-06-01"}

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.wasabi.wasabi.rest_api_resource")
    def test_resume_hook_saves_state_after_batches(self, mock_rest_api_resource: mock.MagicMock) -> None:
        manager = _FakeResumableSourceManager()
        wasabi_source(
            api_key="key",
            endpoint="utilizations",
            team_id=1,
            job_id="job-1",
            resumable_source_manager=cast(Any, manager),
        )

        resume_hook = mock_rest_api_resource.call_args.kwargs["resume_hook"]
        resume_hook({"next_from": "2024-02-01"})
        # A None state means the walk completed — nothing to persist.
        resume_hook(None)

        assert [saved.paginator_state for saved in manager.saved] == [{"next_from": "2024-02-01"}]

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.wasabi.wasabi.rest_api_resources")
    def test_sub_account_invoices_fans_out_from_accounts(self, mock_rest_api_resources: mock.MagicMock) -> None:
        parent = mock.Mock()
        parent.name = "accounts"
        child = mock.Mock()
        child.name = "sub_account_invoices"
        mock_rest_api_resources.return_value = [parent, child]
        manager = _FakeResumableSourceManager()

        response = wasabi_source(
            api_key="key",
            endpoint="sub_account_invoices",
            team_id=1,
            job_id="job-1",
            resumable_source_manager=cast(Any, manager),
        )

        assert response.name == "sub_account_invoices"
        # Wasabi doesn't document SubInvoiceNum's uniqueness scope, so the parent
        # account number stays in the key to keep it unique table-wide.
        assert response.primary_keys == ["AcctNum", "SubInvoiceNum"]
        assert response.items() is child

        config = mock_rest_api_resources.call_args.args[0]
        parent_resource, child_resource = config["resources"]
        assert parent_resource["name"] == "accounts"
        assert child_resource["endpoint"]["path"] == "/v1/accounts/{acct_num}/invoices"
        assert child_resource["endpoint"]["params"]["acct_num"] == {
            "type": "resolve",
            "resource": "accounts",
            "field": "AcctNum",
        }
        assert child_resource["write_disposition"] == "replace"
