import base64
from datetime import UTC, date, datetime
from typing import Any

import pytest

from products.warehouse_sources.sources.sdk.testing import ScriptedResponse, SourceDriver, always, scripted_network
from products.warehouse_sources.sources.shutterstock._config import (
    ShutterstockAuthMethodConfig,
    ShutterstockSourceConfig,
)
from products.warehouse_sources.sources.shutterstock.settings import ENDPOINTS, SHUTTERSTOCK_ENDPOINTS
from products.warehouse_sources.sources.shutterstock.shutterstock import (
    ShutterstockAuth,
    ShutterstockResumeConfig,
    _format_start_date,
    check_endpoint_access,
)
from products.warehouse_sources.sources.shutterstock.source import ShutterstockSource

BASIC_AUTH = ShutterstockAuth(consumer_key="ck", consumer_secret="cs")
TOKEN_AUTH = ShutterstockAuth(access_token="tok")

BASIC_CONFIG = ShutterstockSourceConfig(
    auth_method=ShutterstockAuthMethodConfig(selection="api_key", consumer_key="ck", consumer_secret="cs")
)
TOKEN_CONFIG = ShutterstockSourceConfig(
    auth_method=ShutterstockAuthMethodConfig(selection="access_token", access_token="tok")
)


def _page(items: list[dict[str, Any]]) -> ScriptedResponse:
    return ScriptedResponse(json={"data": items, "page": 1, "per_page": 100, "total_count": 999})


def _driver(config: ShutterstockSourceConfig = BASIC_CONFIG) -> SourceDriver:
    return SourceDriver(ShutterstockSource(), config)


class TestFormatStartDate:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (None, None),
            (datetime(2026, 3, 4, 22, 13, 20, 123456, tzinfo=UTC), "2026-03-04T22:13:20+00:00"),
            (date(2026, 3, 4), "2026-03-04T00:00:00+00:00"),
            ("2026-03-04T22:13:20+00:00", "2026-03-04T22:13:20+00:00"),
            ("", None),
        ],
    )
    def test_format_start_date(self, value: Any, expected: str | None) -> None:
        assert _format_start_date(value) == expected


class TestCredentialProbes:
    @pytest.mark.parametrize(
        "endpoint, status_code, expect_reason, expect_scope",
        [
            ("image_licenses", 200, False, None),
            ("image_licenses", 403, True, "licenses.view"),
            ("image_collections", 401, True, "collections.view"),
            ("subscriptions", 403, True, "purchases.view"),
            ("images_updated", 401, True, None),
            # A throttle or server blip is not a missing scope — the table stays selectable.
            ("image_licenses", 429, False, None),
            ("image_licenses", 500, False, None),
            ("image_collection_items", 403, True, "collections.view"),
            ("video_collection_items", 200, False, None),
        ],
    )
    def test_check_endpoint_access(
        self,
        endpoint: str,
        status_code: int,
        expect_reason: bool,
        expect_scope: str | None,
    ) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code))) as network:
            reason = check_endpoint_access(BASIC_AUTH, endpoint)

        if endpoint.endswith("_collection_items"):
            media = "images" if endpoint.startswith("image_") else "videos"
            assert {request.path for request in network.requests_log} == {f"/v2/{media}/collections"}

        if not expect_reason:
            assert reason is None
        else:
            assert reason is not None
            if expect_scope:
                assert expect_scope in reason


