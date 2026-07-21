from datetime import UTC, date, datetime
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

from parameterized import parameterized
from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.appstack.appstack import (
    AppstackResumeConfig,
    _export_window_start,
    _to_unix_seconds,
    appstack_source,
    get_resource,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.appstack.settings import PAGE_SIZE
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager


class TestToUnixSeconds:
    @parameterized.expand(
        [
            ("aware_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), 1772593094),
            ("naive_datetime_assumed_utc", datetime(2026, 3, 4, 2, 58, 14), 1772593094),
            ("date_value", date(2026, 3, 4), 1772582400),
            ("epoch_int", 1772593094, 1772593094),
            ("epoch_float", 1772593094.9, 1772593094),
            ("iso_string", "2026-03-04T02:58:14+00:00", 1772593094),
            ("iso_string_z_suffix", "2026-03-04T02:58:14Z", 1772593094),
            ("epoch_string", "1772593094", 1772593094),
            ("garbage_string", "not-a-timestamp", 0),
            ("negative_epoch_clamped", -5, 0),
        ]
    )
    def test_conversion(self, _label: str, value: Any, expected: int) -> None:
        assert _to_unix_seconds(value) == expected


class TestExportWindowStart:
    @parameterized.expand(
        [
            # Full refresh must always export the full history regardless of any stored watermark.
            ("full_refresh_ignores_watermark", False, datetime(2026, 3, 4, tzinfo=UTC), 0),
            # First incremental sync has no watermark yet and also backfills everything.
            ("incremental_without_watermark", True, None, 0),
            ("incremental_with_watermark", True, datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), 1772593094),
        ]
    )
    def test_window_start(self, _label: str, incremental: bool, last_value: Any, expected: int) -> None:
        assert _export_window_start(incremental, last_value) == expected


class TestGetResource:
    @staticmethod
    def _params(resource: Any) -> dict[str, Any]:
        return cast(dict[str, Any], cast(dict[str, Any], resource["endpoint"])["params"])

    def test_full_refresh_resource_shape(self) -> None:
        resource = get_resource("events", should_use_incremental_field=False, window_start=0)
        endpoint = cast(dict[str, Any], resource["endpoint"])

        assert resource["name"] == "events"
        assert resource["write_disposition"] == "replace"
        assert resource["table_format"] == "delta"
        assert endpoint["path"] == "/export"
        assert endpoint["data_selector"] == "data"
        # `timestamp` is required by the API even on a full refresh.
        assert self._params(resource)["timestamp"] == 0

    def test_incremental_resource_merges_and_windows(self) -> None:
        resource = get_resource("events", should_use_incremental_field=True, window_start=1772593094)

        assert resource["write_disposition"] == {"disposition": "merge", "strategy": "upsert"}
        assert self._params(resource)["timestamp"] == 1772593094

    def test_event_time_parsed_as_timestamp(self) -> None:
        # Without this hint event_time stays an ISO string and the incremental watermark and
        # datetime partitioning silently break.
        resource = get_resource("events", should_use_incremental_field=True, window_start=0)
        columns = cast(dict[str, Any], resource["columns"])
        assert columns["event_time"]["data_type"] == "timestamp"


class TestAppstackSource:
    def _manager(self, *, can_resume: bool, state: AppstackResumeConfig | None = None) -> MagicMock:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = can_resume
        manager.load_state.return_value = state
        return manager

    def _call(self, manager: MagicMock, **kwargs: Any) -> Any:
        defaults: dict[str, Any] = {
            "api_key": "key",
            "endpoint": "events",
            "team_id": 1,
            "job_id": "job",
            "resumable_source_manager": manager,
            "db_incremental_field_last_value": None,
            "should_use_incremental_field": False,
        }
        defaults.update(kwargs)
        return appstack_source(**defaults)

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.appstack.appstack.rest_api_resource")
    def test_source_response_fields(self, mock_rest: MagicMock) -> None:
        mock_resource = MagicMock()
        mock_resource.name = "events"
        mock_resource.column_hints = {"event_time": "timestamp"}
        mock_rest.return_value = mock_resource

        response = self._call(self._manager(can_resume=False))

        assert response.name == "events"
        assert response.primary_keys == ["event_id"]
        # Documented: exports are ordered by event_time ascending.
        assert response.sort_mode == "asc"
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["event_time"]

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.appstack.appstack.rest_api_resource")
    def test_paginator_never_trusts_total_count(self, mock_rest: MagicMock) -> None:
        # Appstack's `total_count` counts the current page, not the whole window; a paginator
        # reading it as a grand total would stop after the first page and silently truncate.
        mock_rest.return_value = MagicMock(name="events", column_hints=None)

        self._call(self._manager(can_resume=False))

        paginator = mock_rest.call_args.args[0]["client"]["paginator"]
        assert paginator.total_path is None
        assert paginator.limit == PAGE_SIZE

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.appstack.appstack.make_tracked_session")
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.appstack.appstack.rest_api_resource")
    def test_client_session_disables_sample_capture(self, mock_rest: MagicMock, mock_session: MagicMock) -> None:
        # Export rows carry device/user identifiers the sample scrubbers can't recognise; the client
        # must run on a capture=False session so response bodies stay out of shared sample storage.
        mock_rest.return_value = MagicMock(name="events", column_hints=None)

        self._call(self._manager(can_resume=False))

        assert mock_session.call_args.kwargs["capture"] is False
        assert mock_rest.call_args.args[0]["client"]["session"] is mock_session.return_value

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.appstack.appstack.rest_api_resource")
    def test_resume_replays_pinned_window_at_saved_offset(self, mock_rest: MagicMock) -> None:
        # Offsets are positions within one export window: a resumed attempt must reuse the saved
        # window's `timestamp`, not re-derive it from a watermark that advanced mid-walk.
        mock_rest.return_value = MagicMock(name="events", column_hints=None)
        manager = self._manager(can_resume=True, state=AppstackResumeConfig(offset=30000, window_start=1772593094))

        self._call(
            manager,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 6, 1, tzinfo=UTC),
        )

        config = mock_rest.call_args.args[0]
        params = config["resources"][0]["endpoint"]["params"]
        assert params["timestamp"] == 1772593094
        assert mock_rest.call_args.kwargs["initial_paginator_state"] == {"offset": 30000}

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.appstack.appstack.rest_api_resource")
    def test_resume_hook_saves_offset_with_window(self, mock_rest: MagicMock) -> None:
        mock_rest.return_value = MagicMock(name="events", column_hints=None)
        manager = self._manager(can_resume=False)

        self._call(
            manager,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
        )

        resume_hook = mock_rest.call_args.kwargs["resume_hook"]

        # A page with a next offset persists the checkpoint together with its window.
        resume_hook({"offset": 20000})
        manager.save_state.assert_called_once_with(AppstackResumeConfig(offset=20000, window_start=1772593094))

        # A terminal page (no resume state) saves nothing.
        manager.save_state.reset_mock()
        resume_hook(None)
        manager.save_state.assert_not_called()


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("unauthorized", 401, False), ("forbidden", 403, False)])
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.appstack.appstack.make_tracked_session")
    def test_status_mapping(self, _label: str, status_code: int, expected: bool, mock_session: MagicMock) -> None:
        response = MagicMock()
        response.status_code = status_code
        mock_session.return_value.get.return_value = response

        assert validate_credentials("key") is expected

    @parameterized.expand([("rate_limited", 429), ("server_error", 503)])
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.appstack.appstack.make_tracked_session")
    def test_transient_errors_raise(self, _label: str, status_code: int, mock_session: MagicMock) -> None:
        # Transient/unexpected statuses must not be reported as an invalid API key — they raise.
        response = MagicMock()
        response.status_code = status_code
        response.raise_for_status.side_effect = HTTPError
        mock_session.return_value.get.return_value = response

        with pytest.raises(HTTPError):
            validate_credentials("key")

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.appstack.appstack.make_tracked_session")
    def test_sends_raw_key_in_authorization_header(self, mock_session: MagicMock) -> None:
        # Appstack expects the bare key — a Bearer prefix breaks auth for every sync.
        response = MagicMock()
        response.status_code = 200
        mock_session.return_value.get.return_value = response

        validate_credentials("the-key")

        headers = mock_session.return_value.get.call_args.kwargs["headers"]
        assert headers["Authorization"] == "the-key"

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.appstack.appstack.make_tracked_session")
    def test_probe_disables_sample_capture(self, mock_session: MagicMock) -> None:
        # The probe hits the same export endpoint, so its response body must not be captured either.
        response = MagicMock()
        response.status_code = 200
        mock_session.return_value.get.return_value = response

        validate_credentials("the-key")

        assert mock_session.call_args.kwargs["capture"] is False
