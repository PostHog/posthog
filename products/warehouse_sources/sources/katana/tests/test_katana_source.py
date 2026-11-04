from products.warehouse_sources.sources.katana._config import KatanaSourceConfig
from products.warehouse_sources.sources.katana.source import KatanaSource
from products.warehouse_sources.sources.sdk.testing import ScriptedResponse, scripted_network


class TestKatanaSourceClass:
    def test_lists_tables_without_credentials(self) -> None:
        # get_schemas is a static catalog with no I/O, so the public docs table list must render.
        assert KatanaSource.lists_tables_without_credentials is True

    def test_validate_credentials_success(self) -> None:
        with scripted_network([ScriptedResponse(json={"id": 1})]) as network:
            ok, error = KatanaSource().validate_credentials(KatanaSourceConfig(api_key="k"), team_id=1)

        assert ok is True
        assert error is None
        assert [request.path for request in network.requests_log] == ["/v1/user_info"]
