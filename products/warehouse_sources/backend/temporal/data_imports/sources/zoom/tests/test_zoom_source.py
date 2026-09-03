import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.zoom import ZoomSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.zoom.source import ZoomSource

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.zoom.source"


def _config() -> ZoomSourceConfig:
    return ZoomSourceConfig(account_id="acc", client_id="cid", client_secret="secret")


class TestZoomSource:
    def test_get_schemas_lists_all_endpoints_as_full_refresh(self) -> None:
        schemas = ZoomSource().get_schemas(_config(), team_id=1)
        names = {s.name for s in schemas}
        assert names == {"users", "meetings", "webinars"}
        assert all(s.supports_incremental is False for s in schemas)
        assert all(s.supports_append is False for s in schemas)

    @pytest.mark.parametrize("names", [["users"], ["meetings", "webinars"]])
    def test_get_schemas_filters_by_names(self, names: list[str]) -> None:
        schemas = ZoomSource().get_schemas(_config(), team_id=1, names=names)
        assert {s.name for s in schemas} == set(names)
