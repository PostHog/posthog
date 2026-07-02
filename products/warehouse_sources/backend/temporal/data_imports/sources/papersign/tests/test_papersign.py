from typing import Any
from urllib.parse import parse_qs, urlparse

from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.papersign import papersign
from products.warehouse_sources.backend.temporal.data_imports.sources.papersign.papersign import (
    BASE_URL,
    PAGE_SIZE,
    PapersignResumeConfig,
    _build_url,
    get_rows,
    papersign_source,
    validate_credentials,
)


def _ok_json_response(payload: dict | None = None, status_code: int = 200) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = payload if payload is not None else {}
    response.raise_for_status = MagicMock()
    return response


class _FakeResumableManager:
    def __init__(self, state: PapersignResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[PapersignResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> PapersignResumeConfig | None:
        return self._state

    def save_state(self, data: PapersignResumeConfig) -> None:
        self.saved.append(data)


def _page(results_key: str, rows: list[dict[str, Any]], has_more: bool) -> dict[str, Any]:
    return {
        "status": "ok",
        "results": {results_key: rows},
        "total": len(rows),
        "has_more": has_more,
        "limit": PAGE_SIZE,
        "skip": 0,
    }


def _docs(count: int, start: int = 0) -> list[dict[str, Any]]:
    return [{"id": f"doc-{start + i}", "created_at_utc": "2026-01-01T00:00:00Z"} for i in range(count)]


class TestBuildUrl:
    def test_no_params(self) -> None:
        assert _build_url("/papersign/spaces", {}) == f"{BASE_URL}/papersign/spaces"

    def test_with_params_is_urlencoded(self) -> None:
        url = _build_url("/papersign/documents", {"limit": 100, "skip": 200, "sort": "ASC"})
        assert url == f"{BASE_URL}/papersign/documents?limit=100&skip=200&sort=ASC"


class TestValidateCredentials:
    @patch.object(papersign, "make_tracked_session")
    def test_returns_true_on_200(self, mock_session: MagicMock) -> None:
        mock_session.return_value.get.return_value = _ok_json_response({"results": {"spaces": []}})

        success, error = validate_credentials("tok")

        assert success is True
        assert error is None
        called_url = mock_session.return_value.get.call_args.args[0]
        assert called_url == f"{BASE_URL}/papersign/spaces?limit=1"

    @parameterized.expand(
        [
            (401, "invalid"),
            (403, "papersign api access"),
            (500, "unexpected status"),
        ]
    )
    @patch.object(papersign, "make_tracked_session")
    def test_returns_false_on_http_status(
        self, status_code: int, expected_substring: str, mock_session: MagicMock
    ) -> None:
        mock_session.return_value.get.return_value = _ok_json_response(status_code=status_code)

        success, error = validate_credentials("tok")

        assert success is False
        assert error is not None
        assert expected_substring.lower() in error.lower()

    @patch.object(papersign, "make_tracked_session")
    def test_redacts_token_in_tracked_session(self, mock_session: MagicMock) -> None:
        # The bearer token must be passed to redact_values so it's masked in logged URLs and captured
        # HTTP samples. Dropping this would leak customers' API keys into the capture pipeline.
        mock_session.return_value.get.return_value = _ok_json_response({"results": {"spaces": []}})
        validate_credentials("secret-token")
        assert mock_session.call_args.kwargs.get("redact_values") == ("secret-token",)

    @patch.object(papersign, "make_tracked_session")
    def test_returns_false_on_network_error(self, mock_session: MagicMock) -> None:
        mock_session.return_value.get.side_effect = requests.ConnectionError("boom")

        success, error = validate_credentials("tok")

        assert success is False
        assert error is not None
        assert "could not reach paperform" in error.lower()


class TestGetRows:
    @staticmethod
    def _run(
        manager: _FakeResumableManager,
        pages: list[dict[str, Any]],
        endpoint: str = "documents",
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Drive get_rows against a queue of page responses. Returns (rows, recorded_requests)."""
        queue = list(pages)
        recorded: list[dict[str, Any]] = []

        def fake_fetch(session: Any, url: str, logger: Any) -> dict[str, Any]:
            query = parse_qs(urlparse(url).query)
            recorded.append(
                {
                    "url": url,
                    "skip": int(query["skip"][0]) if "skip" in query else None,
                    "limit": int(query["limit"][0]) if "limit" in query else None,
                    "sort": query["sort"][0] if "sort" in query else None,
                }
            )
            return queue.pop(0)

        with patch.object(papersign, "_fetch_page", side_effect=fake_fetch):
            rows: list[dict[str, Any]] = []
            for page in get_rows(
                api_token="tok",
                endpoint=endpoint,
                logger=MagicMock(),
                resumable_source_manager=manager,  # type: ignore[arg-type]
            ):
                rows.extend(page)
        return rows, recorded

    def test_single_page_terminates_when_has_more_false(self) -> None:
        manager = _FakeResumableManager()
        rows, recorded = self._run(manager, [_page("documents", _docs(3), has_more=False)])

        assert [r["id"] for r in rows] == ["doc-0", "doc-1", "doc-2"]
        assert len(recorded) == 1
        assert recorded[0]["skip"] == 0
        assert recorded[0]["limit"] == PAGE_SIZE
        # Documents are the only endpoint that gets an explicit ascending sort.
        assert recorded[0]["sort"] == "ASC"

    def test_walks_pages_incrementing_skip(self) -> None:
        manager = _FakeResumableManager()
        pages = [
            _page("documents", _docs(PAGE_SIZE, start=0), has_more=True),
            _page("documents", _docs(PAGE_SIZE, start=PAGE_SIZE), has_more=True),
            _page("documents", _docs(50, start=2 * PAGE_SIZE), has_more=False),
        ]
        rows, recorded = self._run(manager, pages)

        assert len(rows) == 2 * PAGE_SIZE + 50
        # skip advances by the number of rows actually returned on each page.
        assert [r["skip"] for r in recorded] == [0, PAGE_SIZE, 2 * PAGE_SIZE]

    def test_short_page_terminates_even_if_has_more_true(self) -> None:
        # Guards the folders/spaces infinite-loop case: an endpoint that ignores `skip` but keeps
        # reporting has_more=true must still stop once a page comes back shorter than the limit.
        manager = _FakeResumableManager()
        rows, recorded = self._run(
            manager, [_page("folders", [{"id": i} for i in range(3)], has_more=True)], endpoint="folders"
        )
        assert len(rows) == 3
        assert len(recorded) == 1

    def test_stops_when_results_empty(self) -> None:
        manager = _FakeResumableManager()
        # has_more lies (True) but the page is empty — we must still terminate, not loop forever.
        rows, recorded = self._run(manager, [_page("documents", [], has_more=True)])

        assert rows == []
        assert len(recorded) == 1

    def test_folders_endpoint_sends_no_sort(self) -> None:
        manager = _FakeResumableManager()
        _rows, recorded = self._run(
            manager, [_page("folders", [{"id": 1, "name": "F"}], has_more=False)], endpoint="folders"
        )
        assert recorded[0]["sort"] is None

    def test_resume_uses_saved_skip(self) -> None:
        manager = _FakeResumableManager(PapersignResumeConfig(skip=200))
        _rows, recorded = self._run(manager, [_page("documents", _docs(2, start=200), has_more=False)])

        # First request must continue from the saved offset, not restart at 0.
        assert recorded[0]["skip"] == 200

    def test_saves_only_already_fetched_offsets_after_yield(self) -> None:
        # The "save current page, not next" invariant: every persisted offset must be one we've
        # already fetched, so a crash re-fetches (merge dedupes) rather than skipping buffered rows.
        manager = _FakeResumableManager()
        pages = [
            _page("documents", _docs(PAGE_SIZE, start=0), has_more=True),
            _page("documents", _docs(PAGE_SIZE, start=PAGE_SIZE), has_more=True),
            _page("documents", _docs(10, start=2 * PAGE_SIZE), has_more=False),
        ]
        _rows, recorded = self._run(manager, pages)

        fetched_skips = {r["skip"] for r in recorded}
        assert manager.saved, "expected a save after each yielded page"
        assert all(saved.skip in fetched_skips for saved in manager.saved)


class TestPapersignSourceResponse:
    def test_documents_partitions_on_created_at(self) -> None:
        response = papersign_source(
            api_token="tok",
            endpoint="documents",
            logger=MagicMock(),
            resumable_source_manager=_FakeResumableManager(),  # type: ignore[arg-type]
        )
        assert response.name == "documents"
        assert response.primary_keys == ["id"]
        assert response.sort_mode == "asc"
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["created_at_utc"]

    @parameterized.expand(["folders", "spaces"])
    def test_untimestamped_endpoints_are_not_partitioned(self, endpoint: str) -> None:
        # folders and spaces carry no stable datetime field, so they must not declare a datetime
        # partition (partitioning on a missing column would break the sync).
        response = papersign_source(
            api_token="tok",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=_FakeResumableManager(),  # type: ignore[arg-type]
        )
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        assert response.partition_mode is None
        assert response.partition_keys is None
