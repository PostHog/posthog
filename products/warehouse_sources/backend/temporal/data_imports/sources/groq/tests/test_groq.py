import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.groq import GroqSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.groq.groq import groq_source, validate_credentials
from products.warehouse_sources.backend.temporal.data_imports.sources.groq.source import GroqSource


class TestGroq:
    @staticmethod
    def _driver() -> SourceDriver:
        return SourceDriver(GroqSource(), GroqSourceConfig(api_key="gsk_k"))

    @parameterized.expand([("files",), ("models",)])
    def test_non_paginated_reads_single_page(self, endpoint: str) -> None:
        # files and models are flat `data` arrays; the transport must not attempt a second request
        # even if a stray cursor is present in the body.
        result = self._driver().run(
            endpoint,
            [ScriptedResponse(json={"data": [{"id": "a"}, {"id": "b"}], "paging": {"next_cursor": "x"}})],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["a", "b"]
        assert result.paths == [f"/openai/v1/{endpoint}"]

    def test_non_dict_body_is_retried_then_reraises(self) -> None:
        # A non-object body (bare array) is an unexpected shape; the request is reissued and, if it
        # never recovers, surfaces as a retryable error after the attempt cap.
        result = self._driver().run("models", always(ScriptedResponse(json=["unexpected"])))

        assert isinstance(result.raised, RESTClientRetryableError)
        assert result.paths == ["/openai/v1/models"] * 5
        assert result.rows == []

    def test_non_list_data_is_retried_then_reraises(self) -> None:
        # A `data` field that isn't a list (error payload or changed API shape) must not be yielded as
        # rows; it is treated as a transient malformation and reissued.
        result = self._driver().run("models", always(ScriptedResponse(json={"data": {"unexpected": "object"}})))

        assert isinstance(result.raised, RESTClientRetryableError)
        assert result.paths == ["/openai/v1/models"] * 5
        assert result.rows == []

    @parameterized.expand([("rate_limited", 429, "Too Many Requests"), ("server_error", 503, "Service Unavailable")])
    def test_retryable_status_retries_then_raises(self, _name: str, status: int, _reason: str) -> None:
        result = self._driver().run("models", always(ScriptedResponse(status=status, json={})))

        assert isinstance(result.raised, RESTClientRetryableError)
        assert result.paths == ["/openai/v1/models"] * 5
        assert result.rows == []

    @parameterized.expand([("unauthorized", 401, "Unauthorized"), ("forbidden", 403, "Forbidden")])
    def test_client_error_raises_http_error_without_retry(self, _name: str, status: int, reason: str) -> None:
        # 401/403 are credential/permission failures — never retried, surfaced as an HTTPError whose
        # message carries the stable status text that get_non_retryable_errors matches on.
        result = self._driver().run("models", [ScriptedResponse(status=status, json={"error": "denied"})])

        assert isinstance(result.raised, requests.HTTPError)
        assert f"{status} Client Error: {reason}" in str(result.raised)
        assert "https://api.groq.com" in str(result.raised)
        assert result.paths == ["/openai/v1/models"]

    @parameterized.expand(
        [
            ("batches", "created_at"),
            ("files", "created_at"),
            ("models", "created"),
        ]
    )
    def test_groq_source_maps_primary_keys_and_partitioning(self, endpoint: str, partition_key: str) -> None:
        # No network: SourceResponse metadata is built eagerly, rows only on iteration.
        response = groq_source("gsk_k", endpoint, team_id=1, job_id="j")
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        assert response.partition_mode == "datetime"
        assert response.partition_keys == [partition_key]

    @parameterized.expand(
        [
            ("valid", 200, True, True, 200),
        ]
    )
    def test_validate_credentials(
        self,
        _name: str,
        status: int,
        _ok: bool,
        expected_ok: bool,
        expected_status: int | None,
    ) -> None:
        with scripted_network([ScriptedResponse(status=status)]) as network:
            result_ok, result_status = validate_credentials("gsk_ok")

        assert result_ok is expected_ok
        assert result_status == expected_status
        assert len(network.requests_log) == 1
        assert network.requests_log[0].method == "GET"
        assert network.requests_log[0].path == "/openai/v1/models"
        assert network.requests_log[0].headers["authorization"] == "Bearer gsk_ok"

    def test_validate_credentials_empty_key_skips_request(self) -> None:
        with scripted_network([]) as network:
            ok, status = validate_credentials("   ")

        assert ok is False
        assert status is None
        assert network.requests_log == []
        assert network.session_options == []
