from typing import Any

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.ortto import OrttoSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.ortto.ortto import (
    OrttoResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.ortto.settings import (
    ACCOUNT_BUILTIN_FIELDS,
    ENDPOINTS,
    ORTTO_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.ortto.source import OrttoSource


def _driver() -> SourceDriver:
    return SourceDriver(OrttoSource(), OrttoSourceConfig(api_key="key", region="global"))


def _contacts_page(
    contacts: list[dict[str, Any]], has_more: bool, next_offset: int = 0, cursor_id: str | None = None
) -> dict[str, Any]:
    return {"contacts": contacts, "has_more": has_more, "next_offset": next_offset, "cursor_id": cursor_id}


class TestValidateCredentials:
    def test_probes_region_specific_host(self) -> None:
        with scripted_network([ScriptedResponse()]) as network:
            assert validate_credentials("eu", "key") is True

        assert network.requests_log[0].url == "https://api.eu.ap3api.com/v1/person/custom-field/get"


class TestGetRowsCursorPagination:
    def test_paginates_with_cursor_until_has_more_is_false(self) -> None:
        result = _driver().run(
            "people",
            [
                ScriptedResponse(json={"fields": []}),
                ScriptedResponse(
                    json=_contacts_page([{"id": "p1"}], has_more=True, next_offset=500, cursor_id="cur-1")
                ),
                ScriptedResponse(json=_contacts_page([{"id": "p2"}], has_more=False)),
            ],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["p1", "p2"]
        second_page_body = result.requests[2].json()
        assert second_page_body["offset"] == 500
        assert second_page_body["cursor_id"] == "cur-1"
        # State saved once, after the first page yielded.
        assert result.saved_states == [OrttoResumeConfig(next_offset=500, cursor_id="cur-1")]

    def test_resumes_from_saved_offset_and_cursor(self) -> None:
        result = _driver().run(
            "people",
            [
                ScriptedResponse(json={"fields": []}),
                ScriptedResponse(json=_contacts_page([{"id": "p3"}], has_more=False)),
            ],
            resume_state=OrttoResumeConfig(next_offset=1000, cursor_id="cur-9"),
        )

        assert result.raised is None
        page_body = result.requests[1].json()
        assert page_body["offset"] == 1000
        assert page_body["cursor_id"] == "cur-9"

    def test_accounts_use_account_builtin_fields(self) -> None:
        result = _driver().run(
            "accounts",
            [
                ScriptedResponse(json={"fields": [{"id": "str:oc:industry"}]}),
                ScriptedResponse(json={"accounts": [{"id": "a1"}], "has_more": False}),
            ],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["a1"]
        page_body = result.requests[1].json()
        assert page_body["fields"] == [*ACCOUNT_BUILTIN_FIELDS, "str:oc:industry"]


class TestGetRowsOffsetPagination:
    def test_audiences_paginate_by_offset_until_short_page(self) -> None:
        page_size = ORTTO_ENDPOINTS["audiences"].page_size
        full_page = [{"id": f"aud-{i}"} for i in range(page_size)]
        result = _driver().run(
            "audiences",
            [ScriptedResponse(json=full_page), ScriptedResponse(json=[{"id": "aud-last"}])],
        )

        assert result.raised is None
        assert [len(batch) for batch in result.items] == [page_size, 1]
        second_body = result.requests[1].json()
        assert second_body["offset"] == page_size
        assert "fields" not in second_body
        assert result.saved_states == [OrttoResumeConfig(next_offset=page_size)]


class TestGetRowsSingleRequest:
    def test_person_custom_fields_are_flattened(self) -> None:
        result = _driver().run(
            "person_custom_fields",
            [
                ScriptedResponse(
                    json={"fields": [{"field": {"id": "int:cm:rating", "name": "Rating"}, "tracked_value": False}]}
                )
            ],
        )

        assert result.raised is None
        assert result.items == [[{"id": "int:cm:rating", "name": "Rating", "tracked_value": False}]]


class TestOrttoSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint: str) -> None:
        result = _driver().run(endpoint, always(ScriptedResponse(json={})))

        assert result.raised is None
        assert result.response is not None
        assert result.response.name == endpoint
        assert result.response.primary_keys == ["id"]
        assert result.response.partition_mode is None
        assert result.response.partition_keys is None
