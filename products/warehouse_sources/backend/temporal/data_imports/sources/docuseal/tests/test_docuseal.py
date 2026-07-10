from typing import Any
from urllib.parse import parse_qs, urlparse

from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.docuseal import docuseal
from products.warehouse_sources.backend.temporal.data_imports.sources.docuseal.docuseal import (
    DEFAULT_REGION,
    DOCUSEAL_HOSTS,
    PAGE_SIZE,
    DocusealResumeConfig,
    _base_url,
    _build_url,
    docuseal_source,
    get_rows,
    validate_credentials,
)


def _ok_json_response(payload: dict | list | None = None, status_code: int = 200) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = payload if payload is not None else {}
    response.raise_for_status = MagicMock()
    return response


class _FakeResumableManager:
    def __init__(self, state: DocusealResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[DocusealResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> DocusealResumeConfig | None:
        return self._state

    def save_state(self, data: DocusealResumeConfig) -> None:
        self.saved.append(data)


class TestBaseUrl:
    @parameterized.expand(
        [
            ("us", DOCUSEAL_HOSTS["us"]),
            ("eu", DOCUSEAL_HOSTS["eu"]),
            (None, DOCUSEAL_HOSTS[DEFAULT_REGION]),
            ("", DOCUSEAL_HOSTS[DEFAULT_REGION]),
            ("unknown", DOCUSEAL_HOSTS[DEFAULT_REGION]),
        ]
    )
    def test_picks_correct_base_url(self, region: str | None, expected: str) -> None:
        assert _base_url(region) == expected


class TestBuildUrl:
    def test_no_params(self) -> None:
        assert _build_url("https://api.docuseal.com", "/templates", {}) == "https://api.docuseal.com/templates"

    def test_with_params_is_urlencoded(self) -> None:
        url = _build_url("https://api.docuseal.com", "/submissions", {"limit": 100, "after": 42})
        assert url == "https://api.docuseal.com/submissions?limit=100&after=42"


class TestValidateCredentials:
    @patch.object(docuseal, "make_tracked_session")
    def test_returns_true_on_200(self, mock_session: MagicMock) -> None:
        mock_session.return_value.get.return_value = _ok_json_response({"data": []})

        success, error = validate_credentials("key", "us")

        assert success is True
        assert error is None
        called_url = mock_session.return_value.get.call_args.args[0]
        assert called_url == f"{DOCUSEAL_HOSTS['us']}/templates?limit=1"

    def test_probes_selected_region_host(self) -> None:
        with patch.object(docuseal, "make_tracked_session") as mock_session:
            mock_session.return_value.get.return_value = _ok_json_response({"data": []})
            validate_credentials("key", "eu")
            called_url = mock_session.return_value.get.call_args.args[0]
            assert called_url.startswith(DOCUSEAL_HOSTS["eu"])

    @parameterized.expand(
        [
            (401, "invalid"),
            (500, "unexpected status"),
        ]
    )
    @patch.object(docuseal, "make_tracked_session")
    def test_returns_false_on_http_status(
        self, status_code: int, expected_substring: str, mock_session: MagicMock
    ) -> None:
        mock_session.return_value.get.return_value = _ok_json_response(status_code=status_code)

        success, error = validate_credentials("key", "us")

        assert success is False
        assert error is not None
        assert expected_substring.lower() in error.lower()

    @patch.object(docuseal, "make_tracked_session")
    def test_returns_false_on_network_error(self, mock_session: MagicMock) -> None:
        mock_session.return_value.get.side_effect = requests.ConnectionError("boom")

        success, error = validate_credentials("key", "us")

        assert success is False
        assert error is not None
        assert "could not reach docuseal" in error.lower()


def _page(rows: list[dict[str, Any]], next_cursor: int | None) -> dict[str, Any]:
    return {"data": rows, "pagination": {"count": len(rows), "next": next_cursor, "prev": None}}


def _rows(start_id: int, count: int) -> list[dict[str, Any]]:
    """`count` rows in DocuSeal's newest-first (descending id) order, starting at `start_id`."""
    return [{"id": start_id - offset, "created_at": "2026-01-01T00:00:00Z"} for offset in range(count)]


class TestGetRows:
    @staticmethod
    def _run(
        manager: _FakeResumableManager,
        pages: list[dict[str, Any]],
        endpoint: str = "templates",
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Drive get_rows against a queue of page responses. Returns (rows, recorded_requests)."""
        queue = list(pages)
        recorded: list[dict[str, Any]] = []

        def fake_fetch(session: Any, url: str, headers: dict[str, str], logger: Any) -> dict[str, Any]:
            query = parse_qs(urlparse(url).query)
            recorded.append(
                {
                    "url": url,
                    "after": int(query["after"][0]) if "after" in query else None,
                    "limit": int(query["limit"][0]) if "limit" in query else None,
                }
            )
            return queue.pop(0)

        with patch.object(docuseal, "_fetch_page", side_effect=fake_fetch):
            rows: list[dict[str, Any]] = []
            for table in get_rows(
                api_key="tok",
                region="us",
                endpoint=endpoint,
                logger=MagicMock(),
                resumable_source_manager=manager,  # type: ignore[arg-type]
            ):
                rows.extend(table.to_pylist())
        return rows, recorded

    def test_single_short_page_terminates_without_extra_request(self) -> None:
        manager = _FakeResumableManager()
        rows, recorded = self._run(manager, [_page(_rows(3, 3), next_cursor=1)])

        assert [r["id"] for r in rows] == [3, 2, 1]
        # A page shorter than the page size is the last one — no follow-up request.
        assert len(recorded) == 1
        assert recorded[0]["after"] is None
        assert recorded[0]["limit"] == PAGE_SIZE

    def test_walks_pages_using_after_cursor(self) -> None:
        manager = _FakeResumableManager()
        pages = [
            _page(_rows(300, PAGE_SIZE), next_cursor=201),
            _page(_rows(200, PAGE_SIZE), next_cursor=101),
            _page(_rows(100, 50), next_cursor=51),
        ]
        rows, recorded = self._run(manager, pages)

        assert len(rows) == 250
        assert [r["after"] for r in recorded] == [None, 201, 101]
        # Newest-first across the whole walk.
        assert rows[0]["id"] == 300
        assert rows[-1]["id"] == 51

    def test_stops_when_next_cursor_is_null(self) -> None:
        manager = _FakeResumableManager()
        # A full-size page whose `next` is null (empty next page) must still terminate.
        rows, recorded = self._run(manager, [_page(_rows(100, PAGE_SIZE), next_cursor=None)])

        assert len(rows) == PAGE_SIZE
        assert len(recorded) == 1

    def test_empty_first_page_yields_nothing(self) -> None:
        manager = _FakeResumableManager()
        rows, recorded = self._run(manager, [_page([], next_cursor=None)])

        assert rows == []
        assert len(recorded) == 1

    def test_resume_uses_saved_after_cursor(self) -> None:
        manager = _FakeResumableManager(DocusealResumeConfig(after=500))
        rows, recorded = self._run(manager, [_page(_rows(499, 2), next_cursor=498)])

        # First request must continue from the saved cursor, not start over.
        assert recorded[0]["after"] == 500
        assert [r["id"] for r in rows] == [499, 498]

    def test_saves_only_already_fetched_cursors_after_yield(self) -> None:
        # Force a mid-stream batch flush by exceeding the batcher's row threshold, then assert we never
        # persist a cursor we haven't fetched from yet (the "save current page, not next" invariant) —
        # otherwise a crash would skip rows still buffered.
        manager = _FakeResumableManager()
        pages = [
            _page(_rows(10000 - i * PAGE_SIZE, PAGE_SIZE), next_cursor=10000 - i * PAGE_SIZE - 99) for i in range(30)
        ]
        pages.append(_page(_rows(10000 - 30 * PAGE_SIZE, 10), next_cursor=1))
        rows, recorded = self._run(manager, pages)

        assert len(rows) == 30 * PAGE_SIZE + 10
        assert manager.saved, "expected at least one mid-stream save once the batch threshold was crossed"
        fetched_afters = {r["after"] for r in recorded}
        assert all(saved.after in fetched_afters for saved in manager.saved)


class TestDocusealSourceResponse:
    @parameterized.expand(["templates", "submissions", "submitters"])
    def test_source_response_shape(self, endpoint: str) -> None:
        response = docuseal_source(
            api_key="tok",
            region="us",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=_FakeResumableManager(),  # type: ignore[arg-type]
        )

        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        # Rows arrive newest-first, so the pipeline must not assume ascending order.
        assert response.sort_mode == "desc"
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["created_at"]
