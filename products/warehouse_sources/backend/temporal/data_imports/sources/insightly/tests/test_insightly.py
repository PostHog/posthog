from typing import Any

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.insightly.insightly import (
    PAGE_SIZE,
    InsightlyResumeConfig,
    _build_params,
    _build_url,
    _format_updated_after,
    base_url,
    get_rows,
    insightly_source,
    normalize_pod,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.insightly.settings import INSIGHTLY_ENDPOINTS


class TestNormalizePod:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("na1", "na1"),
            ("NA1", "na1"),
            ("  eu1  ", "eu1"),
            ("https://api.na1.insightly.com/v3.1", "na1"),
            ("https://api.aps1.insightly.com/v3.1/", "aps1"),
            ("api.eu2.insightly.com", "eu2"),
        ],
    )
    def test_normalizes_valid_pods(self, raw: str, expected: str) -> None:
        assert normalize_pod(raw) == expected

    @pytest.mark.parametrize(
        "raw",
        [
            "",
            "na 1",
            "evil.com",
            "na1.evil.com",
            "http://169.254.169.254",
            "na_1",
        ],
    )
    def test_rejects_invalid_pods(self, raw: str) -> None:
        with pytest.raises(ValueError):
            normalize_pod(raw)

    def test_base_url_is_pinned_to_insightly(self) -> None:
        assert base_url("na1") == "https://api.na1.insightly.com/v3.1"
        assert base_url("https://api.EU1.insightly.com/v3.1") == "https://api.eu1.insightly.com/v3.1"


class TestFormatUpdatedAfter:
    def test_formats_datetime_with_trailing_z(self) -> None:
        from datetime import UTC, datetime

        assert _format_updated_after(datetime(2018, 4, 9, 16, 58, 14, tzinfo=UTC)) == "2018-04-09T16:58:14Z"

    def test_naive_datetime_treated_as_utc(self) -> None:
        from datetime import datetime

        assert _format_updated_after(datetime(2020, 1, 2, 3, 4, 5)) == "2020-01-02T03:04:05Z"

    def test_date_formats_at_midnight(self) -> None:
        from datetime import date

        assert _format_updated_after(date(2021, 6, 7)) == "2021-06-07T00:00:00Z"

    def test_string_passes_through(self) -> None:
        assert _format_updated_after("2022-03-04T05:06:07Z") == "2022-03-04T05:06:07Z"


class TestBuildParams:
    def test_adds_updated_after_only_for_incremental_endpoint_with_value(self) -> None:
        from datetime import UTC, datetime

        params = _build_params(
            INSIGHTLY_ENDPOINTS["Contacts"],
            skip=0,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2020, 1, 1, tzinfo=UTC),
        )
        assert params == {"top": PAGE_SIZE, "skip": 0, "updated_after_utc": "2020-01-01T00:00:00Z"}

    def test_no_updated_after_without_value(self) -> None:
        params = _build_params(
            INSIGHTLY_ENDPOINTS["Contacts"],
            skip=500,
            should_use_incremental_field=True,
            db_incremental_field_last_value=None,
        )
        assert params == {"top": PAGE_SIZE, "skip": 500}

    def test_full_refresh_endpoint_never_filters(self) -> None:
        from datetime import UTC, datetime

        # Users is full-refresh only; even with an incremental value it must not send updated_after_utc.
        params = _build_params(
            INSIGHTLY_ENDPOINTS["Users"],
            skip=0,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2020, 1, 1, tzinfo=UTC),
        )
        assert params == {"top": PAGE_SIZE, "skip": 0}


