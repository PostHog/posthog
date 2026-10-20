from typing import Any

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.gleif import GleifSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.gleif.gleif import (
    GleifResumeConfig,
    _flatten_json_api_item,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gleif.settings import LEI_RECORDS
from products.warehouse_sources.backend.temporal.data_imports.sources.gleif.source import GleifSource

_LEI_ITEM: dict[str, Any] = {
    "type": "lei-records",
    "id": "984500I2ABE9B792FF06",
    "attributes": {
        "lei": "984500I2ABE9B792FF06",
        "entity": {"legalName": {"name": "DA Digital GmbH", "language": "de"}},
        "registration": {
            "initialRegistrationDate": "2026-05-30T00:00:00Z",
            "lastUpdateDate": "2026-08-17T22:46:53Z",
        },
        "bic": None,
    },
}


class TestFlattenJsonApiItem:
    def test_missing_attributes_key(self) -> None:
        assert _flatten_json_api_item({"id": "abc"}) == {"id": "abc"}


class TestValidateCredentials:
    @pytest.mark.parametrize(("status_code", "expected"), [(429, False)])
    def test_reflects_http_status(self, status_code: int, expected: bool) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code, json={}))) as network:
            assert validate_credentials() is expected

        assert network.requests_log[0].path == "/api/v1/lei-records"
        assert network.requests_log[0].param("page[size]") == "1"


class TestGleifSourceResumeBehavior:
    @staticmethod
    def _driver() -> SourceDriver:
        return SourceDriver(GleifSource(), GleifSourceConfig())

    @staticmethod
    def _page(rows: list[dict[str, Any]], next_url: str | None = None) -> ScriptedResponse:
        body: dict[str, Any] = {"data": rows}
        if next_url is not None:
            body["links"] = {"next": next_url}
        return ScriptedResponse(json=body)

    def test_lei_records_fresh_run_uses_cursor_pagination(self) -> None:
        next_url = "https://api.gleif.org/api/v1/lei-records?page%5Bcursor%5D=abc"
        result = self._driver().run(LEI_RECORDS, [self._page([_LEI_ITEM], next_url), self._page([_LEI_ITEM])])

        assert result.raised is None
        assert result.queries[0] == {
            "page[size]": ("200",),
            "page[cursor]": ("*",),
            "sort": ("registration.lastUpdateDate",),
        }
        # The second request is driven entirely by the response's `links.next` URL.
        assert result.urls[1] == next_url
        assert result.queries[1] == {"page[cursor]": ("abc",)}
        assert result.rows[0]["last_update_date"] == "2026-08-17T22:46:53Z"
        assert result.saved_states == [GleifResumeConfig(next_url=next_url)]

    def test_lei_records_incremental_run_adds_gte_filter(self) -> None:
        result = self._driver().run(
            LEI_RECORDS,
            [self._page([_LEI_ITEM])],
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-08-17T00:00:00Z",
        )

        assert result.raised is None
        assert result.requests[0].param("filter[registration.lastUpdateDate]") == ">=2026-08-17T00:00:00Z"

    def test_resume_seeds_paginator_with_saved_next_url(self) -> None:
        next_url = "https://api.gleif.org/api/v1/lei-records?page%5Bcursor%5D=resumed"
        result = self._driver().run(
            LEI_RECORDS,
            [self._page([_LEI_ITEM])],
            resume_state=GleifResumeConfig(next_url=next_url),
        )

        assert result.raised is None
        assert result.urls == [next_url]
        assert result.queries == [{"page[cursor]": ("resumed",)}]

    def test_does_not_load_state_when_cannot_resume(self) -> None:
        result = self._driver().run(LEI_RECORDS, [self._page([_LEI_ITEM])])

        assert result.raised is None
        assert result.requests[0].param("page[cursor]") == "*"
