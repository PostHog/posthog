from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.llamacloud import (
    LlamaCloudSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.llama_cloud.source import LlamaCloudSource


class TestLlamaCloudSource:
    def setup_method(self) -> None:
        self.source = LlamaCloudSource()
        self.team_id = 1
        self.config = LlamaCloudSourceConfig(api_key="llx-test")

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

    @parameterized.expand([("v1",), ("v2",)])
    def test_existing_pin_is_honored(self, version: str) -> None:
        # Pinned rows — including the legacy "v1" default existing sources carry — keep their
        # version after the default bump, so their syncs stay byte-for-byte unaffected.
        assert version in self.source.supported_versions
        assert self.source.resolve_api_version(version) == version

    def test_only_legacy_v1_is_deprecated_without_sunset(self) -> None:
        # The vendor published no sunset date, so v1 pins get the advisory banner but keep syncing.
        deprecation = self.source.get_version_deprecation("v1")
        assert deprecation is not None
        assert deprecation.sunset_at is None
        assert self.source.get_version_deprecation("v2") is None
