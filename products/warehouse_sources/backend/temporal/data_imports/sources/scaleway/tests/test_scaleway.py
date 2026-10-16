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
    _resolve_path,
    probe_endpoint,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.scaleway.settings import (
    INSTANCE_ZONES,
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
        assert result.saved_states == [ScalewayResumeConfig(scope_index=0, page=2)]

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

    @parameterized.expand([("page_size_endpoint", "users"), ("token_endpoint", "audit_trail_events")])
    def test_requests_a_single_row(self, _name: str, endpoint: str) -> None:
        with scripted_network([_response({}, status=200)]) as network:
            probe_endpoint("scw-secret", "org-123", endpoint)
        size_key = "per_page" if SCALEWAY_ENDPOINTS[endpoint].pagination == "per_page" else "page_size"
        assert network.requests_log[0].param(size_key) == "1"
