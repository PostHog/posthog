from typing import Any, Optional

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.tavus import TavusSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.tavus import tavus
from products.warehouse_sources.backend.temporal.data_imports.sources.tavus.settings import ENDPOINTS, TAVUS_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.tavus.source import TavusSource
from products.warehouse_sources.backend.temporal.data_imports.sources.tavus.tavus import (
    TAVUS_BASE_URL,
    TavusResumeConfig,
)


def _response(
    items: Optional[list[dict[str, Any]]],
    *,
    total_count: Optional[int] = None,
    drop_data: bool = False,
    status: int = 200,
) -> ScriptedResponse:
    body: dict[str, Any] = {}
    if not drop_data:
        body["data"] = items or []
        if total_count is not None:
            body["total_count"] = total_count
    return ScriptedResponse(status=status, json=body)


def _driver() -> SourceDriver:
    return SourceDriver(TavusSource(), TavusSourceConfig(api_key="tavus-key"))


class TestPagination:
    def test_full_page_then_short_page_progresses_page_param(self) -> None:
        full = [{"video_id": f"v_{i}"} for i in range(100)]
        result = _driver().run(
            "videos",
            [_response(full, total_count=101), _response([{"video_id": "v_last"}], total_count=101)],
        )

        assert [r["video_id"] for r in result.rows] == [*(f"v_{i}" for i in range(100)), "v_last"]
        assert result.params("page") == ["0", "1"]
        assert result.requests[0].param("limit") == "100"
        # Checkpoint saved after the first full page (pointing at page 1); the short page ends it.
        assert result.saved_states == [TavusResumeConfig(next_page=1)]

    def test_stops_when_running_count_reaches_total_on_full_final_page(self, monkeypatch) -> None:
        # Both pages are full (== PAGE_SIZE), so termination relies on total_count, not a short page.
        monkeypatch.setattr(tavus, "PAGE_SIZE", 2)
        result = _driver().run(
            "videos",
            [
                _response([{"video_id": "a"}, {"video_id": "b"}], total_count=4),
                _response([{"video_id": "c"}, {"video_id": "d"}], total_count=4),
            ],
        )

        assert [r["video_id"] for r in result.rows] == ["a", "b", "c", "d"]
        # Page 2 must never be requested; state saved exactly once (after page 0).
        assert len(result.requests) == 2
        assert result.saved_states == [TavusResumeConfig(next_page=1)]

    def test_resumes_from_saved_page(self, monkeypatch) -> None:
        monkeypatch.setattr(tavus, "PAGE_SIZE", 2)
        # Page 0 must never be fetched on resume; the first request targets the saved page.
        result = _driver().run(
            "videos",
            [_response([{"video_id": "c"}], total_count=3)],
            resume_state=TavusResumeConfig(next_page=1),
        )

        assert result.requests[0].param("page") == "1"
        assert [r["video_id"] for r in result.rows] == ["c"]

    def test_unpaginated_endpoint_fetches_once_without_page_params(self) -> None:
        # /memory-stores returns every store with no total_count, so a full page must not trigger page 1.
        stores = [{"memory_store_id": f"m_{i}", "pal_id": "p_1", "participant_tag": f"user_{i}"} for i in range(100)]
        result = _driver().run("memory_stores", [_response(stores)])

        assert len(result.rows) == 100
        assert len(result.requests) == 1
        assert result.requests[0].param("page") is None and result.requests[0].param("limit") is None
        assert result.saved_states == []

    def test_missing_data_key_raises_loudly(self) -> None:
        result = _driver().run("videos", [_response(None, drop_data=True)])

        # A 200 body without "data" means the response shape changed — fail loud, not silently 0 rows.
        assert isinstance(result.raised, ValueError)
        assert "matched nothing" in str(result.raised)


class TestRetryClassification:
    @parameterized.expand([("unauthorized", 401, "Unauthorized"), ("forbidden", 403, "Forbidden")])
    def test_auth_error_raises_matchable_httperror(self, _name, status, reason) -> None:
        result = _driver().run("videos", [_response(None, status=status)])

        assert isinstance(result.raised, requests.HTTPError)
        # The message must carry the stable "{status} Client Error: {reason} for url: <base host>"
        # prefix that TavusSource.get_non_retryable_errors matches on.
        assert f"{status} Client Error: {reason} for url: {TAVUS_BASE_URL}" in str(result.raised)


class TestTavusSourceResponse:
    @parameterized.expand(
        [
            ("videos", "video_id"),
            ("replicas", "replica_id"),
            ("personas", "persona_id"),
            ("conversations", "conversation_id"),
            ("memory_stores", "memory_store_id"),
        ]
    )
    def test_primary_key_matches_endpoint_config(self, endpoint: str, primary_key: str) -> None:
        response = _driver().run(endpoint, always(_response([]))).response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == [primary_key]
        # No endpoint exposes a curl-verified creation field, so none partition.
        assert response.partition_mode is None
        assert response.partition_keys is None

    def test_every_endpoint_uses_a_resource_specific_primary_key(self) -> None:
        assert {name: cfg.primary_keys for name, cfg in TAVUS_ENDPOINTS.items()} == {
            "videos": ["video_id"],
            "replicas": ["replica_id"],
            "personas": ["persona_id"],
            "conversations": ["conversation_id"],
            "memory_stores": ["memory_store_id"],
        }
        assert set(TAVUS_ENDPOINTS) == set(ENDPOINTS)
