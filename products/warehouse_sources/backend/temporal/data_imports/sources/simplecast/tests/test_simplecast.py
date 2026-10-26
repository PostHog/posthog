from typing import Any

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.simplecast import (
    SimpleCastSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.simplecast.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.simplecast.simplecast import (
    PAGE_SIZE,
    SimpleCastResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.simplecast.source import SimpleCastSource


def _envelope(items: list[dict[str, Any]], *, total: int = 1, current: int = 1) -> ScriptedResponse:
    return ScriptedResponse(json={"collection": items, "pages": {"total": total, "current": current}})


def _full_page(start_id: int) -> list[dict[str, Any]]:
    return [{"id": f"p_{start_id + i}"} for i in range(PAGE_SIZE)]


def _driver() -> SourceDriver:
    return SourceDriver(SimpleCastSource(), SimpleCastSourceConfig(api_key="sc-token"))


class TestPagination:
    def test_paginates_and_progresses_offset(self) -> None:
        result = _driver().run(
            "podcasts",
            [_envelope(_full_page(0), total=2, current=1), _envelope([{"id": "p_last"}], total=2, current=2)],
        )

        assert [r["id"] for r in result.rows] == [*(f"p_{i}" for i in range(PAGE_SIZE)), "p_last"]
        assert result.params("offset") == ["0", str(PAGE_SIZE)]
        assert result.params("limit")[0] == str(PAGE_SIZE)
        # Checkpoint saved once after the first full page (points at the next page); short page ends it.
        assert result.saved_states == [SimpleCastResumeConfig(offset=PAGE_SIZE)]

    def test_full_last_page_stops_on_pages_metadata_without_extra_request(self) -> None:
        # A full page whose `pages` metadata marks it as the last page must terminate without paying
        # for an extra empty-page request, and without persisting a resume checkpoint.
        result = _driver().run("podcasts", [_envelope(_full_page(0), total=1, current=1)])

        assert len(result.rows) == PAGE_SIZE
        assert len(result.requests) == 1
        assert result.saved_states == []

    def test_resumes_from_saved_offset(self) -> None:
        result = _driver().run(
            "podcasts",
            [_envelope([{"id": "p_101"}], total=2, current=2)],
            resume_state=SimpleCastResumeConfig(offset=PAGE_SIZE),
        )

        # Offset 0 must never be fetched on resume; the first (only) request starts at the saved offset.
        assert result.params("offset") == [str(PAGE_SIZE)]
        assert [r["id"] for r in result.rows] == ["p_101"]


class TestErrorHandling:
    @parameterized.expand(
        [
            ("bare_list", [{"id": 1}]),
            ("missing_collection", {"pages": {}}),
            ("error_envelope", {"error": "no"}),
        ]
    )
    def test_unexpected_200_body_is_retried_then_raises(self, _name, body) -> None:
        # The client retries a malformed 200 body up to 5 attempts, then reraises.
        result = _driver().run("podcasts", always(ScriptedResponse(json=body)))

        assert result.raised is not None
        assert len(result.requests) == 5

    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    def test_retryable_status_is_retried_then_raises(self, _name, status) -> None:
        result = _driver().run("podcasts", always(ScriptedResponse(status=status, json={})))

        assert result.raised is not None
        assert len(result.requests) == 5

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_error_raises_without_retry(self, _name, status) -> None:
        result = _driver().run("podcasts", [ScriptedResponse(status=status, json={})])

        assert isinstance(result.raised, requests.HTTPError)
        # 4xx is a permanent failure — issued exactly once, never retried.
        assert len(result.requests) == 1


class TestSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        response = _driver().run(endpoint, always(_envelope([]))).response

        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        # No stable creation timestamp is guaranteed across every object, so we don't partition.
        assert response.partition_mode is None
