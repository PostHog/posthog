from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.fulcrum import fulcrum
from products.warehouse_sources.backend.temporal.data_imports.sources.fulcrum.fulcrum import (
    FulcrumResumeConfig,
    _build_params,
    _has_more_pages,
    _to_epoch_seconds,
    fulcrum_source,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.fulcrum.settings import FULCRUM_ENDPOINTS


class TestToEpochSeconds:
    @parameterized.expand(
        [
            ("datetime", datetime(2021, 1, 1, tzinfo=UTC), 1609459200),
            ("date", date(2021, 1, 1), int(datetime(2021, 1, 1).timestamp())),
            ("int_passthrough", 1609459200, 1609459200),
            ("iso_string", "2021-01-01T00:00:00+00:00", 1609459200),
            ("iso_string_z", "2021-01-01T00:00:00Z", 1609459200),
            ("none", None, None),
            ("garbage_string", "not-a-date", None),
        ]
    )
    def test_to_epoch_seconds(self, _name: str, value: Any, expected: int | None) -> None:
        assert _to_epoch_seconds(value) == expected


class TestBuildParams:
    def test_records_incremental_adds_updated_since(self) -> None:
        params = _build_params(
            FULCRUM_ENDPOINTS["records"],
            page=1,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2021, 1, 1, tzinfo=UTC),
        )
        assert params["updated_since"] == 1609459200
        assert params["page"] == 1
        assert params["per_page"] == FULCRUM_ENDPOINTS["records"].page_size

    def test_records_full_refresh_omits_filter(self) -> None:
        params = _build_params(
            FULCRUM_ENDPOINTS["records"],
            page=2,
            should_use_incremental_field=False,
            db_incremental_field_last_value=datetime(2021, 1, 1, tzinfo=UTC),
        )
        assert "updated_since" not in params
        assert params["page"] == 2

    @parameterized.expand(["forms", "projects", "photos"])
    def test_non_incremental_endpoints_never_filter(self, endpoint: str) -> None:
        # A full-refresh endpoint must never send updated_since even when a watermark is present —
        # the API would silently ignore it, but we keep the request honest.
        params = _build_params(
            FULCRUM_ENDPOINTS[endpoint],
            page=1,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2021, 1, 1, tzinfo=UTC),
        )
        assert "updated_since" not in params


class TestHasMorePages:
    @parameterized.expand(
        [
            # (total_pages, current_page, items_len, per_page, expected_more)
            ("more_by_total_pages", 3, 1, 1000, 1000, True),
            ("last_by_total_pages", 3, 3, 200, 1000, False),
            ("missing_total_full_page_means_more", None, 1, 1000, 1000, True),
            ("missing_total_short_page_means_done", None, 1, 42, 1000, False),
        ]
    )
    def test_has_more_pages(
        self,
        _name: str,
        total_pages: int | None,
        current_page: int,
        items_len: int,
        per_page: int,
        expected_more: bool,
    ) -> None:
        data: dict[str, Any] = {"current_page": current_page}
        if total_pages is not None:
            data["total_pages"] = total_pages
        items: list[dict[str, Any]] = [{}] * items_len
        assert _has_more_pages(data, items, current_page, per_page) is expected_more


