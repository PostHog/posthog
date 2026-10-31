from products.warehouse_sources.backend.temporal.data_imports.sources.platform_sh.source import PlatformShSource


class TestPlatformShSourceConfig:
    def test_platform_is_a_connection_host_field(self) -> None:
        # `platform` retargets which vendor host the stored token is sent to, so changing it must
        # force the editor to re-enter the secret.
        assert PlatformShSource().connection_host_fields == ["platform"]
