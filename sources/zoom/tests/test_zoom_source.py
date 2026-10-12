import pytest

from sources.zoom._config import ZoomSourceConfig
from sources.zoom.source import ZoomSource

MODULE = "sources.zoom.source"


def _config() -> ZoomSourceConfig:
    return ZoomSourceConfig(account_id="acc", client_id="cid", client_secret="secret")


class TestZoomSource:
    @pytest.mark.parametrize("names", [["users"], ["meetings", "webinars"]])
    def test_get_schemas_filters_by_names(self, names: list[str]) -> None:
        schemas = ZoomSource().get_schemas(_config(), team_id=1, names=names)
        assert {s.name for s in schemas} == set(names)
