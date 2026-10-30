from datetime import UTC, date, datetime
from typing import Any

import pytest

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    route,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.housecallpro import (
    HousecallProSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.housecall_pro.housecall_pro import (
    HousecallProResumeConfig,
    _format_created_at_min,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.housecall_pro.settings import (
    ENDPOINTS,
    HOUSECALL_PRO_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.housecall_pro.source import HousecallProSource


def _driver() -> SourceDriver:
    return SourceDriver(HousecallProSource(), HousecallProSourceConfig(api_key="key"))


def _page(response_key: str, items: list[dict[str, Any]], total_pages: int) -> ScriptedResponse:
    return ScriptedResponse(json={response_key: items, "page": 1, "page_size": 100, "total_pages": total_pages})


class TestFormatCreatedAtMin:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (None, None),
            (datetime(2026, 3, 4, 22, 13, 20, tzinfo=UTC), "2026-03-04T22:13:20Z"),
            (date(2026, 3, 4), "2026-03-04T00:00:00Z"),
            ("2026-03-04T22:13:20Z", "2026-03-04T22:13:20Z"),
            ("", None),
        ],
    )
    def test_format_created_at_min(self, value: Any, expected: str | None) -> None:
        assert _format_created_at_min(value) == expected


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected",
        [
            (200, True),
        ],
    )
    def test_validate_credentials_status_mapping(self, status_code: int, expected: bool) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code))) as network:
            assert validate_credentials("key") is expected

        assert network.requests_log[0].path == "/company"
        assert network.requests_log[0].headers["authorization"] == "Bearer key"


class TestGetRows:
    def test_paginates_by_page_number(self) -> None:
        result = _driver().run(
            "customers",
            [
                _page("customers", [{"id": "1"}, {"id": "2"}], total_pages=2),
                _page("customers", [{"id": "3"}], total_pages=2),
            ],
        )

        assert result.raised is None
        assert [item["id"] for item in result.rows] == ["1", "2", "3"]
        assert result.params("page") == ["1", "2"]
        assert result.params("page_size") == ["100", "100"]
        # State saved once (after page 1, pointing at page 2); page 2 is the last so no save after it.
        assert result.saved_states == [HousecallProResumeConfig(page=2)]

    def test_created_at_min_omitted_when_last_value_missing(self) -> None:
        result = _driver().run(
            "invoices",
            [_page("invoices", [{"id": "1"}], total_pages=1)],
            should_use_incremental_field=True,
            db_incremental_field_last_value=None,
        )

        assert result.raised is None
        assert result.requests[0].param("created_at_min") is None

    @parameterized.expand([("job_appointments", "appointments"), ("job_line_items", "data")])
    def test_job_children_walk_every_jobs_page_and_carry_the_job_id(self, endpoint: str, response_key: str) -> None:
        child_path = HOUSECALL_PRO_ENDPOINTS[endpoint].path
        result = _driver().run(
            endpoint,
            route(
                {
                    "/jobs": [
                        _page("jobs", [{"id": "job_1"}, {"id": "job_2"}], total_pages=2),
                        _page("jobs", [{"id": "job_3"}], total_pages=2),
                    ],
                    child_path.format(job_id="job_1"): [ScriptedResponse(json={response_key: [{"id": "a"}]})],
                    child_path.format(job_id="job_2"): [ScriptedResponse(status=404)],
                    child_path.format(job_id="job_3"): [ScriptedResponse(json={response_key: [{"id": "a"}]})],
                }
            ),
        )

        assert result.raised is None
        assert [(row["job_id"], row["id"]) for row in result.rows] == [("job_1", "a"), ("job_3", "a")]
        assert result.params("page") == ["1", None, None, "2", None]
        assert result.params("page_size") == ["100", None, None, "100", None]
        assert result.saved_states
        assert all(state.page is None and state.fanout_state for state in result.saved_states)

    def test_pipeline_statuses_read_each_resource_type(self) -> None:
        result = _driver().run(
            "pipeline_statuses",
            [
                _page("statuses", [{"id": "s1", "name": "New", "status_type": "open"}], total_pages=1),
                _page("statuses", [], total_pages=0),
                _page("statuses", [{"id": "s1", "name": "Won", "status_type": "closed"}], total_pages=1),
            ],
        )

        assert result.raised is None
        assert result.params("resource_type") == ["lead", "job", "estimate"]
        assert [(row["resource_type"], row["id"], row["name"]) for row in result.rows] == [
            ("lead", "s1", "New"),
            ("estimate", "s1", "Won"),
        ]


class TestHousecallProSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint: str) -> None:
        config = HOUSECALL_PRO_ENDPOINTS[endpoint]
        result = _driver().run(endpoint, always(_page(config.response_key, [], total_pages=1)))
        response = result.response

        assert result.raised is None
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        assert response.sort_mode == "asc"
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    @pytest.mark.parametrize("config", list(HOUSECALL_PRO_ENDPOINTS.values()))
    def test_partition_keys_are_stable_creation_fields(self, config: Any) -> None:
        # Never partition on a mutable field; only stable creation timestamps are allowed.
        if config.partition_key:
            assert config.partition_key == "created_at"

    @pytest.mark.parametrize("config", list(HOUSECALL_PRO_ENDPOINTS.values()))
    def test_incremental_endpoints_have_a_sort_field(self, config: Any) -> None:
        # An incremental endpoint must sort ascending on its cursor so the watermark advances.
        if config.supports_incremental:
            assert config.sort_field is not None
            assert config.incremental_param is not None
            assert config.incremental_fields
