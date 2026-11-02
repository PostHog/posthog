import pytest

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.instatus import (
    InstatusSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.instatus.instatus import (
    InstatusResumeConfig,
    _child_path,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.instatus.settings import INSTATUS_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.instatus.source import InstatusSource


def _driver() -> SourceDriver:
    return SourceDriver(InstatusSource(), InstatusSourceConfig(api_key="key"))


class TestPagesEndpoint:
    def test_resumes_from_saved_page(self) -> None:
        result = _driver().run(
            "pages",
            [ScriptedResponse(json=[{"id": "p9"}]), ScriptedResponse(json=[])],
            resume_state=InstatusResumeConfig(page=3, parent_page_id=None),
        )

        assert result.raised is None
        assert result.params("page") == ["3", "4"]

    def test_client_error_raises(self) -> None:
        result = _driver().run(
            "pages", [ScriptedResponse(status=401, json={"error": {"message": "Could not authenticate"}})]
        )

        assert isinstance(result.raised, requests.HTTPError)


class TestFanOut:
    @pytest.mark.parametrize(
        "endpoint, url_suffix",
        [
            ("components", "components"),
            # Schema names use underscores, but the API path is hyphenated.
            ("generic_notices", "generic-notices"),
        ],
    )
    def test_fans_out_over_pages_and_injects_page_id(self, endpoint: str, url_suffix: str) -> None:
        result = _driver().run(
            endpoint,
            [
                ScriptedResponse(json=[{"id": "p1"}, {"id": "p2"}]),  # /v2/pages page 1
                ScriptedResponse(json=[{"id": "c1"}]),  # /v1/p1/<endpoint> page 1
                ScriptedResponse(json=[]),  # /v1/p1/<endpoint> page 2 (stop)
                ScriptedResponse(json=[{"id": "c2"}]),  # /v1/p2/<endpoint> page 1
                ScriptedResponse(json=[]),  # /v1/p2/<endpoint> page 2 (stop)
                ScriptedResponse(json=[]),  # /v2/pages page 2 (stop)
            ],
        )

        # page_id injected so the composite [page_id, id] key stays unique table-wide.
        assert result.raised is None
        assert result.rows == [{"id": "c1", "page_id": "p1"}, {"id": "c2", "page_id": "p2"}]
        assert f"/v1/p1/{url_suffix}" in result.paths
        assert f"/v1/p2/{url_suffix}" in result.paths

    def test_resumes_fan_out_at_saved_parent_and_page(self) -> None:
        # p1 already completed, p2 in progress at its next page (2) — p1 must not be re-requested.
        result = _driver().run(
            "components",
            [
                ScriptedResponse(json=[{"id": "p1"}, {"id": "p2"}]),  # pages relisted on resume
                ScriptedResponse(json=[{"id": "c2b"}]),  # resume p2 at page 2
                ScriptedResponse(json=[]),  # p2 components page 3 (stop)
                ScriptedResponse(json=[]),  # pages page 2 (stop)
            ],
            resume_state=InstatusResumeConfig(
                fanout_state={
                    "completed": [_child_path("components", "p1")],
                    "current": _child_path("components", "p2"),
                    "child_state": {"page": 2},
                }
            ),
        )

        assert result.raised is None
        assert result.rows == [{"id": "c2b", "page_id": "p2"}]
        assert "/v1/p1/components" not in result.paths
        component_requests = [request for request in result.requests if request.path == "/v1/p2/components"]
        assert component_requests[0].param("page") == "2"

    def test_missing_parent_id_raises_loudly(self) -> None:
        # A status page without an id can't drive the child fan-out — surface it loudly.
        result = _driver().run("components", [ScriptedResponse(json=[{"name": "no-id"}]), ScriptedResponse(json=[])])

        assert isinstance(result.raised, ValueError)
        assert "id" in str(result.raised)


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected_ok",
        [
            (200, True),
        ],
    )
    def test_status_mapping(self, status_code: int, expected_ok: bool) -> None:
        script = (
            always(ScriptedResponse(status=status_code))
            if status_code == 500
            else [ScriptedResponse(status=status_code)]
        )
        with scripted_network(script) as network:
            ok, error = validate_credentials("key")

        assert ok is expected_ok
        if not ok:
            assert error
        assert network.requests_log[0].path == "/v2/pages"
        assert network.requests_log[0].param("per_page") == "1"
        assert network.requests_log[0].headers["authorization"] == "Bearer key"

    def test_request_exception_is_failure(self) -> None:
        with scripted_network(always(ConnectionError("boom"))) as network:
            ok, error = validate_credentials("key")

        assert ok is False
        assert error
        assert {request.path for request in network.requests_log} == {"/v2/pages"}


class TestInstatusSourceResponse:
    @pytest.mark.parametrize("endpoint", list(INSTATUS_ENDPOINTS.keys()))
    def test_source_response_shape(self, endpoint: str) -> None:
        config = INSTATUS_ENDPOINTS[endpoint]
        result = _driver().run(endpoint, [ScriptedResponse(json=[])])
        response = result.response

        assert result.raised is None
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == config.primary_key
        assert response.sort_mode == "asc"
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    @pytest.mark.parametrize(
        "endpoint, expected_keys",
        [
            ("pages", ["id"]),
            ("components", ["page_id", "id"]),
            ("subscribers", ["page_id", "id"]),
            ("incidents", ["page_id", "id"]),
        ],
    )
    def test_primary_keys_are_unique_table_wide(self, endpoint: str, expected_keys: list[str]) -> None:
        # Fan-out children carry the parent page id in their key so rows from different pages
        # never collide on a bare resource id.
        assert INSTATUS_ENDPOINTS[endpoint].primary_key == expected_keys

    @pytest.mark.parametrize(
        "endpoint, expected_partition",
        [
            ("pages", "createdAt"),
            ("components", "createdAt"),
            ("templates", "createdAt"),
            ("incidents", "started"),
            ("maintenances", "start"),
            ("outages", "createdAt"),
            ("generic_notices", "createdAt"),
            ("subscribers", None),
            ("metrics", None),
        ],
    )
    def test_partition_keys_are_stable_fields(self, endpoint: str, expected_partition: str | None) -> None:
        # Partition only on immutable creation-time fields, never updatedAt.
        assert INSTATUS_ENDPOINTS[endpoint].partition_key == expected_partition
