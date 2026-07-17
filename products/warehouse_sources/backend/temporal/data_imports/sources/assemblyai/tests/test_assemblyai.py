from typing import Any

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.assemblyai.assemblyai import (
    AssemblyAIResumeConfig,
    _pinned_url,
    assemblyai_source,
    base_url_for_region,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.assemblyai.settings import ENDPOINTS

US_LIST_URL = "https://api.assemblyai.com/v2/transcript?limit=200"


def _make_manager(resume_state: AssemblyAIResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _resp(json_body: Any, status: int = 200) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.json.return_value = json_body
    resp.status_code = status
    resp.ok = status < 400
    return resp


def _list_page(items: list[dict[str, Any]], next_url: str | None) -> dict[str, Any]:
    return {"transcripts": items, "page_details": {"next_url": next_url}}


def _url_router(responses: dict[str, dict[str, Any]]) -> Any:
    """Return a session.get side_effect that maps each requested URL to a mocked response."""

    def fake_get(url: str, headers: Any = None, timeout: Any = None) -> mock.MagicMock:
        return _resp(responses[url])

    return fake_get


class TestBaseUrlForRegion:
    @pytest.mark.parametrize(
        "region, expected",
        [
            ("us", "https://api.assemblyai.com"),
            ("eu", "https://api.eu.assemblyai.com"),
            ("EU", "https://api.eu.assemblyai.com"),
            (None, "https://api.assemblyai.com"),
            ("unknown", "https://api.assemblyai.com"),
        ],
    )
    def test_base_url_for_region(self, region: str | None, expected: str) -> None:
        assert base_url_for_region(region) == expected


class TestPinnedUrl:
    @pytest.mark.parametrize(
        "url, expected",
        [
            (
                "https://api.assemblyai.com/v2/transcript?before_id=abc",
                "https://api.assemblyai.com/v2/transcript?before_id=abc",
            ),
            ("/v2/transcript?before_id=abc", "https://api.assemblyai.com/v2/transcript?before_id=abc"),
        ],
    )
    def test_pinned_url_keeps_same_host(self, url: str, expected: str) -> None:
        assert _pinned_url("https://api.assemblyai.com", url) == expected

    @pytest.mark.parametrize(
        "url",
        [
            # A tampered next_url must not redirect the credential-bearing request off the base host.
            "https://evil.example.com/v2/transcript",
            "http://api.assemblyai.com/v2/transcript",  # scheme downgrade
            "https://api.eu.assemblyai.com/v2/transcript",  # different region host
        ],
    )
    def test_pinned_url_rejects_other_hosts(self, url: str) -> None:
        with pytest.raises(ValueError):
            _pinned_url("https://api.assemblyai.com", url)


class TestValidateCredentials:
    @pytest.mark.parametrize("status_code, expected", [(200, True), (401, False), (403, False), (500, False)])
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.assemblyai.assemblyai.make_tracked_session"
    )
    def test_status_mapping(self, mock_session: mock.MagicMock, status_code: int, expected: bool) -> None:
        mock_session.return_value.get.return_value = _resp({}, status=status_code)
        assert validate_credentials("key", "us") is expected

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.assemblyai.assemblyai.make_tracked_session"
    )
    def test_swallows_exceptions(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("key", "us") is False

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.assemblyai.assemblyai.make_tracked_session"
    )
    def test_eu_region_probes_eu_host(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.return_value = _resp({}, status=200)
        validate_credentials("key", "eu")
        called_url = mock_session.return_value.get.call_args.args[0]
        assert called_url.startswith("https://api.eu.assemblyai.com/v2/transcript")


class TestGetRows:
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.assemblyai.assemblyai.make_tracked_session"
    )
    def test_lists_then_hydrates_each_transcript(self, mock_session: mock.MagicMock) -> None:
        next_url = "https://api.assemblyai.com/v2/transcript?limit=200&before_id=t2"
        responses = {
            US_LIST_URL: _list_page([{"id": "t1"}, {"id": "t2"}], next_url),
            "https://api.assemblyai.com/v2/transcript/t1": {"id": "t1", "text": "hello", "status": "completed"},
            "https://api.assemblyai.com/v2/transcript/t2": {"id": "t2", "text": "world", "status": "completed"},
            next_url: _list_page([{"id": "t3"}], None),
            "https://api.assemblyai.com/v2/transcript/t3": {"id": "t3", "text": "again", "status": "completed"},
        }
        mock_session.return_value.get.side_effect = _url_router(responses)

        manager = _make_manager()
        batches = list(get_rows("key", "us", "transcripts", mock.MagicMock(), manager))

        rows = [row for batch in batches for row in batch]
        # Rows are the hydrated full objects, not the list summaries.
        assert [r["id"] for r in rows] == ["t1", "t2", "t3"]
        assert all("text" in r for r in rows)

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.assemblyai.assemblyai.make_tracked_session"
    )
    def test_saves_state_after_each_page_only_when_more_remain(self, mock_session: mock.MagicMock) -> None:
        next_url = "https://api.assemblyai.com/v2/transcript?limit=200&before_id=t1"
        responses = {
            US_LIST_URL: _list_page([{"id": "t1"}], next_url),
            "https://api.assemblyai.com/v2/transcript/t1": {"id": "t1", "text": "hello"},
            next_url: _list_page([{"id": "t2"}], None),
            "https://api.assemblyai.com/v2/transcript/t2": {"id": "t2", "text": "world"},
        }
        mock_session.return_value.get.side_effect = _url_router(responses)

        manager = _make_manager()
        list(get_rows("key", "us", "transcripts", mock.MagicMock(), manager))

        # Only the first page has a next_url, so state is saved exactly once, pointing at page two.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0].next_url == next_url

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.assemblyai.assemblyai.make_tracked_session"
    )
    def test_resumes_from_saved_state(self, mock_session: mock.MagicMock) -> None:
        resume_url = "https://api.assemblyai.com/v2/transcript?limit=200&before_id=resume"
        responses = {
            resume_url: _list_page([{"id": "r1"}], None),
            "https://api.assemblyai.com/v2/transcript/r1": {"id": "r1", "text": "resumed"},
        }
        mock_session.return_value.get.side_effect = _url_router(responses)

        manager = _make_manager(AssemblyAIResumeConfig(next_url=resume_url))
        batches = list(get_rows("key", "us", "transcripts", mock.MagicMock(), manager))

        rows = [row for batch in batches for row in batch]
        assert [r["id"] for r in rows] == ["r1"]
        # The initial list URL must never be requested when resuming.
        requested = [call.args[0] for call in mock_session.return_value.get.call_args_list]
        assert US_LIST_URL not in requested

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.assemblyai.assemblyai.make_tracked_session"
    )
    def test_empty_list_yields_nothing(self, mock_session: mock.MagicMock) -> None:
        responses = {US_LIST_URL: _list_page([], None)}
        mock_session.return_value.get.side_effect = _url_router(responses)

        manager = _make_manager()
        batches = list(get_rows("key", "us", "transcripts", mock.MagicMock(), manager))

        assert batches == []
        manager.save_state.assert_not_called()


class TestAssemblyAISource:
    def test_endpoints_inventory(self) -> None:
        assert ENDPOINTS == ("transcripts",)

    def test_source_response_shape(self) -> None:
        response = assemblyai_source("key", "us", "transcripts", mock.MagicMock(), _make_manager())
        assert response.name == "transcripts"
        assert response.primary_keys == ["id"]
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["created"]
        # The list endpoint returns newest-first and exposes no ascending sort.
        assert response.sort_mode == "desc"