class TestGetRows:
    def _page(self, data_key: str, items: list[dict], total_pages: int, current_page: int) -> dict[str, Any]:
        return {data_key: items, "total_pages": total_pages, "current_page": current_page}

    def test_paginates_and_yields_each_page(self) -> None:
        manager = mock.Mock()
        manager.can_resume.return_value = False
        pages = [
            self._page("forms", [{"id": "1"}], total_pages=2, current_page=1),
            self._page("forms", [{"id": "2"}], total_pages=2, current_page=2),
        ]
        with mock.patch.object(fulcrum, "_fetch_page", side_effect=pages):
            batches = list(get_rows("token", "forms", mock.Mock(), manager))

        assert batches == [[{"id": "1"}], [{"id": "2"}]]

    def test_stops_on_empty_page(self) -> None:
        manager = mock.Mock()
        manager.can_resume.return_value = False
        with mock.patch.object(fulcrum, "_fetch_page", return_value=self._page("forms", [], 1, 1)):
            batches = list(get_rows("token", "forms", mock.Mock(), manager))
        assert batches == []

    def test_saves_resume_state_after_yielding_each_page(self) -> None:
        # State must be saved AFTER a page is yielded (so a crash re-yields, not skips) and only
        # while more pages remain — the last page saves nothing.
        manager = mock.Mock()
        manager.can_resume.return_value = False
        emitted: list[Any] = []
        pages = [
            self._page("forms", [{"id": "1"}], total_pages=2, current_page=1),
            self._page("forms", [{"id": "2"}], total_pages=2, current_page=2),
        ]

        def _record_save(state: FulcrumResumeConfig) -> None:
            # Capture how many batches had been produced when the save happened.
            emitted.append(("save", state.page, len(batches)))

        manager.save_state.side_effect = _record_save
        with mock.patch.object(fulcrum, "_fetch_page", side_effect=pages):
            batches: list[Any] = []
            for batch in get_rows("token", "forms", mock.Mock(), manager):
                batches.append(batch)

        # One save (advancing to page 2), recorded after the first page was already yielded.
        assert emitted == [("save", 2, 1)]

    def test_resumes_from_saved_page(self) -> None:
        manager = mock.Mock()
        manager.can_resume.return_value = True
        manager.load_state.return_value = FulcrumResumeConfig(page=2)
        seen_urls: list[str] = []

        def _fetch(_session: Any, url: str, _headers: Any, _logger: Any) -> dict[str, Any]:
            seen_urls.append(url)
            return self._page("forms", [{"id": "2"}], total_pages=2, current_page=2)

        with mock.patch.object(fulcrum, "_fetch_page", side_effect=_fetch):
            list(get_rows("token", "forms", mock.Mock(), manager))

        assert "page=2" in seen_urls[0]


class TestFulcrumSource:
    @parameterized.expand(
        [
            ("records", ["id"], "created_at", "asc"),
            ("photos", ["access_key"], "created_at", "asc"),
            ("roles", ["id"], None, "asc"),
        ]
    )
    def test_source_response_shape(
        self, endpoint: str, expected_pk: list[str], partition_key: str | None, sort_mode: str
    ) -> None:
        response = fulcrum_source("token", endpoint, mock.Mock(), mock.Mock())
        assert response.name == endpoint
        assert response.primary_keys == expected_pk
        assert response.sort_mode == sort_mode
        if partition_key is None:
            assert response.partition_mode is None
        else:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [partition_key]


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("unauthorized", 401, False), ("forbidden", 403, False)])
    def test_status_mapping(self, _name: str, status_code: int, expected: bool) -> None:
        session = mock.Mock()
        response = mock.Mock(spec=requests.Response)
        response.status_code = status_code
        session.get.return_value = response
        with mock.patch.object(fulcrum, "make_tracked_session", return_value=session):
            assert validate_credentials("token") is expected

    def test_network_error_is_false(self) -> None:
        session = mock.Mock()
        session.get.side_effect = requests.ConnectionError("boom")
        with mock.patch.object(fulcrum, "make_tracked_session", return_value=session):
            assert validate_credentials("token") is False


class TestFetchPage:
    # tenacity exposes the undecorated body as __wrapped__; access it via getattr so a single
    # attempt's classification can be asserted without the retry loop actually sleeping.
    _fetch_page_body = staticmethod(getattr(fulcrum._fetch_page, "__wrapped__"))

    @parameterized.expand([("rate_limited", 429), ("server_error", 503)])
    def test_retryable_status_raises_retryable_error(self, _name: str, status_code: int) -> None:
        # Fulcrum enforces an hourly request cap (429) and can 5xx transiently; both must be
        # classified retryable so a rate limit doesn't hard-fail the whole sync.
        session = mock.Mock()
        response = mock.Mock(spec=requests.Response)
        response.status_code = status_code
        response.ok = False
        response.text = ""
        session.get.return_value = response

        with pytest.raises(fulcrum.FulcrumRetryableError):
            self._fetch_page_body(session, "https://api.fulcrumapp.com/api/v2/forms.json", {}, mock.Mock())

    def test_client_error_raises_for_status(self) -> None:
        session = mock.Mock()
        response = mock.Mock(spec=requests.Response)
        response.status_code = 401
        response.ok = False
        response.text = "unauthorized"
        response.raise_for_status.side_effect = requests.HTTPError("401 Client Error", response=response)
        session.get.return_value = response

        with pytest.raises(requests.HTTPError):
            self._fetch_page_body(session, "https://api.fulcrumapp.com/api/v2/forms.json", {}, mock.Mock())