class TestGetRows:
    def test_paginates_until_empty_page_and_checkpoints(self) -> None:
        result = _driver().run("images_updated", [_page([{"id": "1"}, {"id": "2"}]), _page([])])

        assert [item["id"] for item in result.rows] == ["1", "2"]
        assert result.params("page") == ["1", "2"]
        assert result.params("per_page")[0] == "500"
        # State saved once (after page 1, pointing at page 2); the empty page ends the run.
        assert result.saved_states == [ShutterstockResumeConfig(page=2)]

    def test_basic_auth_uses_consumer_key_and_secret(self) -> None:
        result = _driver(BASIC_CONFIG).run("images_updated", [_page([])])

        expected = base64.b64encode(b"ck:cs").decode()
        assert result.requests[0].headers["authorization"] == f"Basic {expected}"

    def test_access_token_uses_bearer_auth(self) -> None:
        result = _driver(TOKEN_CONFIG).run("image_licenses", [_page([])])

        assert result.requests[0].headers["authorization"] == "Bearer tok"

    @pytest.mark.parametrize("endpoint", ["image_licenses", "audio_licenses"])
    @pytest.mark.parametrize("incremental", [True, False])
    def test_incremental_request_carries_watermark_and_ascending_sort(self, endpoint: str, incremental: bool) -> None:
        result = _driver().run(
            endpoint,
            [
                _page([{"id": "license-a", "download_time": "2026-01-02T00:00:00+00:00"}]),
                _page([{"id": "license-b", "download_time": "2026-01-03T00:00:00+00:00"}]),
                _page([]),
            ],
            should_use_incremental_field=incremental,
            db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["license-a", "license-b"]
        assert result.params("start_date") == (["2026-01-01T00:00:00+00:00"] * 3 if incremental else [None] * 3)
        assert result.params("sort") == ["oldest"] * 3
        assert result.params("per_page") == ["200"] * 3
        assert result.params("page") == ["1", "2", "3"]

    @pytest.mark.parametrize(
        "media, endpoint", [("images", "image_collection_items"), ("videos", "video_collection_items")]
    )
    def test_collection_members_keep_parent_ids_and_resume_child_pages(self, media: str, endpoint: str) -> None:
        parent_path = f"/v2/{media}/collections"
        first_path = f"{parent_path}/collection-a/items"
        second_path = f"{parent_path}/collection-b/items"
        result = _driver(TOKEN_CONFIG).run(
            endpoint,
            [
                _page([{"id": "collection-a"}]),
                _page([{"id": "shared-item"}]),
                _page([]),
                _page([{"id": "collection-b"}]),
                _page([{"id": "shared-item"}]),
                ScriptedResponse(status=400),
            ],
        )

        assert result.raised is not None
        assert result.rows == [
            {"id": "shared-item", "collection_id": "collection-a"},
            {"id": "shared-item", "collection_id": "collection-b"},
        ]
        assert result.paths == [parent_path, first_path, first_path, parent_path, second_path, second_path]
        assert result.params("page") == ["1", "1", "2", "2", "1", "2"]
        assert result.params("per_page") == ["100", "150", "150", "100", "150", "150"]
        assert result.final_state is not None
        assert result.final_state.fanout_state["child_state"] == {"page": 2}
        assert result.committed_states
        assert result.response is not None
        assert result.response.primary_keys == ["collection_id", "id"]
        assert result.response.sort_mode is None

        resumed = _driver(TOKEN_CONFIG).run(
            endpoint,
            [
                _page([{"id": "collection-a"}]),
                _page([{"id": "collection-b"}]),
                _page([{"id": "next-item"}]),
                _page([]),
                _page([]),
            ],
            resume_state=result.final_state,
        )

        assert resumed.raised is None
        assert resumed.rows == [{"id": "next-item", "collection_id": "collection-b"}]
        assert resumed.paths == [parent_path, parent_path, second_path, second_path, parent_path]
        assert resumed.params("page") == ["1", "2", "2", "3", "3"]

    @pytest.mark.parametrize("endpoint", ["audio_genres", "audio_instruments", "audio_moods"])
    def test_audio_taxonomy_strings_become_named_rows(self, endpoint: str) -> None:
        result = _driver().run(
            endpoint, [ScriptedResponse(json={"data": ["Sample / Category", "Sample > Subcategory"]})]
        )

        assert result.raised is None
        assert result.rows == [{"name": "Sample / Category"}, {"name": "Sample > Subcategory"}]
        assert len(result.requests) == 1
        assert result.paths == [f"/v2/audio/{endpoint.removeprefix('audio_')}"]
        assert result.params("page") == [None]
        assert result.params("per_page") == [None]
        assert result.response is not None
        assert result.response.primary_keys == ["name"]

    def test_unpaginated_endpoint_makes_a_single_request(self) -> None:
        result = _driver().run("subscriptions", [_page([{"id": "s1"}, {"id": "s2"}])])

        assert len(result.requests) == 1
        assert [item["id"] for item in result.rows] == ["s1", "s2"]
        assert result.params("page") == [None]
        assert result.params("per_page") == [None]
        assert result.saved_states == []


class TestShutterstockSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint: str) -> None:
        config = SHUTTERSTOCK_ENDPOINTS[endpoint]
        response = _driver().run(endpoint, always(_page([]))).response

        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        assert response.sort_mode == (None if config.fanout or config.string_rows else "asc")
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    @pytest.mark.parametrize("config", list(SHUTTERSTOCK_ENDPOINTS.values()))
    def test_incremental_endpoints_sort_ascending_on_their_cursor(self, config: Any) -> None:
        # An incremental endpoint must sort ascending on its cursor so the watermark advances.
        if config.supports_incremental:
            assert config.cursor_field is not None
            assert config.incremental_fields
            assert config.incremental_fields[0]["field"] == config.cursor_field
