import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.linearb import (
    LinearbSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.linearb.linearb import (
    _sanitize_metric_key,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.linearb.settings import (
    ENDPOINTS,
    LINEARB_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.linearb.source import LinearbSource


def _driver() -> SourceDriver:
    return SourceDriver(LinearbSource(), LinearbSourceConfig(api_key="key"))


class TestSanitizeMetricKey:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("branch.computed.cycle_time:p75", "branch_computed_cycle_time_p75"),
            ("releases.count", "releases_count"),
            ("organization_id", "organization_id"),
            ("pr.merged.without.review.count", "pr_merged_without_review_count"),
        ],
    )
    def test_sanitize(self, raw: str, expected: str) -> None:
        assert _sanitize_metric_key(raw) == expected


class TestValidateCredentials:
    @pytest.mark.parametrize(
        ("status_code", "expected"),
        [(200, True), (403, False), (401, False), (500, False)],
    )
    def test_status_mapping(self, status_code: int, expected: bool) -> None:
        with scripted_network([ScriptedResponse(status=status_code)]) as network:
            assert validate_credentials("key") is expected

        assert network.requests_log[0].path == "/api/v2/teams"
        assert network.requests_log[0].param("page_size") == "1"
        assert network.requests_log[0].headers["x-api-key"] == "key"
        assert network.session_options == [{"allow_redirects": False}]

    def test_network_error_is_invalid(self) -> None:
        with scripted_network(always(ConnectionError("boom"))) as network:
            assert validate_credentials("key") is False

        assert {request.path for request in network.requests_log} == {"/api/v2/teams"}


class TestListPagination:
    @pytest.mark.parametrize(
        ("endpoint", "method", "page_size_param", "page_size"),
        [
            ("teams", "GET", "page_size", 50),
            ("incidents", "POST", "limit", 100),
        ],
    )
    def test_paginates_until_total_reached(
        self, endpoint: str, method: str, page_size_param: str, page_size: int
    ) -> None:
        # A full page followed by a short page must stop at the reported total.
        result = _driver().run(
            endpoint,
            [
                ScriptedResponse(json={"total": page_size + 1, "items": [{"id": i} for i in range(page_size)]}),
                ScriptedResponse(json={"total": page_size + 1, "items": [{"id": page_size}]}),
            ],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == list(range(page_size + 1))
        assert [request.method for request in result.requests] == [method, method]
        assert result.paths == [LINEARB_ENDPOINTS[endpoint].path] * 2
        if method == "GET":
            assert result.queries == [
                {page_size_param: (str(page_size),), "offset": (str(offset),)} for offset in (0, page_size)
            ]
            assert [request.body for request in result.requests] == [None, None]
        else:
            assert result.queries == [{}, {}]
            assert [request.json() for request in result.requests] == [
                {
                    "issued_at": {"after": "2000-01-01"},
                    "sort_by": "issued_at",
                    "sort_dir": "asc",
                    page_size_param: page_size,
                    "offset": offset,
                }
                for offset in (0, page_size)
            ]

    def test_stops_on_empty_page(self) -> None:
        result = _driver().run("teams", [ScriptedResponse(json={"total": 0, "items": []})])

        assert result.raised is None
        assert result.items == []
        assert result.paths == ["/api/v2/teams"]
        assert result.params("offset") == ["0"]

    def test_single_page_endpoint_without_paging_params_fetches_once(self) -> None:
        # services documents no paging params; even a large page must not loop forever.
        result = _driver().run(
            "services", [ScriptedResponse(json={"total": 5, "items": [{"id": i} for i in range(5)]})]
        )

        assert result.raised is None
        assert len(result.items) == 1
        assert result.rows == [{"id": i} for i in range(5)]
        assert result.paths == ["/api/v1/services"]
        assert result.queries == [{}]


class TestMeasurements:
    def test_flattens_windows_into_rows(self) -> None:
        windows = [
            {
                "after": "2024-01-01",
                "before": "2024-01-02",
                "metrics": [{"organization_id": 7, "releases.count": 3, "branch.computed.cycle_time:p75": 100}],
            }
        ]
        result = _driver().run("measurements", [ScriptedResponse(json=windows)])

        assert result.raised is None
        assert len(result.items) == 1
        row = result.rows[0]
        assert row["after"] == "2024-01-01"
        assert row["before"] == "2024-01-02"
        assert row["organization_id"] == 7
        assert row["releases_count"] == 3
        assert row["branch_computed_cycle_time_p75"] == 100
        assert result.paths == ["/api/v2/measurements"]
        assert result.requests[0].method == "POST"
        assert result.requests[0].json()["group_by"] == "organization"

    def test_no_content_yields_nothing(self) -> None:
        result = _driver().run("measurements", [ScriptedResponse(status=204)])

        assert result.raised is None
        assert result.items == []
        assert result.paths == ["/api/v2/measurements"]


class TestLinearbSource:
    @pytest.mark.parametrize("endpoint", ENDPOINTS)
    def test_source_response_matches_endpoint_config(self, endpoint: str) -> None:
        answer = ScriptedResponse(status=204) if endpoint == "measurements" else ScriptedResponse(json={"items": []})
        result = _driver().run(endpoint, [answer])
        config = LINEARB_ENDPOINTS[endpoint]

        assert result.raised is None
        assert result.response is not None
        assert result.response.name == endpoint
        assert result.response.primary_keys == config.primary_keys
        assert result.response.sort_mode == "asc"
        if config.partition_key:
            assert result.response.partition_mode == "datetime"
            assert result.response.partition_keys == [config.partition_key]
        else:
            assert result.response.partition_mode is None
