from typing import Any

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    Script,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.smartsheet import (
    SmartsheetSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.smartsheet.settings import (
    ENDPOINTS,
    SMARTSHEET_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.smartsheet.smartsheet import (
    PAGE_SIZE,
    SmartsheetResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.smartsheet.source import SmartsheetSource


def _response(items: list[dict[str, Any]], total_pages: int) -> ScriptedResponse:
    return ScriptedResponse(
        json={"pageNumber": 1, "pageSize": PAGE_SIZE, "totalPages": total_pages, "data": items},
    )


def _run(endpoint: str, script: Script, **inputs: Any) -> DriveResult:
    return SourceDriver(SmartsheetSource(), SmartsheetSourceConfig(access_token="token")).run(
        endpoint, script, **inputs
    )


class TestPagination:
    def test_paginates_through_total_pages(self) -> None:
        result = _run(
            "sheets", [_response([{"id": 1}, {"id": 2}], total_pages=2), _response([{"id": 3}], total_pages=2)]
        )

        assert [r["id"] for r in result.rows] == [1, 2, 3]
        # Each request asks for an explicit ascending page number plus the fixed page size.
        assert result.params("page") == ["1", "2"]
        assert result.requests[0].param("pageSize") == str(PAGE_SIZE)
        # State is saved once — only while a further page remains — pointing at the next page.
        assert result.saved_states == [SmartsheetResumeConfig(next_page=2)]

    def test_resumes_from_saved_page(self) -> None:
        result = _run(
            "sheets",
            [_response([{"id": 9}], total_pages=3)],
            resume_state=SmartsheetResumeConfig(next_page=3),
        )

        assert result.params("page")[0] == "3"


class TestSmartsheetSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint) -> None:
        config = SMARTSHEET_ENDPOINTS[endpoint]
        response = _run(endpoint, always(_response([], total_pages=1))).response

        expected_keys = config.primary_key if isinstance(config.primary_key, list) else [config.primary_key]
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == expected_keys
        assert response.sort_mode == "asc"
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_format == "week"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    @pytest.mark.parametrize("config", list(SMARTSHEET_ENDPOINTS.values()))
    def test_partition_keys_are_stable_creation_fields(self, config) -> None:
        # Never partition on a mutable field like modifiedAt.
        if config.partition_key:
            assert config.partition_key == "createdAt"


class TestValidateCredentials:
    def test_validate_credentials_probes_users_me(self) -> None:
        with scripted_network(always(ScriptedResponse(status=200))) as network:
            validate_credentials("token")

        assert [request.url for request in network.requests_log] == ["https://api.smartsheet.com/2.0/users/me"]
        assert network.session_options[0]["redact_values"] == ("token",)
