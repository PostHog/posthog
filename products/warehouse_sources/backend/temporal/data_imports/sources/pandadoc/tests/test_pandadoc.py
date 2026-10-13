from datetime import UTC, date, datetime

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.pandadoc import (
    PandaDocSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.pandadoc.pandadoc import (
    PAGE_SIZE,
    PandaDocResumeConfig,
    _build_query_params,
    _format_date_filter,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.pandadoc.settings import PANDADOC_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.pandadoc.source import PandaDocSource


class TestFormatDateFilter:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC), "2024-01-02T03:04:05.000000Z"),
            (datetime(2024, 1, 2, 3, 4, 5), "2024-01-02T03:04:05.000000Z"),
            (date(2024, 1, 2), "2024-01-02T00:00:00.000000Z"),
            ("2024-01-02T03:04:05.000000Z", "2024-01-02T03:04:05.000000Z"),
        ],
    )
    def test_format_values(self, value, expected):
        assert _format_date_filter(value) == expected


class TestBuildQueryParams:
    @pytest.mark.parametrize("endpoint", ["templates", "forms", "document_folders", "template_folders"])
    def test_paginated_non_incremental_endpoints_only_count(self, endpoint):
        params = _build_query_params(
            PANDADOC_ENDPOINTS[endpoint],
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
            incremental_field=None,
        )

        assert params == {"count": PAGE_SIZE}


class TestValidateCredentials:
    def test_validate_credentials_sends_api_key_header(self) -> None:
        with scripted_network([ScriptedResponse(json={"results": []})]) as network:
            validate_credentials("key")

        assert network.requests_log[0].headers["authorization"] == "API-Key key"


class TestPagination:
    @staticmethod
    def _driver() -> SourceDriver:
        return SourceDriver(PandaDocSource(), PandaDocSourceConfig(api_key="key"))

    def test_paginates_until_short_page(self) -> None:
        full_page = [{"id": str(i)} for i in range(PAGE_SIZE)]
        result = self._driver().run(
            "documents",
            [ScriptedResponse(json={"results": full_page}), ScriptedResponse(json={"results": [{"id": "last"}]})],
        )

        assert result.raised is None
        assert result.rows[-1] == {"id": "last"}
        assert len(result.rows) == PAGE_SIZE + 1
        assert result.params("page") == ["1", "2"]
        # State saved once, after the first (full) page, pointing at page 2.
        assert result.saved_states == [PandaDocResumeConfig(page=2)]

    def test_resumes_from_saved_page(self) -> None:
        result = self._driver().run(
            "documents",
            [ScriptedResponse(json={"results": [{"id": "9"}]})],
            resume_state=PandaDocResumeConfig(page=5),
        )

        assert result.raised is None
        assert result.params("page") == ["5"]

    def test_incremental_request_includes_filter(self) -> None:
        result = self._driver().run(
            "documents",
            [ScriptedResponse(json={"results": []})],
            incremental_field="date_modified",
            db_incremental_field_last_value=datetime(2024, 1, 1, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.requests[0].param("modified_from") == "2024-01-01T00:00:00.000000Z"
        assert result.requests[0].param("order_by") == "date_modified"
