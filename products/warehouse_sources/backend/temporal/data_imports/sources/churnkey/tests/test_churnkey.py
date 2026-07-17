from collections.abc import Iterable
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

from products.warehouse_sources.backend.temporal.data_imports.sources.churnkey.churnkey import (
    ChurnkeyResumeConfig,
    _get_headers,
    churnkey_source,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.churnkey.settings import (
    CHURNKEY_ENDPOINTS,
    DEFAULT_PAGE_SIZE,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

_FETCH = "products.warehouse_sources.backend.temporal.data_imports.sources.churnkey.churnkey._fetch_page"


def _logger() -> MagicMock:
    log = MagicMock()
    log.debug = MagicMock()
    log.error = MagicMock()
    return log


class TestHeaders:
    def test_get_headers(self) -> None:
        headers = _get_headers("data_abc", "app_123")
        assert headers["x-ck-api-key"] == "data_abc"
        assert headers["x-ck-app"] == "app_123"
        assert headers["content-type"] == "application/json"


class TestValidateCredentials:
    @pytest.mark.parametrize(
        ("status_code", "expected"),
        [
            (200, (True, 200)),
            (401, (False, 401)),
            (403, (False, 403)),
            (404, (False, 404)),
            (500, (False, 500)),
        ],
    )
    def test_status_mapping(self, status_code: int, expected: tuple[bool, int]) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.churnkey.churnkey.make_tracked_session"
        ) as mock_session:
            response = MagicMock()
            response.status_code = status_code
            mock_session.return_value.get.return_value = response

            assert validate_credentials("key", "app") == expected

    def test_network_failure_returns_none_status(self) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.churnkey.churnkey.make_tracked_session"
        ) as mock_session:
            mock_session.return_value.get.side_effect = Exception("boom")
            assert validate_credentials("key", "app") == (False, None)


def _drive_rows(manager: MagicMock, pages: list[list[dict[str, Any]]]) -> tuple[list[list[dict[str, Any]]], list[str]]:
    """Run ``get_rows`` against ``pages`` (returned in order) with page size forced to 2.

    Returns ``(yielded_pages, requested_urls)``.
    """
    urls: list[str] = []
    page_iter = iter(pages)

    def fake_fetch(_session: Any, url: str, _headers: Any, _logger: Any) -> list[dict[str, Any]]:
        urls.append(url)
        return next(page_iter, [])

    with (
        patch.object(CHURNKEY_ENDPOINTS["Sessions"], "page_size", 2),
        patch(_FETCH, side_effect=fake_fetch),
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.churnkey.churnkey.make_tracked_session"
        ),
    ):
        yielded = list(get_rows("key", "app", "Sessions", _logger(), manager))
    return yielded, urls


class TestGetRows:
    def test_fresh_run_pages_and_saves_after_each_non_terminal_page(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        pages = [
            [{"_id": "1"}, {"_id": "2"}],
            [{"_id": "3"}, {"_id": "4"}],
            [{"_id": "5"}],  # short page → terminal
        ]
        yielded, urls = _drive_rows(manager, pages)

        assert yielded == pages
        # skip advances by the page size (2) each request, starting at 0.
        assert [u.split("?", 1)[1] for u in urls] == ["limit=2&skip=0", "limit=2&skip=2", "limit=2&skip=4"]
        # State saved only after the two full (non-terminal) pages, never after the short one.
        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [ChurnkeyResumeConfig(skip=2), ChurnkeyResumeConfig(skip=4)]
        manager.load_state.assert_not_called()

    def test_resume_starts_from_saved_skip(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = ChurnkeyResumeConfig(skip=4)

        yielded, urls = _drive_rows(manager, [[{"_id": "5"}]])

        assert yielded == [[{"_id": "5"}]]
        assert urls[0].split("?", 1)[1] == "limit=2&skip=4"
        manager.load_state.assert_called_once()

    def test_terminal_single_page_does_not_save_state(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        yielded, _ = _drive_rows(manager, [[{"_id": "only"}]])

        assert yielded == [[{"_id": "only"}]]
        manager.save_state.assert_not_called()

    def test_empty_first_page_yields_nothing(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        yielded, urls = _drive_rows(manager, [[]])

        assert yielded == []
        assert len(urls) == 1
        manager.save_state.assert_not_called()


class TestChurnkeySource:
    def test_source_response_shape(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        response = churnkey_source("key", "app", "Sessions", _logger(), manager)

        assert response.name == "Sessions"
        assert response.primary_keys == ["_id"]
        assert response.partition_mode == "datetime"
        assert response.partition_format == "month"
        assert response.partition_keys == ["createdAt"]

    def test_items_is_lazy(self) -> None:
        # Building the SourceResponse must not perform any HTTP — items is a thunk.
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False
        with patch(_FETCH) as mock_fetch:
            response = churnkey_source("key", "app", "Sessions", _logger(), manager)
            mock_fetch.assert_not_called()
            # Draining the iterator (one empty page) then triggers a fetch.
            mock_fetch.return_value = []
            list(cast(Iterable[Any], response.items()))
            assert mock_fetch.called

    def test_default_page_size_within_api_cap(self) -> None:
        # The API rejects limit > 10,000.
        assert 0 < DEFAULT_PAGE_SIZE <= 10_000
