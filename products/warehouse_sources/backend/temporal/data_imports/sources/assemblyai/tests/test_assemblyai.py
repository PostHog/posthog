import json
from typing import Any
from urllib.parse import urlencode

import pytest
from unittest import mock

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.assemblyai.assemblyai import (
    AssemblyAIResumeConfig,
    _pinned_url,
    assemblyai_source,
    base_url_for_region,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.assemblyai.settings import ENDPOINTS

# RESTClient (list pagination and per-transcript hydration) builds its session via
# make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the assemblyai module.
ASSEMBLYAI_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.assemblyai.assemblyai.make_tracked_session"
)

US_LIST_URL = "https://api.assemblyai.com/v2/transcript?limit=200"


def _make_manager(resume_state: AssemblyAIResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _list_page(items: list[dict[str, Any]], next_url: str | None) -> dict[str, Any]:
    return {"transcripts": items, "page_details": {"next_url": next_url}}


def _wire(session: mock.MagicMock, responses: dict[str, dict[str, Any]]) -> list[str]:
    """Wire a mock session that routes each request to a response body by its full URL.

    URLs are snapshotted at prepare_request time (the params dict is mutated in place across
    pages, so inspecting it after the run would only show the final state).
    """
    session.headers = {}
    requested: list[str] = []

    def _prepare(request: Any) -> mock.MagicMock:
        url = request.url
        if request.params:
            url = f"{url}?{urlencode(request.params)}"
        requested.append(url)
        prepared = mock.MagicMock()
        prepared.url = url
        return prepared

    def _send(prepared: Any) -> Response:
        resp = Response()
        resp.status_code = 200
        resp.url = prepared.url
        resp._content = json.dumps(responses[prepared.url]).encode()
        return resp

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = _send
    return requested


def _batches(api_key: str, region: str | None, endpoint: str, manager: mock.MagicMock) -> list[list[dict[str, Any]]]:
    response = assemblyai_source(api_key, region, endpoint, team_id=1, job_id="j", resumable_source_manager=manager)
    return list(response.items())


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
    @mock.patch(ASSEMBLYAI_SESSION_PATCH)
    def test_status_mapping(self, mock_session: mock.MagicMock, status_code: int, expected: bool) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status_code)
        assert validate_credentials("key", "us") is expected

    @mock.patch(ASSEMBLYAI_SESSION_PATCH)
    def test_swallows_exceptions(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("key", "us") is False

    @mock.patch(ASSEMBLYAI_SESSION_PATCH)
    def test_eu_region_probes_eu_host_with_raw_key(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)
        validate_credentials("key", "eu")
        call = mock_session.return_value.get.call_args
        assert call.args[0].startswith("https://api.eu.assemblyai.com/v2/transcript")
        # AssemblyAI takes the raw API key in Authorization — no "Bearer" prefix.
        assert call.kwargs["headers"]["Authorization"] == "key"


class TestAssemblyAIRows:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_lists_then_hydrates_each_transcript(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        next_url = "https://api.assemblyai.com/v2/transcript?limit=200&before_id=t2"
        requested = _wire(
            session,
            {
                US_LIST_URL: _list_page([{"id": "t1"}, {"id": "t2"}], next_url),
                "https://api.assemblyai.com/v2/transcript/t1": {"id": "t1", "text": "hello", "status": "completed"},
                "https://api.assemblyai.com/v2/transcript/t2": {"id": "t2", "text": "world", "status": "completed"},
                next_url: _list_page([{"id": "t3"}], None),
                "https://api.assemblyai.com/v2/transcript/t3": {"id": "t3", "text": "again", "status": "completed"},
            },
        )

        batches = _batches("key", "us", "transcripts", _make_manager())

        rows = [row for batch in batches for row in batch]
        # Rows are the hydrated full objects, not the list summaries.
        assert [r["id"] for r in rows] == ["t1", "t2", "t3"]
        assert all("text" in r for r in rows)
        assert requested[0] == US_LIST_URL

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_saves_state_after_each_page_only_when_more_remain(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        next_url = "https://api.assemblyai.com/v2/transcript?limit=200&before_id=t1"
        _wire(
            session,
            {
                US_LIST_URL: _list_page([{"id": "t1"}], next_url),
                "https://api.assemblyai.com/v2/transcript/t1": {"id": "t1", "text": "hello"},
                next_url: _list_page([{"id": "t2"}], None),
                "https://api.assemblyai.com/v2/transcript/t2": {"id": "t2", "text": "world"},
            },
        )

        manager = _make_manager()
        _batches("key", "us", "transcripts", manager)

        # Only the first page has a next_url, so state is saved exactly once, pointing at page two.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == AssemblyAIResumeConfig(next_url=next_url)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_state(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        resume_url = "https://api.assemblyai.com/v2/transcript?limit=200&before_id=resume"
        requested = _wire(
            session,
            {
                resume_url: _list_page([{"id": "r1"}], None),
                "https://api.assemblyai.com/v2/transcript/r1": {"id": "r1", "text": "resumed"},
            },
        )

        manager = _make_manager(AssemblyAIResumeConfig(next_url=resume_url))
        batches = _batches("key", "us", "transcripts", manager)

        rows = [row for batch in batches for row in batch]
        assert [r["id"] for r in rows] == ["r1"]
        # The initial list URL must never be requested when resuming.
        assert US_LIST_URL not in requested
        assert requested[0] == resume_url

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_list_yields_nothing(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        _wire(session, {US_LIST_URL: _list_page([], None)})

        manager = _make_manager()
        assert _batches("key", "us", "transcripts", manager) == []
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_page_stops_even_with_next_url(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        _wire(session, {US_LIST_URL: _list_page([], "https://api.assemblyai.com/v2/transcript?before_id=x")})

        manager = _make_manager()
        assert _batches("key", "us", "transcripts", manager) == []
        # The walk ends on the empty page — the advertised next page is never fetched.
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_tampered_next_url_is_rejected(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        _wire(
            session,
            {
                US_LIST_URL: _list_page([{"id": "t1"}], "https://evil.example.com/v2/transcript"),
                "https://api.assemblyai.com/v2/transcript/t1": {"id": "t1", "text": "hello"},
            },
        )

        with pytest.raises(ValueError, match="not on the selected host"):
            _batches("key", "us", "transcripts", _make_manager())

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_tampered_saved_state_is_rejected(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        _wire(session, {})

        manager = _make_manager(AssemblyAIResumeConfig(next_url="https://evil.example.com/v2/transcript"))
        with pytest.raises(ValueError, match="not on the selected host"):
            _batches("key", "us", "transcripts", manager)


class TestAssemblyAISource:
    def test_endpoints_inventory(self) -> None:
        assert ENDPOINTS == ("transcripts",)

    def test_source_response_shape(self) -> None:
        response = assemblyai_source(
            "key", "us", "transcripts", team_id=1, job_id="j", resumable_source_manager=_make_manager()
        )
        assert response.name == "transcripts"
        assert response.primary_keys == ["id"]
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["created"]
        # The list endpoint returns newest-first and exposes no ascending sort.
        assert response.sort_mode == "desc"
