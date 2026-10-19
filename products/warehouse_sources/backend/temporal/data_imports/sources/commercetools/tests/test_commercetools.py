from datetime import UTC, date, datetime

import pytest
from unittest.mock import MagicMock

from products.warehouse_sources.backend.temporal.data_imports.sources.commercetools.commercetools import (
    MAX_OFFSET,
    PAGE_SIZE,
    CommercetoolsResumeConfig,
    _format_last_modified,
    _validate_path_component,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.commercetools.settings import (
    COMMERCETOOLS_ENDPOINTS,
    ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.commercetools.source import CommercetoolsSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.commercetools import (
    CommercetoolsSourceConfig,
)


def _driver() -> SourceDriver:
    return SourceDriver(
        CommercetoolsSource(),
        CommercetoolsSourceConfig(
            region="us-central1.gcp",
            project_key="proj",
            client_id="id",
            client_secret="secret",
        ),
    )


def _token_response(token: str = "the-token") -> ScriptedResponse:
    return ScriptedResponse(json={"access_token": token, "token_type": "Bearer", "expires_in": 172800})


def _page_response(items: list[dict[str, str]]) -> ScriptedResponse:
    return ScriptedResponse(json={"limit": PAGE_SIZE, "offset": 0, "count": len(items), "results": items})


class TestUrlHelpers:
    @pytest.mark.parametrize("value", ["", "bad value", "x/y", "x?y", "../up"])
    def test_invalid_path_components_raise(self, value):
        with pytest.raises(ValueError):
            _validate_path_component(value, "test")

    def test_build_url_full_refresh(self):
        result = _driver().run("orders", [_token_response(), _page_response([])])

        assert result.raised is None
        request = result.requests[1]
        assert request.param("limit") == str(PAGE_SIZE)
        assert request.param("offset") == "0"
        assert request.param("sort") == "lastModifiedAt asc"
        assert request.param("withTotal") == "false"
        assert request.param("where") is None


class TestFormatLastModified:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2024, 1, 2, 3, 4, 5, 123000, tzinfo=UTC), "2024-01-02T03:04:05.123Z"),
            (datetime(2024, 1, 2, 3, 4, 5), "2024-01-02T03:04:05.000Z"),
            (date(2024, 1, 2), "2024-01-02T00:00:00.000Z"),
            ("2024-01-02T03:04:05.000Z", "2024-01-02T03:04:05.000Z"),
        ],
    )
    def test_format_values(self, value, expected):
        assert _format_last_modified(value) == expected


class TestValidateCredentials:
    def test_valid_when_token_mints(self):
        with scripted_network([_token_response()]) as network:
            assert validate_credentials("us-central1.gcp", "my-project", "id", "secret") is True

        assert [request.method for request in network.requests_log] == ["POST"]
        assert [request.path for request in network.requests_log] == ["/oauth/token"]

    def test_invalid_when_token_mint_fails(self):
        with scripted_network([ScriptedResponse(status=401)]) as network:
            assert validate_credentials("us-central1.gcp", "my-project", "id", "secret") is False

        assert [request.path for request in network.requests_log] == ["/oauth/token"]

    def test_invalid_project_key_rejected_without_request(self):
        with scripted_network([]) as network:
            assert validate_credentials("us-central1.gcp", "bad key!", "id", "secret") is False

        assert network.requests_log == []


