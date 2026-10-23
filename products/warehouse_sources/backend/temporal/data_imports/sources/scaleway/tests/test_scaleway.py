from datetime import UTC, datetime

import time_machine

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.scaleway import (
    ScalewaySourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.scaleway.scaleway import (
    ScalewayResumeConfig,
    _base_params,
    _billing_periods,
    _resolve_path,
    probe_endpoint,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.scaleway.settings import (
    BILLING_CONSUMPTION_LOOKBACK_MONTHS,
    INSTANCE_ZONES,
    K8S_REGIONS,
    PAGE_SIZE,
    SCALEWAY_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.scaleway.source import ScalewaySource


def _response(body: dict, status: int = 200) -> ScriptedResponse:
    return ScriptedResponse(status=status, json=body)


def _drive(endpoint: str, responses: list[ScriptedResponse], resume: ScalewayResumeConfig | None = None) -> DriveResult:
    """Run an extraction for `endpoint` against scripted answers returned in order."""
    driver = SourceDriver(ScalewaySource(), ScalewaySourceConfig(secret_key="scw-secret", organization_id="org-123"))
    return driver.run(endpoint, responses, resume_state=resume)


class TestBaseParams:
    @parameterized.expand(
        [
            # (endpoint, expected page-size param, expected org param name)
            ("users", "page_size", "organization_id"),
            ("projects", "page_size", "organization_id"),
            ("invoices", "page_size", "organization_id"),
            ("instance_servers", "per_page", "organization"),
            ("audit_trail_events", "page_size", "organization_id"),
            ("billing_consumptions", "page_size", "organization_id"),
            ("kubernetes_clusters", "page_size", "organization_id"),
            ("database_instances", "page_size", "organization_id"),
        ]
    )
    def test_pagination_and_org_param_wiring(self, endpoint: str, page_param: str, org_param: str) -> None:
        # Guards the three-dialect wiring: Instance must use per_page + `organization`, everything else
        # page_size + `organization_id`. A swap here silently breaks pagination or org scoping.
        params = _base_params(SCALEWAY_ENDPOINTS[endpoint], "org-123")
        assert params[page_param] == PAGE_SIZE
        assert params[org_param] == "org-123"

    @parameterized.expand(
        [
            ("users", "order_by", "created_at_asc"),
            ("invoices", "order_by", "start_date_asc"),
            ("instance_servers", "order", "creation_date_asc"),
            ("audit_trail_events", "order_by", "recorded_at_asc"),
            ("billing_consumptions", "order_by", "updated_at_asc"),
            ("kubernetes_clusters", "order_by", "created_at_asc"),
            ("kubernetes_pools", "order_by", "created_at_asc"),
            ("kubernetes_nodes", "order_by", "created_at_asc"),
            ("database_instances", "order_by", "created_at_asc"),
        ]
    )
    def test_sort_param_wiring(self, endpoint: str, order_param: str, order_value: str) -> None:
        params = _base_params(SCALEWAY_ENDPOINTS[endpoint], "org-123")
        assert params[order_param] == order_value


class TestResolvePath:
    @parameterized.expand(
        [
            ("users", "fr-par", "/iam/v1alpha1/users"),
            ("instance_servers", "nl-ams-1", "/instance/v1/zones/nl-ams-1/servers"),
            ("audit_trail_events", "fr-par", "/audit-trail/v1alpha1/regions/fr-par/events"),
            ("kubernetes_clusters", "it-mil", "/k8s/v1/regions/it-mil/clusters"),
            ("database_instances", "pl-waw", "/rdb/v1/regions/pl-waw/instances"),
            ("kubernetes_pools", "nl-ams/c-1", "/k8s/v1/regions/nl-ams/clusters/c-1/pools"),
            ("kubernetes_nodes", "fr-par/c-2", "/k8s/v1/regions/fr-par/clusters/c-2/nodes"),
            ("billing_consumptions", "2026-10", "/billing/v2beta1/consumptions"),
        ]
    )
    def test_scope_substitution(self, endpoint: str, scope: str, expected: str) -> None:
        assert _resolve_path(SCALEWAY_ENDPOINTS[endpoint], scope) == expected


class TestPageNumberPagination:
    def test_terminates_on_short_page_and_saves_resume_after_full_page(self) -> None:
        full = _response({"users": [{"id": str(i)} for i in range(PAGE_SIZE)]})
        short = _response({"users": [{"id": "x"}]})

        result = _drive("users", [full, short])

        assert [len(p) for p in result.items] == [PAGE_SIZE, 1]
        # Two page requests, second asks for page 2.
        assert len(result.requests) == 2
        assert result.requests[1].param("page") == "2"
        # Resume state persisted only while more pages remained — pointing at the next page.
        assert result.saved_states == [ScalewayResumeConfig(scope_index=0, page=2, scope_key="_")]

    def test_resumes_from_saved_page(self) -> None:
        short = _response({"users": [{"id": "x"}]})

        result = _drive("users", [short], ScalewayResumeConfig(scope_index=0, page=7))

        assert result.requests[0].param("page") == "7"

    def test_a_run_with_no_saved_state_starts_from_the_first_page(self) -> None:
        result = _drive("users", [_response({"users": [{"id": "x"}]})])

        assert result.requests[0].param("page") == "1"


class TestTokenPagination:
    def test_chains_tokens_and_drops_window_filter_on_subsequent_requests(self) -> None:
        page1 = _response({"events": [{"id": "a"}], "next_page_token": "tok2"})
        page2 = _response({"events": [{"id": "b"}], "next_page_token": None})
        # audit_trail_events fans out over two regions; give each region a single terminal page after
        # the first region's two-page chain.
        region2 = _response({"events": [], "next_page_token": None})

        result = _drive("audit_trail_events", [page1, page2, region2])

        assert [row["id"] for row in result.rows] == ["a", "b"]
        # First request carries the recorded_after window; the token follow-up must not (the token
        # already encodes it server-side).
        assert "recorded_after" in result.queries[0]
        assert result.queries[1] == {"page_size": (str(PAGE_SIZE),), "page_token": ("tok2",)}


class TestFanOut:
    def test_iterates_every_zone_and_advances_scope_between_them(self) -> None:
        # Each zone returns one short page, so the connector visits every zone once.
        responses = [_response({"servers": [{"id": f"srv-{z}"}]}) for z in INSTANCE_ZONES]

        result = _drive("instance_servers", responses)

        assert len(result.requests) == len(INSTANCE_ZONES)
        for zone in INSTANCE_ZONES:
            assert any(f"/zones/{zone}/servers" in path for path in result.paths)
        # Between scopes the bookmark advances so a crash resumes at the next zone, not the first.
        assert [state.scope_index for state in result.saved_states] == list(range(1, len(INSTANCE_ZONES)))
        assert len(result.rows) == len(INSTANCE_ZONES)


class TestBillingPeriods:
    @parameterized.expand(
        [
            ("mid_year", datetime(2026, 10, 16, tzinfo=UTC), "2025-11", "2026-10"),
            ("january_crosses_year", datetime(2026, 1, 1, tzinfo=UTC), "2025-02", "2026-01"),
            ("december", datetime(2026, 12, 31, 23, 59, tzinfo=UTC), "2026-01", "2026-12"),
        ]
    )
    def test_window_ends_at_current_month(self, _name: str, now: datetime, first: str, last: str) -> None:
        periods = _billing_periods(now)

        assert len(periods) == BILLING_CONSUMPTION_LOOKBACK_MONTHS
        assert len(set(periods)) == BILLING_CONSUMPTION_LOOKBACK_MONTHS
        assert periods == sorted(periods)
        assert (periods[0], periods[-1]) == (first, last)

    @time_machine.travel(datetime(2026, 3, 10, tzinfo=UTC), tick=False)
    def test_requests_each_period_and_stamps_it_on_rows(self) -> None:
        responses = [
            _response({"consumptions": [{"sku": f"sku-{i}", "project_id": "p-1"}], "total_count": 1})
            for i in range(BILLING_CONSUMPTION_LOOKBACK_MONTHS)
        ]

        result = _drive("billing_consumptions", responses)

        expected_periods = _billing_periods(datetime(2026, 3, 10, tzinfo=UTC))
        assert result.params("billing_period") == expected_periods
        assert [row["billing_period"] for row in result.rows] == expected_periods
        assert all(query["organization_id"] == ("org-123",) for query in result.queries)

    @parameterized.expand(
        [
            # (name, saved state, first period requested)
            (
                "saved_period_in_window",
                ScalewayResumeConfig(scope_index=0, page=2, scope_key="2025-12"),
                "2025-12",
                "2",
            ),
            # The month rolled over since the save, so the oldest period left the window: start over.
            (
                "saved_period_left_window",
                ScalewayResumeConfig(scope_index=0, page=2, scope_key="2025-03"),
                "2025-04",
                "1",
            ),
        ]
    )
    def test_resume_finds_period_by_key(
        self, _name: str, resume: ScalewayResumeConfig, first_period: str, first_page: str
    ) -> None:
        responses = [_response({"consumptions": []}) for _ in range(BILLING_CONSUMPTION_LOOKBACK_MONTHS)]

        with time_machine.travel(datetime(2026, 3, 10, tzinfo=UTC), tick=False):
            result = _drive("billing_consumptions", responses, resume)

        assert result.requests[0].param("billing_period") == first_period
        assert result.requests[0].param("page") == first_page


class TestKubernetesClusterFanOut:
    def _cluster_listing(self, clusters_by_region: dict[str, list[str]]) -> list[ScriptedResponse]:
        return [
            _response({"clusters": [{"id": cid} for cid in clusters_by_region.get(region, [])]})
            for region in K8S_REGIONS
        ]

    @parameterized.expand([("pools", "kubernetes_pools", "pools"), ("nodes", "kubernetes_nodes", "nodes")])
    def test_lists_clusters_in_every_region_then_pages_each_cluster(
        self, _name: str, endpoint: str, data_key: str
    ) -> None:
        listing = self._cluster_listing({"fr-par": ["c-1"], "pl-waw": ["c-2"]})
        children = [
            _response({data_key: [{"id": f"{data_key}-{i}", "cluster_id": "c-1"} for i in range(PAGE_SIZE)]}),
            _response({data_key: [{"id": "last", "cluster_id": "c-1"}]}),
            _response({data_key: [{"id": "other", "cluster_id": "c-2"}]}),
        ]

        result = _drive(endpoint, listing + children)

        assert result.paths == [
            *[f"/k8s/v1/regions/{region}/clusters" for region in K8S_REGIONS],
            f"/k8s/v1/regions/fr-par/clusters/c-1/{data_key}",
            f"/k8s/v1/regions/fr-par/clusters/c-1/{data_key}",
            f"/k8s/v1/regions/pl-waw/clusters/c-2/{data_key}",
        ]
        assert len(result.rows) == PAGE_SIZE + 2
        # The cluster listing is organization-scoped; the per-cluster requests take no organization filter.
        assert all(query["organization_id"] == ("org-123",) for query in result.queries[: len(K8S_REGIONS)])
        assert all("organization_id" not in query for query in result.queries[len(K8S_REGIONS) :])
        assert result.saved_states == [
            ScalewayResumeConfig(scope_index=0, page=2, scope_key="fr-par/c-1"),
            ScalewayResumeConfig(scope_index=1, scope_key="pl-waw/c-2"),
        ]

    def test_no_clusters_makes_no_child_requests(self) -> None:
        result = _drive("kubernetes_pools", self._cluster_listing({}))

        assert len(result.requests) == len(K8S_REGIONS)
        assert result.rows == []
        assert result.raised is None

    @parameterized.expand(
        [
            # (name, saved state, expected child paths)
            (
                "saved_cluster_still_exists",
                ScalewayResumeConfig(scope_index=0, page=3, scope_key="pl-waw/c-2"),
                ["/k8s/v1/regions/pl-waw/clusters/c-2/pools"],
                "3",
            ),
            (
                # A new cluster in an earlier region shifted the index; the key still finds the right cluster.
                "index_shifted_by_new_cluster",
                ScalewayResumeConfig(scope_index=1, scope_key="pl-waw/c-2"),
                ["/k8s/v1/regions/pl-waw/clusters/c-2/pools"],
                "1",
            ),
            (
                "saved_cluster_deleted",
                ScalewayResumeConfig(scope_index=1, page=3, scope_key="pl-waw/c-gone"),
                [
                    "/k8s/v1/regions/fr-par/clusters/c-0/pools",
                    "/k8s/v1/regions/fr-par/clusters/c-1/pools",
                    "/k8s/v1/regions/pl-waw/clusters/c-2/pools",
                ],
                "1",
            ),
        ]
    )
    def test_resume_finds_cluster_by_key(
        self, _name: str, resume: ScalewayResumeConfig, expected_child_paths: list[str], first_page: str
    ) -> None:
        listing = self._cluster_listing({"fr-par": ["c-0", "c-1"], "pl-waw": ["c-2"]})
        children = [_response({"pools": []}) for _ in expected_child_paths]

        result = _drive("kubernetes_pools", listing + children, resume)

        assert result.paths[len(K8S_REGIONS) :] == expected_child_paths
        assert result.requests[len(K8S_REGIONS)].param("page") == first_page

    def test_a_cluster_deleted_after_listing_is_skipped(self) -> None:
        listing = self._cluster_listing({"fr-par": ["c-gone", "c-1"]})
        children = [_response({}, status=404), _response({"pools": [{"id": "p-1"}]})]

        result = _drive("kubernetes_pools", listing + children)

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["p-1"]
        assert result.paths[len(K8S_REGIONS) :] == [
            "/k8s/v1/regions/fr-par/clusters/c-gone/pools",
            "/k8s/v1/regions/fr-par/clusters/c-1/pools",
        ]


class TestFetchErrors:
    def test_non_ok_response_raises(self) -> None:
        result = _drive("users", [_response({}, status=403)])

        assert isinstance(result.raised, requests.HTTPError)


class TestProbeEndpoint:
    @parameterized.expand([("ok", 200, 200), ("unauthorized", 401, 401), ("forbidden", 403, 403)])
    def test_returns_status_code(self, _name: str, status: int, expected: int) -> None:
        with scripted_network(always(_response({}, status=status))):
            assert probe_endpoint("scw-secret", "org-123", "users") == expected

    def test_network_error_returns_zero(self) -> None:
        with scripted_network(always(requests.ConnectionError("boom"))):
            assert probe_endpoint("scw-secret", "org-123", "users") == 0

    @parameterized.expand(
        [
            ("kubernetes_pools", "/k8s/v1/regions/fr-par/clusters"),
            ("kubernetes_nodes", "/k8s/v1/regions/fr-par/clusters"),
            ("database_instances", "/rdb/v1/regions/fr-par/instances"),
            ("billing_consumptions", "/billing/v2beta1/consumptions"),
        ]
    )
    def test_probes_a_path_that_needs_no_parent_id(self, endpoint: str, expected_path: str) -> None:
        with scripted_network([_response({}, status=200)]) as network:
            assert probe_endpoint("scw-secret", "org-123", endpoint) == 200
        assert network.requests_log[0].path == expected_path

    @parameterized.expand([("page_size_endpoint", "users"), ("token_endpoint", "audit_trail_events")])
    def test_requests_a_single_row(self, _name: str, endpoint: str) -> None:
        with scripted_network([_response({}, status=200)]) as network:
            probe_endpoint("scw-secret", "org-123", endpoint)
        size_key = "per_page" if SCALEWAY_ENDPOINTS[endpoint].pagination == "per_page" else "page_size"
        assert network.requests_log[0].param(size_key) == "1"
