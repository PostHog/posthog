from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.llamacloud import (
    LlamaCloudSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.llama_cloud.settings import (
    ENDPOINTS,
    LLAMA_CLOUD_ENDPOINTS,
    LlamaCloudEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.llama_cloud.source import LlamaCloudSource


class TestLlamaCloudSource:
    def setup_method(self) -> None:
        self.source = LlamaCloudSource()
        self.team_id = 1
        self.config = LlamaCloudSourceConfig(api_key="llx-test")

    def test_get_schemas_endpoints(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    @parameterized.expand(
        [
            ("parse_jobs", True, "created_at"),
            ("extract_jobs", True, "created_at"),
            ("classify_jobs", True, "created_at"),
            ("batches", True, "created_at"),
            ("split_jobs", True, "created_at"),
            ("sheets_jobs", True, "created_at"),
            ("usage_metrics", True, "day"),
            # No server-side timestamp filter on these listings, so full refresh only.
            ("projects", False, None),
            ("pipelines", False, None),
            ("files", False, None),
        ]
    )
    def test_get_schemas_incremental_semantics(
        self, endpoint: str, supports_incremental: bool, incremental_field: str | None
    ) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        schema = schemas[endpoint]
        assert schema.supports_incremental is supports_incremental
        assert schema.supports_append is supports_incremental
        assert [f["field"] for f in schema.incremental_fields] == ([incremental_field] if incremental_field else [])

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["parse_jobs", "projects"])
        assert {s.name for s in schemas} == {"parse_jobs", "projects"}

    def test_get_schemas_filtered_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    def test_job_schemas_declare_status_lookback(self) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        assert schemas["parse_jobs"].default_incremental_lookback_seconds == 24 * 60 * 60
        assert schemas["projects"].default_incremental_lookback_seconds is None

    def test_http_sample_capture_is_fail_closed(self) -> None:
        # A new endpoint config must default to no HTTP sample capture; only endpoints whose
        # response is limited to safe metadata opt in. Guards against a job/config endpoint
        # (which can carry customer document content or embedded credentials) silently
        # sampling raw responses into object storage.
        assert LlamaCloudEndpointConfig(name="x", path="/y").capture_http_samples is False
        capturing = {name for name, config in LLAMA_CLOUD_ENDPOINTS.items() if config.capture_http_samples}
        assert capturing == {"projects", "usage_metrics"}

    def test_documented_tables_render_without_credentials(self) -> None:
        assert self.source.lists_tables_without_credentials is True
        tables = self.source.get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)
        parse_jobs = next(t for t in tables if t["name"] == "parse_jobs")
        assert parse_jobs["description"]

    @parameterized.expand(
        [
            ("401 Client Error: Unauthorized for url: https://api.cloud.llamaindex.ai/api/v2/parse?page_size=100",),
            ("401 Client Error: Unauthorized for url: https://api.cloud.eu.llamaindex.ai/api/v2/projects",),
            ("403 Client Error: Forbidden for url: https://api.cloud.llamaindex.ai/api/v1/beta/files",),
            # The beta usage-metrics endpoint 400s for organizations it isn't available to; the
            # request is otherwise valid, so retrying can't help. Both regional hosts must match.
            (
                "400 Client Error: Bad Request for url: https://api.cloud.llamaindex.ai/api/v1/beta/usage-metrics?page_size=100&organization_id=00000000-0000-0000-0000-000000000000",
            ),
            (
                "400 Client Error: Bad Request for url: https://api.cloud.eu.llamaindex.ai/api/v1/beta/usage-metrics?page_size=100&organization_id=00000000-0000-0000-0000-000000000000",
            ),
        ]
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            ("500 Server Error: Internal Server Error for url: https://api.cloud.llamaindex.ai/api/v2/parse",),
            ("401 Client Error: Unauthorized for url: https://api.example.com/api/v2/parse",),
            # A 400 on a different endpoint may be a fixable bug in our request, so it must stay
            # retryable and keep surfacing rather than being swallowed by the usage-metrics key.
            ("400 Client Error: Bad Request for url: https://api.cloud.llamaindex.ai/api/v2/parse?page_size=100",),
        ]
    )
    def test_non_retryable_errors_ignore_unrelated(self, unrelated_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in unrelated_error for key in non_retryable)


class TestLlamaCloudSourceVersions:
    def setup_method(self) -> None:
        self.source = LlamaCloudSource()

    def test_new_sources_default_to_v2(self) -> None:
        # New sources (no pin) must be created on LlamaCloud's current API generation.
        assert self.source.default_version == "v2"
        assert self.source.resolve_api_version(None) == "v2"

    @parameterized.expand([("v1",), ("v2",)])
    def test_existing_pin_is_honored(self, version: str) -> None:
        # Pinned rows — including the legacy "v1" default existing sources carry — keep their
        # version after the default bump, so their syncs stay byte-for-byte unaffected.
        assert version in self.source.supported_versions
        assert self.source.resolve_api_version(version) == version

    @parameterized.expand([("v1",), ("v2",)])
    def test_no_version_is_deprecated(self, version: str) -> None:
        # This is a plain update, not a sunset: neither label is deprecated, so the in-product
        # deprecation banner must stay dark for existing v1 pins.
        assert self.source.get_version_deprecation(version) is None