class TestGetRows:
    def test_paginates_with_offset_until_short_page(self):
        full_page = [{"id": str(i), "lastModifiedAt": "2024-01-01T00:00:00.000Z"} for i in range(PAGE_SIZE)]
        last = {"id": "last", "lastModifiedAt": "2024-01-02T00:00:00.000Z"}

        result = _driver().run("orders", [_token_response(), _page_response(full_page), _page_response([last])])

        assert result.raised is None
        assert result.items == [full_page, [last]]
        assert result.saved_states == [CommercetoolsResumeConfig(anchor=None, offset=PAGE_SIZE)]
        assert result.params("offset") == [None, "0", str(PAGE_SIZE)]

    def test_reanchors_at_offset_cap(self):
        pages = []
        for page_index in range(MAX_OFFSET // PAGE_SIZE):
            pages.append(
                _page_response(
                    [
                        {"id": f"{page_index}-{i}", "lastModifiedAt": f"2024-01-01T00:00:{page_index:02d}.000Z"}
                        for i in range(PAGE_SIZE)
                    ]
                )
            )
        # After re-anchoring, one short page ends the scan.
        pages.append(_page_response([{"id": "post-anchor", "lastModifiedAt": "2024-01-02T00:00:00.000Z"}]))

        result = _driver().run("orders", [_token_response(), *pages])

        assert result.raised is None
        assert len(result.items) == MAX_OFFSET // PAGE_SIZE + 1
        # The window re-anchored on the latest lastModifiedAt with offset reset.
        assert result.requests[-1].param("where") == 'lastModifiedAt >= "2024-01-01T00:00:19.000Z"'
        assert result.requests[-1].param("offset") == "0"

    def test_non_advancing_anchor_stops_at_cap(self):
        same_ts = "2024-01-01T00:00:00.000Z"
        pages = [
            _page_response([{"id": f"{p}-{i}", "lastModifiedAt": same_ts} for i in range(PAGE_SIZE)])
            for p in range(MAX_OFFSET // PAGE_SIZE)
        ]
        logger = MagicMock()

        result = _driver().run(
            "orders",
            [_token_response(), *pages],
            resume_state=CommercetoolsResumeConfig(anchor=same_ts, offset=0),
            logger=logger,
        )

        # All cap pages yielded, then the scan stops instead of looping.
        assert result.raised is None
        assert len(result.items) == MAX_OFFSET // PAGE_SIZE
        assert len(result.requests) == MAX_OFFSET // PAGE_SIZE + 1
        logger.error.assert_called_once()

    def test_incremental_starts_from_watermark_anchor(self):
        result = _driver().run(
            "orders",
            [_token_response(), _page_response([])],
            incremental_field="lastModifiedAt",
            db_incremental_field_last_value=datetime(2024, 1, 2, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.requests[1].param("where") == 'lastModifiedAt >= "2024-01-02T00:00:00.000Z"'

    def test_remints_token_on_401(self):
        row = {"id": "1"}
        result = _driver().run(
            "orders",
            [_token_response("first"), ScriptedResponse(status=401), _token_response("second"), _page_response([row])],
        )

        assert result.raised is None
        assert result.items == [[row]]
        assert result.paths == ["/oauth/token", "/proj/orders", "/oauth/token", "/proj/orders"]
        assert result.requests[1].headers["authorization"] == "Bearer first"
        assert result.requests[3].headers["authorization"] == "Bearer second"

    def test_resumes_from_saved_state(self):
        result = _driver().run(
            "orders",
            [_token_response(), _page_response([])],
            resume_state=CommercetoolsResumeConfig(anchor="2024-01-01T00:00:00.000Z", offset=1500),
        )

        assert result.raised is None
        assert result.requests[1].param("where") == 'lastModifiedAt >= "2024-01-01T00:00:00.000Z"'
        assert result.requests[1].param("offset") == "1500"

    def test_empty_response_stops_without_saving_state(self):
        result = _driver().run("orders", [_token_response(), _page_response([])])

        assert result.raised is None
        assert result.items == []
        assert result.saved_states == []


class TestCommercetoolsSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint):
        config = COMMERCETOOLS_ENDPOINTS[endpoint]
        result = _driver().run(endpoint, [_token_response(), _page_response([])])

        assert result.raised is None
        assert result.response is not None
        assert result.response.name == endpoint
        assert result.response.primary_keys == [config.primary_key]
        assert result.response.sort_mode == "asc"
        assert result.response.partition_mode == "datetime"
        assert result.response.partition_keys == ["createdAt"]

    @pytest.mark.parametrize("config", list(COMMERCETOOLS_ENDPOINTS.values()))
    def test_paths_are_kebab_case_resource_paths(self, config):
        # Schema names are snake_case but commercetools resource paths are kebab-case,
        # so a path derived from the name (/customer_groups) 404s at sync time.
        assert config.path.startswith("/")
        assert "_" not in config.path
