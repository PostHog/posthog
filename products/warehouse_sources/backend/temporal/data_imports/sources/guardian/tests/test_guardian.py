from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.guardian import guardian
from products.warehouse_sources.backend.temporal.data_imports.sources.guardian.guardian import (
    GuardianResumeConfig,
    _build_base_params,
    _format_from_date,
    _scrub_url,
    get_rows,
    guardian_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.guardian.settings import GUARDIAN_ENDPOINTS


class _FakeResumableManager:
    def __init__(self, state: GuardianResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[GuardianResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> GuardianResumeConfig | None:
        return self._state

    def save_state(self, data: GuardianResumeConfig) -> None:
        self.saved.append(data)


def _page(results: list[dict[str, Any]], *, pages: int = 1, current_page: int = 1) -> dict[str, Any]:
    return {"response": {"status": "ok", "results": results, "pages": pages, "currentPage": current_page}}


class TestFormatFromDate:
    @pytest.mark.parametrize(
        "value,expected",
        [
            (datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04"),
            (date(2026, 3, 4), "2026-03-04"),
            ("2026-03-04T02:58:14Z", "2026-03-04"),
            ("", None),
            (None, None),
        ],
    )
    def test_format_from_date(self, value: Any, expected: str | None) -> None:
        assert _format_from_date(value) == expected


class TestBuildBaseParams:
    def test_content_incremental_sets_from_date_and_oldest_order(self) -> None:
        params = _build_base_params(
            GUARDIAN_ENDPOINTS["content"],
            api_key="k",
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
        )
        assert params["from-date"] == "2026-03-04"
        # Ascending order is what keeps the incremental watermark advancing correctly.
        assert params["order-by"] == "oldest"
        assert params["order-date"] == "published"
        assert params["show-fields"] == "all"

    def test_content_full_refresh_has_no_from_date(self) -> None:
        params = _build_base_params(
            GUARDIAN_ENDPOINTS["content"],
            api_key="k",
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
        )
        assert "from-date" not in params

    def test_non_incremental_endpoint_never_sets_from_date(self) -> None:
        # tags advertises no incremental field, so even an accidental cursor value is ignored.
        params = _build_base_params(
            GUARDIAN_ENDPOINTS["tags"],
            api_key="k",
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
        )
        assert "from-date" not in params


class TestScrubUrl:
    @pytest.mark.parametrize(
        "url,expected",
        [
            (
                "https://content.guardianapis.com/search?api-key=secret&page=1",
                "https://content.guardianapis.com/search",
            ),
            ("https://content.guardianapis.com/tags", "https://content.guardianapis.com/tags"),
            (None, "https://content.guardianapis.com"),
        ],
    )
    def test_scrub_url_strips_query(self, url: str | None, expected: str) -> None:
        assert _scrub_url(url) == expected


class TestValidateCredentials:
    @pytest.mark.parametrize("status_code,expected", [(200, True), (401, False), (403, False)])
    def test_status_maps_to_bool(self, status_code: int, expected: bool) -> None:
        response = MagicMock()
        response.status_code = status_code
        session = MagicMock()
        session.get.return_value = response
        with patch.object(guardian, "make_tracked_session", return_value=session):
            assert validate_credentials("some-key") is expected

    def test_network_error_is_false(self) -> None:
        session = MagicMock()
        session.get.side_effect = requests.ConnectionError("boom")
        with patch.object(guardian, "make_tracked_session", return_value=session):
            assert validate_credentials("some-key") is False


class TestGetRows:
    @staticmethod
    def _collect(manager: _FakeResumableManager, pages: dict[str, dict[str, Any]], **kwargs: Any) -> list[dict]:
        def fake_fetch(session: Any, url: str, logger: Any) -> dict[str, Any]:
            # Match by page number embedded in the URL so param ordering doesn't matter.
            for marker, payload in pages.items():
                if f"page={marker}" in url:
                    return payload
            raise AssertionError(f"unexpected url: {url}")

        with patch.object(guardian, "make_tracked_session", return_value=MagicMock()):
            with patch.object(guardian, "_fetch_page", side_effect=fake_fetch):
                rows: list[dict] = []
                for batch in get_rows(
                    api_key="k",
                    endpoint="content",
                    logger=MagicMock(),
                    resumable_source_manager=manager,  # type: ignore[arg-type]
                    **kwargs,
                ):
                    rows.extend(batch)
                return rows

    def test_paginates_until_last_page(self) -> None:
        pages = {
            "1": _page([{"id": "a"}, {"id": "b"}], pages=2, current_page=1),
            "2": _page([{"id": "c"}], pages=2, current_page=2),
        }
        rows = self._collect(_FakeResumableManager(), pages)
        assert [r["id"] for r in rows] == ["a", "b", "c"]

    def test_saves_next_page_after_yield(self) -> None:
        pages = {
            "1": _page([{"id": "a"}], pages=2, current_page=1),
            "2": _page([{"id": "b"}], pages=2, current_page=2),
        }
        manager = _FakeResumableManager()
        self._collect(manager, pages)
        # State is saved once (after page 1 yields), pointing at page 2. The final page saves nothing.
        assert manager.saved == [GuardianResumeConfig(page=2)]

    def test_resumes_from_saved_page(self) -> None:
        pages = {
            "1": _page([{"id": "a"}], pages=3, current_page=1),
            "2": _page([{"id": "b"}], pages=3, current_page=2),
            "3": _page([{"id": "c"}], pages=3, current_page=3),
        }
        manager = _FakeResumableManager(GuardianResumeConfig(page=3))
        rows = self._collect(manager, pages)
        # Resuming at page 3 skips the already-synced earlier pages.
        assert [r["id"] for r in rows] == ["c"]

    def test_single_page_response_without_pagination_metadata(self) -> None:
        # /sections and /editions omit `pages`/`currentPage`; default to a single page.
        def fake_fetch(session: Any, url: str, logger: Any) -> dict[str, Any]:
            return {"response": {"status": "ok", "results": [{"id": "uk"}, {"id": "us"}]}}

        manager = _FakeResumableManager()
        with patch.object(guardian, "make_tracked_session", return_value=MagicMock()):
            with patch.object(guardian, "_fetch_page", side_effect=fake_fetch):
                rows = [r for batch in get_rows("k", "editions", MagicMock(), manager) for r in batch]  # type: ignore[arg-type]
        assert [r["id"] for r in rows] == ["uk", "us"]
        assert manager.saved == []


class TestFetchPageRetries:
    @pytest.mark.parametrize("status_code", [429, 500, 503])
    def test_retryable_status_raises_retryable_error(self, status_code: int) -> None:
        response = MagicMock()
        response.status_code = status_code
        session = MagicMock()
        session.get.return_value = response
        with patch.object(guardian._fetch_page.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            with pytest.raises(guardian.GuardianRetryableError):
                guardian._fetch_page(session, "https://content.guardianapis.com/search?page=1", MagicMock())
        assert session.get.call_count == 5

    def test_transient_network_error_is_retried_then_succeeds(self) -> None:
        good = MagicMock()
        good.status_code = 200
        good.ok = True
        good.json.return_value = _page([{"id": "a"}])
        session = MagicMock()
        session.get.side_effect = [requests.ReadTimeout("timed out"), good]
        with patch.object(guardian._fetch_page.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            result = guardian._fetch_page(session, "https://content.guardianapis.com/search?page=1", MagicMock())
        assert result == _page([{"id": "a"}])
        assert session.get.call_count == 2

    def test_auth_failure_raises_without_leaking_api_key(self) -> None:
        # The api-key rides in the query string; a non-2xx must not surface it in the exception, but
        # the base host must survive so get_non_retryable_errors() can still match.
        response = MagicMock()
        response.status_code = 401
        response.ok = False
        response.reason = "Unauthorized"
        response.text = "Unauthorized"
        response.url = "https://content.guardianapis.com/search?api-key=super-secret&page=1"
        session = MagicMock()
        session.get.return_value = response
        with pytest.raises(requests.HTTPError) as exc_info:
            guardian._fetch_page(session, response.url, MagicMock())
        message = str(exc_info.value)
        assert "super-secret" not in message
        assert "401 Client Error: Unauthorized for url: https://content.guardianapis.com/search" in message


class TestGuardianSourceResponse:
    def test_content_partitions_on_stable_publication_date(self) -> None:
        response = guardian_source("k", "content", MagicMock(), MagicMock())
        assert response.primary_keys == ["id"]
        assert response.partition_keys == ["webPublicationDate"]
        assert response.partition_mode == "datetime"
        assert response.sort_mode == "asc"

    @pytest.mark.parametrize("endpoint", ["tags", "sections", "editions"])
    def test_reference_endpoints_are_unpartitioned(self, endpoint: str) -> None:
        response = guardian_source("k", endpoint, MagicMock(), MagicMock())
        assert response.primary_keys == ["id"]
        assert response.partition_keys is None
        assert response.partition_mode is None
        # Full-refresh endpoints carry no order-by, so their order is unspecified.
        assert response.sort_mode is None
