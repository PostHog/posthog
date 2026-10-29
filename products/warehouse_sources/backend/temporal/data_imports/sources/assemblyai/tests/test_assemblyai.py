from typing import Any

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.assemblyai.assemblyai import (
    AssemblyAIResumeConfig,
    _pinned_url,
    base_url_for_region,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.assemblyai.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.assemblyai.source import AssemblyAISource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.assemblyai import (
    AssemblyAISourceConfig,
)

US_LIST_URL = "https://api.assemblyai.com/v2/transcript?limit=200"


def _driver() -> SourceDriver:
    return SourceDriver(AssemblyAISource(), AssemblyAISourceConfig(api_key="key", region="us"))


def _list_page(items: list[dict[str, Any]], next_url: str | None) -> ScriptedResponse:
    return ScriptedResponse(json={"transcripts": items, "page_details": {"next_url": next_url}})


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
    def test_swallows_exceptions(self) -> None:
        with scripted_network([ConnectionResetError("boom")]):
            assert validate_credentials("key", "us") is False

    def test_eu_region_probes_eu_host_with_raw_key(self) -> None:
        with scripted_network([ScriptedResponse()]) as network:
            validate_credentials("key", "eu")

        assert network.requests_log[0].url.startswith("https://api.eu.assemblyai.com/v2/transcript")
        # AssemblyAI takes the raw API key in Authorization — no "Bearer" prefix.
        assert network.requests_log[0].headers["authorization"] == "key"


class TestAssemblyAIRows:
    def test_lists_then_hydrates_each_transcript(self) -> None:
        next_url = "https://api.assemblyai.com/v2/transcript?limit=200&before_id=t2"
        result = _driver().run(
            "transcripts",
            [
                _list_page([{"id": "t1"}, {"id": "t2"}], next_url),
                ScriptedResponse(json={"id": "t1", "text": "hello", "status": "completed"}),
                ScriptedResponse(json={"id": "t2", "text": "world", "status": "completed"}),
                _list_page([{"id": "t3"}], None),
                ScriptedResponse(json={"id": "t3", "text": "again", "status": "completed"}),
            ],
        )

        assert result.raised is None
        # Rows are the hydrated full objects, not the list summaries.
        assert [row["id"] for row in result.rows] == ["t1", "t2", "t3"]
        assert all("text" in row for row in result.rows)
        assert result.urls == [
            US_LIST_URL,
            "https://api.assemblyai.com/v2/transcript/t1",
            "https://api.assemblyai.com/v2/transcript/t2",
            next_url,
            "https://api.assemblyai.com/v2/transcript/t3",
        ]

    def test_saves_state_after_each_page_only_when_more_remain(self) -> None:
        next_url = "https://api.assemblyai.com/v2/transcript?limit=200&before_id=t1"
        result = _driver().run(
            "transcripts",
            [
                _list_page([{"id": "t1"}], next_url),
                ScriptedResponse(json={"id": "t1", "text": "hello"}),
                _list_page([{"id": "t2"}], None),
                ScriptedResponse(json={"id": "t2", "text": "world"}),
            ],
        )

        assert result.raised is None
        # Only the first page has a next_url, so state is saved exactly once, pointing at page two.
        assert result.saved_states == [AssemblyAIResumeConfig(next_url=next_url)]

    def test_resumes_from_saved_state(self) -> None:
        resume_url = "https://api.assemblyai.com/v2/transcript?limit=200&before_id=resume"
        result = _driver().run(
            "transcripts",
            [
                _list_page([{"id": "r1"}], None),
                ScriptedResponse(json={"id": "r1", "text": "resumed"}),
            ],
            resume_state=AssemblyAIResumeConfig(next_url=resume_url),
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["r1"]
        # The initial list URL must never be requested when resuming.
        assert US_LIST_URL not in result.urls
        assert result.urls[0] == resume_url

    def test_empty_list_yields_nothing(self) -> None:
        result = _driver().run("transcripts", [_list_page([], None)])

        assert result.raised is None
        assert result.rows == []
        assert result.saved_states == []

    def test_empty_page_stops_even_with_next_url(self) -> None:
        result = _driver().run("transcripts", [_list_page([], "https://api.assemblyai.com/v2/transcript?before_id=x")])

        assert result.raised is None
        assert result.rows == []
        # The walk ends on the empty page — the advertised next page is never fetched.
        assert result.urls == [US_LIST_URL]
        assert result.saved_states == []

    def test_tampered_next_url_is_rejected(self) -> None:
        result = _driver().run(
            "transcripts",
            [
                _list_page([{"id": "t1"}], "https://evil.example.com/v2/transcript"),
                ScriptedResponse(json={"id": "t1", "text": "hello"}),
            ],
        )

        assert isinstance(result.raised, ValueError)
        assert "not on the selected host" in str(result.raised)

    def test_tampered_saved_state_is_rejected(self) -> None:
        result = _driver().run(
            "transcripts",
            [],
            resume_state=AssemblyAIResumeConfig(next_url="https://evil.example.com/v2/transcript"),
        )

        assert isinstance(result.raised, ValueError)
        assert "not on the selected host" in str(result.raised)


class TestAssemblyAISource:
    def test_endpoints_inventory(self) -> None:
        assert ENDPOINTS == ("transcripts",)

    def test_source_response_shape(self) -> None:
        result = _driver().run("transcripts", [_list_page([], None)])

        assert result.raised is None
        assert result.response is not None
        assert result.response.name == "transcripts"
        assert result.response.primary_keys == ["id"]
        assert result.response.partition_mode == "datetime"
        assert result.response.partition_keys == ["created"]
        # The list endpoint returns newest-first and exposes no ascending sort.
        assert result.response.sort_mode == "desc"
