import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.attio.attio import (
    AttioResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.attio.settings import ATTIO_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.attio.source import AttioSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.attio import AttioSourceConfig


class TestValidateCredentials:
    def test_non_ascii_key_returns_actionable_message_without_leaking_encoding_error(self):
        # A non-latin-1 key can't be encoded into the Authorization header; the raw
        # UnicodeEncodeError ("'latin-1' codec can't encode ... ordinal not in range(256)")
        # must never surface to the user.
        valid, msg = validate_credentials("bad中key")

        assert valid is False
        assert "Retype it by hand" in (msg or "")
        assert "latin-1" not in (msg or "")
        assert "ordinal not in range" not in (msg or "")


def _page(endpoint: str, start: int, count: int) -> ScriptedResponse:
    primary_key = ATTIO_ENDPOINTS[endpoint].primary_key
    rows = [
        {"id": {"workspace_id": "ws", primary_key: f"row-{i}"}, "created_at": "2024-01-01"}
        for i in range(start, start + count)
    ]
    return ScriptedResponse(json={"data": rows})


class TestAttioResume:
    @staticmethod
    def _driver() -> SourceDriver:
        return SourceDriver(AttioSource(), AttioSourceConfig(api_key="key"))

    @pytest.mark.parametrize("endpoint", ["companies", "people", "deals", "notes", "tasks"])
    def test_fresh_run_stages_next_offset_after_each_page(self, endpoint: str) -> None:
        limit = ATTIO_ENDPOINTS[endpoint].page_size
        responses = [_page(endpoint, 0, limit), _page(endpoint, limit, limit), _page(endpoint, 2 * limit, 3)]

        result = self._driver().run(endpoint, responses)
        is_post = ATTIO_ENDPOINTS[endpoint].method == "POST"

        assert result.raised is None
        assert [request.json()["offset"] if is_post else request.param("offset") for request in result.requests] == [
            offset if is_post else str(offset) for offset in (0, limit, 2 * limit)
        ]
        assert all(
            (request.json()["limit"] if is_post else request.param("limit")) == (limit if is_post else str(limit))
            for request in result.requests
        )
        assert len(result.rows) == 2 * limit + 3
        assert result.rows[-1][ATTIO_ENDPOINTS[endpoint].primary_key] == f"row-{2 * limit + 2}"
        assert result.saved_states == [
            AttioResumeConfig(offset=limit),
            AttioResumeConfig(offset=2 * limit),
        ]

    @pytest.mark.parametrize("endpoint", ["companies", "people", "lists", "notes", "tasks", "workspace_members"])
    def test_resumed_run_starts_from_saved_offset(self, endpoint: str) -> None:
        limit = ATTIO_ENDPOINTS[endpoint].page_size
        responses = [_page(endpoint, 2 * limit, limit), _page(endpoint, 3 * limit, 1)]

        result = self._driver().run(endpoint, responses, resume_state=AttioResumeConfig(offset=2 * limit))
        is_post = ATTIO_ENDPOINTS[endpoint].method == "POST"

        assert result.raised is None
        assert [request.json()["offset"] if is_post else request.param("offset") for request in result.requests] == [
            offset if is_post else str(offset) for offset in (2 * limit, 3 * limit)
        ]
        assert result.rows[0][ATTIO_ENDPOINTS[endpoint].primary_key] == f"row-{2 * limit}"
        assert result.saved_states == [AttioResumeConfig(offset=3 * limit)]

    def test_resumed_query_keeps_sort_order_in_body(self) -> None:
        # Offsets only line up across runs when every run asks for the same order.
        result = self._driver().run(
            "companies", [_page("companies", 500, 1)], resume_state=AttioResumeConfig(offset=500)
        )

        assert result.raised is None
        assert [request.json() for request in result.requests] == [
            {"sorts": [{"attribute": "created_at", "direction": "asc"}], "offset": 500, "limit": 500}
        ]
