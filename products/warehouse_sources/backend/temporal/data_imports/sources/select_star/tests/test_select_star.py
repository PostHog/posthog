from datetime import UTC, datetime
from typing import Any, Optional

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.selectstar import (
    SelectStarSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.select_star.select_star import (
    SelectStarResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.select_star.settings import (
    ENDPOINTS,
    SELECTSTAR_BASE_URL,
    SELECTSTAR_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.select_star.source import SelectStarSource

TABLES_URL = f"{SELECTSTAR_BASE_URL}/v1/tables/"
TAGS_URL = f"{SELECTSTAR_BASE_URL}/v1/tags/"


def _driver() -> SourceDriver:
    return SourceDriver(SelectStarSource(), SelectStarSourceConfig(api_token="tok"))


def _page(results: list[dict[str, Any]], *, next_url: Optional[str] = None) -> ScriptedResponse:
    return ScriptedResponse(json={"count": len(results), "next": next_url, "previous": None, "results": results})


class TestPagination:
    def test_follows_next_url_until_null(self) -> None:
        second = f"{TABLES_URL}?page=2"

        result = _driver().run("Tables", [_page([{"guid": "a"}], next_url=second), _page([{"guid": "b"}])])

        assert result.rows == [{"guid": "a"}, {"guid": "b"}]
        assert result.urls[0].split("?")[0] == TABLES_URL
        assert result.urls[1] == second
        assert result.saved_states == [SelectStarResumeConfig(next_url=second)]

    def test_resumes_from_the_saved_cursor(self) -> None:
        saved = f"{TABLES_URL}?page=7"

        result = _driver().run("Tables", [_page([{"guid": "z"}])], resume_state=SelectStarResumeConfig(next_url=saved))

        assert result.rows == [{"guid": "z"}]
        assert result.urls == [saved]


class TestIncrementalFilter:
    def test_default_incremental_field_used_when_none_selected(self) -> None:
        result = _driver().run(
            "Tables",
            [_page([])],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
        )

        assert result.requests[0].param("updated_on__gte") == "2026-01-01 00:00:00+00:00"


class TestValidateCredentials:
    def test_ok(self) -> None:
        with scripted_network([ScriptedResponse(status=200, json={})]) as network:
            assert validate_credentials("tok") == (True, None)

        assert network.requests_log[0].headers["authorization"] == "Token tok"


class TestSelectStarSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        result = _driver().run(endpoint, [_page([])])

        assert result.response is not None
        assert result.response.name == endpoint
        assert result.response.primary_keys == ["guid"]
        assert result.response.sort_mode == "asc"

    def test_every_endpoint_uses_guid_primary_key(self) -> None:
        assert all(config.primary_keys == ["guid"] for config in SELECTSTAR_ENDPOINTS.values())
        assert set(SELECTSTAR_ENDPOINTS) == set(ENDPOINTS)