class TestValidateCredentials:
    @pytest.mark.parametrize("status_code", [200, 401, 403, 500])
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.insightly.insightly.make_tracked_session"
    )
    def test_returns_status_code(self, mock_session: mock.MagicMock, status_code: int) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status_code)
        assert validate_credentials("na1", "key", "/Contacts") == status_code
        called_url = mock_session.return_value.get.call_args.args[0]
        assert called_url == "https://api.na1.insightly.com/v3.1/Contacts?top=1"
        # The key is masked in logged URLs and captured samples.
        assert mock_session.call_args.kwargs["redact_values"] == ("key",)

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.insightly.insightly.make_tracked_session"
    )
    def test_returns_none_on_transport_error(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("na1", "key") is None

    def test_propagates_invalid_pod(self) -> None:
        with pytest.raises(ValueError):
            validate_credentials("evil.com", "key")


class TestGetRows:
    def _manager(self, resume_state: InsightlyResumeConfig | None = None) -> mock.MagicMock:
        manager = mock.MagicMock()
        manager.can_resume.return_value = resume_state is not None
        manager.load_state.return_value = resume_state
        return manager

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.insightly.insightly.make_tracked_session"
    )
    def test_paginates_offset_and_saves_state_after_yield(self, mock_session: mock.MagicMock) -> None:
        # A full page forces a second request; the short second page ends pagination.
        full_page = mock.MagicMock(status_code=200, ok=True)
        full_page.json.return_value = [{"CONTACT_ID": i} for i in range(PAGE_SIZE)]
        last_page = mock.MagicMock(status_code=200, ok=True)
        last_page.json.return_value = [{"CONTACT_ID": 9999}]
        mock_session.return_value.get.side_effect = [full_page, last_page]

        manager = self._manager()
        batches = list(get_rows("na1", "key", "Contacts", mock.MagicMock(), manager))

        assert len(batches) == 2
        assert batches[1] == [{"CONTACT_ID": 9999}]
        # Two page fetches at skip=0 then skip=PAGE_SIZE.
        urls = [call.args[0] for call in mock_session.return_value.get.call_args_list]
        assert urls[0].endswith(f"top={PAGE_SIZE}&skip=0")
        assert urls[1].endswith(f"top={PAGE_SIZE}&skip={PAGE_SIZE}")
        # State saved once, after the first (full) page, pointing at the next offset.
        manager.save_state.assert_called_once_with(InsightlyResumeConfig(skip=PAGE_SIZE))

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.insightly.insightly.make_tracked_session"
    )
    def test_single_short_page_does_not_save_state(self, mock_session: mock.MagicMock) -> None:
        page = mock.MagicMock(status_code=200, ok=True)
        page.json.return_value = [{"CONTACT_ID": 1}, {"CONTACT_ID": 2}]
        mock_session.return_value.get.return_value = page

        manager = self._manager()
        batches = list(get_rows("na1", "key", "Contacts", mock.MagicMock(), manager))

        assert batches == [[{"CONTACT_ID": 1}, {"CONTACT_ID": 2}]]
        manager.save_state.assert_not_called()

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.insightly.insightly.make_tracked_session"
    )
    def test_resumes_from_saved_offset(self, mock_session: mock.MagicMock) -> None:
        page = mock.MagicMock(status_code=200, ok=True)
        page.json.return_value = [{"CONTACT_ID": 7}]
        mock_session.return_value.get.return_value = page

        manager = self._manager(InsightlyResumeConfig(skip=1000))
        batches = list(get_rows("na1", "key", "Contacts", mock.MagicMock(), manager))

        assert batches == [[{"CONTACT_ID": 7}]]
        assert mock_session.return_value.get.call_args.args[0].endswith(f"top={PAGE_SIZE}&skip=1000")

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.insightly.insightly.make_tracked_session"
    )
    def test_incremental_filter_applied_on_every_page(self, mock_session: mock.MagicMock) -> None:
        from datetime import UTC, datetime

        full_page = mock.MagicMock(status_code=200, ok=True)
        full_page.json.return_value = [{"CONTACT_ID": i} for i in range(PAGE_SIZE)]
        last_page = mock.MagicMock(status_code=200, ok=True)
        last_page.json.return_value = []
        mock_session.return_value.get.side_effect = [full_page, last_page]

        list(
            get_rows(
                "na1",
                "key",
                "Contacts",
                mock.MagicMock(),
                self._manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2020, 1, 1, tzinfo=UTC),
            )
        )
        urls = [call.args[0] for call in mock_session.return_value.get.call_args_list]
        # The `updated_after_utc` filter is present on both the first and the second page.
        assert all("updated_after_utc=2020-01-01T00%3A00%3A00Z" in url for url in urls)

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.insightly.insightly.make_tracked_session"
    )
    def test_raises_on_non_retryable_error(self, mock_session: mock.MagicMock) -> None:
        page = mock.MagicMock(status_code=401, ok=False, text="unauthorized")
        page.raise_for_status.side_effect = Exception("401 Client Error")
        mock_session.return_value.get.return_value = page

        with pytest.raises(Exception, match="401 Client Error"):
            list(get_rows("na1", "key", "Contacts", mock.MagicMock(), self._manager()))

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.insightly.insightly.make_tracked_session"
    )
    def test_raises_on_non_list_response(self, mock_session: mock.MagicMock) -> None:
        # A 2xx with an unexpected (non-array) body must fail loudly, not sync zero rows silently.
        page = mock.MagicMock(status_code=200, ok=True)
        page.json.return_value = {"error": "something went wrong"}
        mock_session.return_value.get.return_value = page

        with pytest.raises(ValueError, match="unexpected"):
            list(get_rows("na1", "key", "Contacts", mock.MagicMock(), self._manager()))


class TestInsightlySourceResponse:
    @pytest.mark.parametrize(
        "endpoint, expected_pk, expected_partition_keys, expected_mode",
        [
            ("Contacts", "CONTACT_ID", ["DATE_CREATED_UTC"], "datetime"),
            ("Opportunities", "OPPORTUNITY_ID", ["DATE_CREATED_UTC"], "datetime"),
            ("Users", "USER_ID", ["DATE_CREATED_UTC"], "datetime"),
            ("Pipelines", "PIPELINE_ID", None, None),
        ],
    )
    def test_source_response_shape(
        self,
        endpoint: str,
        expected_pk: str,
        expected_partition_keys: list[str] | None,
        expected_mode: str | None,
    ) -> None:
        response = insightly_source("na1", "key", endpoint, mock.MagicMock(), mock.MagicMock())
        assert response.name == endpoint
        assert response.primary_keys == [expected_pk]
        assert response.partition_keys == expected_partition_keys
        assert response.partition_mode == expected_mode
        assert response.sort_mode == "asc"


class TestBuildUrl:
    def test_build_url_encodes_params(self) -> None:
        params: dict[str, Any] = {"top": 500, "skip": 0, "updated_after_utc": "2020-01-01T00:00:00Z"}
        url = _build_url("na1", "/Contacts", params)
        assert url == (
            "https://api.na1.insightly.com/v3.1/Contacts?top=500&skip=0&updated_after_utc=2020-01-01T00%3A00%3A00Z"
        )
