import structlog

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.mixpanel import (
    MixpanelSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mixpanel.source import MixpanelSource

LOGGER = structlog.get_logger()


def _config() -> MixpanelSourceConfig:
    return MixpanelSource().parse_config(
        {
            "project_id": "123456",
            "service_account_username": "svc",
            "service_account_secret": "shh",
            "region": "eu",
        }
    )


class TestGetSchemas:
    def test_export_has_time_incremental_field(self) -> None:
        schemas = {s.name: s for s in MixpanelSource().get_schemas(_config(), team_id=1)}
        fields = schemas["export"].incremental_fields
        assert [f["field"] for f in fields] == ["time"]


class TestApiVersions:
    def test_new_sources_default_to_2_0(self) -> None:
        # New sources are stamped with `default_version`; existing pins are unaffected.
        assert MixpanelSource().default_version == "2.0"
        assert set(MixpanelSource().supported_versions) == {"v1", "2.0"}
