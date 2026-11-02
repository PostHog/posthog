from typing import Any

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.boldsign import boldsign
from products.warehouse_sources.backend.temporal.data_imports.sources.boldsign.boldsign import (
    PAGE_SIZE,
    BoldSignResumeConfig,
    _base_url,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.boldsign.settings import BOLDSIGN_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.boldsign.source import BoldSignSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.boldsign import (
    BoldSignSourceConfig,
)


def _driver(api_key: str = "key") -> SourceDriver:
    return SourceDriver(BoldSignSource(), BoldSignSourceConfig(api_key=api_key, region="us"))


def _response(items: list[dict[str, Any]] | None, *, data_key: str = "result") -> ScriptedResponse:
    return ScriptedResponse(json={data_key: items or []})


class TestBaseUrlAndHeaders:
    def test_base_url_rejects_unknown_region(self) -> None:
        with pytest.raises(ValueError):
            _base_url("apac")


class TestPagination:
    def test_empty_first_page_yields_nothing(self) -> None:
        result = _driver().run("documents", [_response([])])

        assert result.raised is None
        assert result.rows == []
        assert len(result.requests) == 1

    @pytest.mark.parametrize(
        "endpoint, param, expected",
        [
            ("templates", "TemplateType", "all"),
            ("contacts", "ContactType", "AllContacts"),
            ("contact_groups", "ContactType", "AllContacts"),
            # PageType has no documented server-side default, so it must be sent explicitly.
            ("behalf_documents", "PageType", "BehalfOfOthers"),
        ],
    )
    def test_endpoints_send_their_widening_params(self, endpoint: str, param: str, expected: str) -> None:
        result = _driver().run(endpoint, [_response([{"documentId": "X1"}])])

        assert result.raised is None
        assert result.requests[0].param(param) == expected

    def test_api_key_supplied_via_framework_auth(self) -> None:
        result = _driver(api_key="secret").run("documents", [_response([{"documentId": "D1"}])])

        # The key rides on the framework's api_key auth (redacted from logs), not a raw header.
        assert result.raised is None
        assert result.requests[0].headers["x-api-key"] == "secret"
        assert result.session_options[0]["redact_values"] == ("secret",)


class TestResume:
    def test_resumes_from_saved_page(self) -> None:
        result = _driver().run(
            "documents",
            [_response([{"documentId": "D5"}])],
            resume_state=BoldSignResumeConfig(page=5, next_cursor=None, records_fetched=400),
        )

        assert result.raised is None
        assert result.params("Page") == ["5"]

    def test_resumes_from_saved_cursor(self) -> None:
        result = _driver().run(
            "documents",
            [_response([{"documentId": "after"}])],
            resume_state=BoldSignResumeConfig(page=1, next_cursor=4242, records_fetched=10_000),
        )

        assert result.raised is None
        assert result.params("Page") == ["1"]
        assert result.params("NextCursor") == ["4242"]


class TestCursorPagination:
    def test_documents_switch_to_cursor_past_record_threshold(self) -> None:
        # Fill exactly the 10k page-cap with full pages, then expect a NextCursor request.
        threshold_pages = boldsign.RECORD_CURSOR_THRESHOLD // PAGE_SIZE
        full_pages = [
            _response([{"documentId": f"D{p}-{i}", "cursor": p * PAGE_SIZE + i} for i in range(PAGE_SIZE)])
            for p in range(threshold_pages)
        ]
        # One more page reached via cursor, then a short page to stop.
        cursor_page = _response([{"documentId": "after-cursor", "cursor": 999999}])

        result = _driver().run("documents", [*full_pages, cursor_page])

        # The cursor passed is the last record's cursor from the final full page, with Page reset.
        expected_cursor = boldsign.RECORD_CURSOR_THRESHOLD - 1
        assert result.raised is None
        assert result.params("NextCursor")[-1] == str(expected_cursor)
        assert result.params("Page")[-1] == "1"
        # The checkpoint written after the final full page carries the cursor position.
        assert result.saved_states[-1] == BoldSignResumeConfig(
            page=1, next_cursor=expected_cursor, records_fetched=boldsign.RECORD_CURSOR_THRESHOLD
        )

    def test_non_cursor_endpoint_stops_at_record_threshold(self) -> None:
        # users/list has no cursor support, so it must stop at the 10k page cap rather than loop.
        threshold_pages = boldsign.RECORD_CURSOR_THRESHOLD // PAGE_SIZE
        full_pages = [_response([{"userId": f"U{p}-{i}"} for i in range(PAGE_SIZE)]) for p in range(threshold_pages)]
        # Provide an extra page that should never be requested.
        responses = [*full_pages, _response([{"userId": "should-not-fetch"}])]

        result = _driver().run("users", responses)

        assert result.raised is None
        assert len(result.requests) == threshold_pages
        assert len(result.rows) == boldsign.RECORD_CURSOR_THRESHOLD


class TestSourceResponse:
    @pytest.mark.parametrize(
        "endpoint, expected_pk",
        [
            ("documents", ["documentId"]),
            ("templates", ["documentId"]),
            ("users", ["userId"]),
            ("teams", ["teamId"]),
            ("contacts", ["id"]),
            ("contact_groups", ["groupId"]),
            ("sender_identities", ["id"]),
            ("brands", ["brandId"]),
            ("team_documents", ["documentId"]),
            ("behalf_documents", ["documentId"]),
            ("custom_fields", ["brandId", "customFieldId"]),
        ],
    )
    def test_primary_keys_per_endpoint(self, endpoint: str, expected_pk: list[str]) -> None:
        data_key = BOLDSIGN_ENDPOINTS[endpoint].data_key
        result = _driver().run(endpoint, [_response([], data_key=data_key)])

        assert result.raised is None
        assert result.response is not None
        assert result.response.name == endpoint
        assert result.response.primary_keys == expected_pk
        # Full refresh: BoldSign timestamps are epoch ints, so no datetime partitioning.
        assert result.response.partition_mode is None
        assert result.response.primary_keys == BOLDSIGN_ENDPOINTS[endpoint].primary_keys


class TestCustomFieldsFanout:
    """`customField/list` needs a brandId, so it fans out over the brands endpoint."""

    def test_fans_out_over_every_brand(self) -> None:
        result = _driver().run(
            "custom_fields",
            [
                _response([{"brandId": "B1"}, {"brandId": "B2"}]),
                _response([{"customFieldId": "F1", "brandId": "B1"}]),
                # The response's own brandId is nullable, so the parent's value must fill it in.
                _response([{"customFieldId": "F2", "brandId": None}]),
            ],
        )

        assert result.raised is None
        assert [url for url in result.urls if "customField" in url] == [
            "https://api.boldsign.com/v1/customField/list?brandId=B1",
            "https://api.boldsign.com/v1/customField/list?brandId=B2",
        ]
        assert result.rows == [
            {"customFieldId": "F1", "brandId": "B1"},
            {"customFieldId": "F2", "brandId": "B2"},
        ]


class TestValidateCredentials:
    def test_probes_the_region_host_with_the_api_key_header(self) -> None:
        with scripted_network([ScriptedResponse(status=200)]) as network:
            validate_credentials("eu", "secret")

        assert network.requests_log[0].url.startswith("https://api-eu.boldsign.com/v1/document/list")
        assert network.requests_log[0].headers["x-api-key"] == "secret"
