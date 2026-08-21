from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.llamacloud import (
    LlamaCloudSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.llama_cloud.settings import (
    LLAMA_CLOUD_ENDPOINTS,
    LlamaCloudEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.llama_cloud.source import LlamaCloudSource


class TestLlamaCloudSource:
    def setup_method(self) -> None:
        self.source = LlamaCloudSource()
        self.team_id = 1
        self.config = LlamaCloudSourceConfig(api_key="llx-test")

    def test_http_sample_capture_is_fail_closed(self) -> None:
        # A new endpoint config must default to no HTTP sample capture; only endpoints whose
        # response is limited to safe metadata opt in. Guards against a job/config endpoint
        # (which can carry customer document content or embedded credentials) silently
        # sampling raw responses into object storage.
        assert LlamaCloudEndpointConfig(name="x", path="/y").capture_http_samples is False
        capturing = {name for name, config in LLAMA_CLOUD_ENDPOINTS.items() if config.capture_http_samples}
        assert capturing == {"projects", "usage_metrics"}


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
