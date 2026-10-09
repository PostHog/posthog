from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.platform_sh.source import PlatformShSource


class TestPlatformShSourceConfig:
    def test_platform_is_a_connection_host_field(self) -> None:
        # `platform` retargets which vendor host the stored token is sent to, so changing it must
        # force the editor to re-enter the secret.
        assert PlatformShSource().connection_host_fields == ["platform"]


class TestPlatformShGetSchemas:
    def test_names_filter(self) -> None:
        schemas = PlatformShSource().get_schemas(mock.Mock(), team_id=1, names=["projects", "activities"])
        assert {s.name for s in schemas} == {"projects", "activities"}
