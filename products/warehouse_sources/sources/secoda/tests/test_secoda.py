from typing import Any, Optional

from parameterized import parameterized

from products.warehouse_sources.sources.sdk.testing import ScriptedResponse, SourceDriver, always, scripted_network
from products.warehouse_sources.sources.secoda._config import SecodaSourceConfig
from products.warehouse_sources.sources.secoda.secoda import SECODA_BASE_URL, SecodaResumeConfig, validate_credentials
from products.warehouse_sources.sources.secoda.settings import ENDPOINTS, SECODA_ENDPOINTS
from products.warehouse_sources.sources.secoda.source import SecodaSource

TABLES_URL = f"{SECODA_BASE_URL}/api/v1/table/tables"
MONITORS_URL = f"{SECODA_BASE_URL}/api/v1/monitor/monitors"
MEASUREMENTS_URL = f"{SECODA_BASE_URL}/api/v1/monitor/measurements"


def _driver() -> SourceDriver:
    return SourceDriver(SecodaSource(), SecodaSourceConfig(api_key="sk-key"))


def _page(
    results: list[dict], *, links_next: Optional[str] = None, top_level_next: Optional[str] = None
) -> ScriptedResponse:
    # DRF cursor endpoints nest the follow link under links.next; a few endpoints instead expose it
    # top-level under next (with no links envelope). Build one shape or the other, never both.
    if top_level_next is not None:
        return ScriptedResponse(json={"results": results, "next": top_level_next})
    return ScriptedResponse(json={"results": results, "links": {"next": links_next, "previous": None}})


class TestPagination:
    def test_follows_links_next_cursor_until_null(self) -> None:
        second = f"{TABLES_URL}?page=2"

        result = _driver().run(
            "tables",
            [_page([{"id": "a"}], links_next=second), _page([{"id": "b"}], links_next=None)],
        )

        assert result.rows == [{"id": "a"}, {"id": "b"}]
        # First request hits the base path; the second follows the self-contained cursor URL verbatim.
        assert result.urls[0] == TABLES_URL
        assert result.urls[1] == second
        # State is saved once — after the first page, pointing at the next cursor — then we stop.
        assert result.saved_states == [SecodaResumeConfig(next_url=second)]

    def test_resumes_from_the_saved_cursor(self) -> None:
        saved = f"{TABLES_URL}?page=7"

        result = _driver().run("tables", [_page([{"id": "z"}])], resume_state=SecodaResumeConfig(next_url=saved))

        assert result.rows == [{"id": "z"}]
        assert result.urls == [saved]


class TestMonitorMeasurementsFanout:
    def test_fetches_measurements_per_monitor_across_pages(self) -> None:
        monitors_page_2 = f"{MONITORS_URL}?page=2"
        measurements_page_2 = f"{MEASUREMENTS_URL}?monitor=mon-a&page=2"

        result = _driver().run(
            "monitor_measurements",
            [
                _page([{"id": "mon-a"}], links_next=monitors_page_2),
                _page([{"id": "m1", "monitor": "mon-a", "value": 1.0}], links_next=measurements_page_2),
                _page([{"id": "m2", "monitor": "mon-a", "value": 2.0}]),
                _page([{"id": "mon-b"}, {"id": "mon-deleted"}]),
                _page([{"id": "m3", "monitor": "mon-b", "value": 3.0}]),
                # A monitor deleted after the monitors listing must not fail the sync.
                ScriptedResponse(status=404, json={"detail": "Not found."}),
            ],
        )

        assert result.rows == [
            {"id": "m1", "monitor": "mon-a", "value": 1.0, "monitor_id": "mon-a"},
            {"id": "m2", "monitor": "mon-a", "value": 2.0, "monitor_id": "mon-a"},
            {"id": "m3", "monitor": "mon-b", "value": 3.0, "monitor_id": "mon-b"},
        ]
        assert result.urls == [
            MONITORS_URL,
            f"{MEASUREMENTS_URL}?monitor=mon-a",
            measurements_page_2,
            monitors_page_2,
            f"{MEASUREMENTS_URL}?monitor=mon-b",
            f"{MEASUREMENTS_URL}?monitor=mon-deleted",
        ]
        assert result.saved_states == []


class TestTransientResponsesRetried:
    @parameterized.expand(
        [
            ("bare_list_body", [{"id": "x"}]),
            ("missing_results_key", {"count": 1}),
            ("results_not_a_list", {"results": {"nope": 1}}),
        ]
    )
    def test_unexpected_200_body_is_reissued(self, _name: str, bad_body: Any) -> None:
        # A 200 whose body isn't the expected {"results": [...]} shape is transient — the framework
        # reissues it; a well-formed follow-up succeeds.
        result = _driver().run("tables", [ScriptedResponse(json=bad_body), _page([{"id": "a"}], links_next=None)])

        assert result.rows == [{"id": "a"}]
        assert len(result.requests) == 2

    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    def test_retryable_status_is_reissued(self, _name: str, status: int) -> None:
        # 429/5xx are retried by the client itself; the retried request then succeeds.
        result = _driver().run("tables", [ScriptedResponse(status=status, json={}), _page([{"id": "a"}])])

        assert result.rows == [{"id": "a"}]
        assert len(result.requests) == 2


class TestRowShaping:
    def test_integration_credentials_never_reach_the_warehouse(self) -> None:
        row = {"id": "int-1", "name": "Warehouse", "type": "postgres", "credentials": {"password": "fake-pw"}}

        result = _driver().run("integrations", [_page([row])])

        assert result.rows == [{"id": "int-1", "name": "Warehouse", "type": "postgres"}]


class TestValidateCredentials:
    def test_ok(self) -> None:
        with scripted_network([ScriptedResponse(status=200, json={})]) as network:
            assert validate_credentials("sk-key") == (True, None)

        assert network.requests_log[0].headers["authorization"] == "Bearer sk-key"

    def test_connection_error_maps_to_generic_message(self) -> None:
        # validate_via_probe swallows transport errors and reports status None.
        with scripted_network(always(ConnectionError("boom"))):
            assert validate_credentials("sk-key") == (False, "Could not validate Secoda API key")


class TestSecodaSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        result = _driver().run(endpoint, [_page([])])

        response = result.response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == SECODA_ENDPOINTS[endpoint].primary_keys
        # No stable creation timestamp is guaranteed across every object, so we don't partition.
        assert response.partition_mode is None
