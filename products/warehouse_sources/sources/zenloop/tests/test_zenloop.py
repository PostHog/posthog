from typing import Any

from parameterized import parameterized
from requests import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    ScriptedResponse,
    SourceDriver,
    always,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.zenloop import (
    ZenloopSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.zenloop import zenloop
from products.warehouse_sources.backend.temporal.data_imports.sources.zenloop.settings import (
    ENDPOINTS,
    ZENLOOP_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.zenloop.source import ZenloopSource
from products.warehouse_sources.backend.temporal.data_imports.sources.zenloop.zenloop import ZenloopResumeConfig


def _response(
    items: list[dict[str, Any]] | None,
    *,
    response_key: str = "surveys",
    status: int = 200,
    drop_key: bool = False,
) -> ScriptedResponse:
    body: dict[str, Any] = {"meta": {"per_page": zenloop.PER_PAGE}}
    if not drop_key:
        body[response_key] = items or []
    return ScriptedResponse(status=status, json=body)


def _run(script: Any, endpoint: str = "surveys", resume_state: ZenloopResumeConfig | None = None) -> DriveResult:
    driver = SourceDriver(ZenloopSource(), ZenloopSourceConfig(api_token="token"))
    return driver.run(endpoint, script, resume_state=resume_state)


class TestPagination:
    def test_resumes_from_saved_page(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(zenloop, "PER_PAGE", 2)
        # Page 1 must never be fetched on resume.
        result = _run(
            [_response([{"id": 3}, {"id": 4}]), _response([{"id": 5}])],
            resume_state=ZenloopResumeConfig(next_page=2),
        )

        assert [r["id"] for r in result.rows] == [3, 4, 5]
        assert result.params("page")[0] == "2"

    def test_missing_data_key_raises_loudly(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(zenloop, "PER_PAGE", 2)
        result = _run([_response(None, drop_key=True)])

        # A 200 body without the endpoint's named key means the response shape changed — fail loud
        # rather than silently syncing 0 rows.
        assert isinstance(result.raised, ValueError)
        assert "matched nothing" in str(result.raised)


class TestRetryAndErrors:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    def test_retryable_status_is_retried_then_succeeds(self, _name: str, status: int) -> None:
        result = _run([_response([{"id": 1}], status=status), _response([{"id": 1}])])

        # The transient error is retried and the reissued request succeeds.
        assert result.rows == [{"id": 1}]
        assert len(result.requests) == 2

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise_http_error(self, _name: str, status: int) -> None:
        result = _run(always(_response([{"id": 1}], status=status)))

        assert isinstance(result.raised, HTTPError)


class TestZenloopSourceResponse:
    @parameterized.expand([("surveys",), ("survey_groups",), ("properties",)])
    def test_response_shape_matches_endpoint_config(self, endpoint: str) -> None:
        result = _run(
            always(_response([], response_key=ZENLOOP_ENDPOINTS[endpoint].response_key)),
            endpoint=endpoint,
        )

        response = result.response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        # No endpoint exposes a creation-timestamp partition key, so partitioning stays off.
        assert response.partition_mode is None
        assert response.partition_keys is None

    def test_every_endpoint_uses_id_primary_key(self) -> None:
        assert all(config.primary_keys == ["id"] for config in ZENLOOP_ENDPOINTS.values())
        assert set(ZENLOOP_ENDPOINTS) == set(ENDPOINTS)
