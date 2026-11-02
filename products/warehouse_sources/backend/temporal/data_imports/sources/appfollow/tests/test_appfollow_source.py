import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.appfollow.settings import (
    APPFOLLOW_V2,
    APPFOLLOW_V3,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.appfollow.source import AppfollowSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.appfollow import (
    AppfollowSourceConfig,
)


class TestAppfollowSource:
    def setup_method(self):
        self.source = AppfollowSource()
        self.team_id = 123
        self.config = AppfollowSourceConfig(api_key="tok_test")

    def test_lists_tables_without_credentials(self):
        # get_schemas is a static catalog with no I/O, so the public docs can render the table list.
        assert self.source.lists_tables_without_credentials is True

    def test_new_sources_start_on_v3(self):
        assert self.source.default_version == APPFOLLOW_V3
        assert self.source.supported_versions == (APPFOLLOW_V2, APPFOLLOW_V3)

    @pytest.mark.parametrize(
        "status,expected_ok",
        [
            # A single account-wide token: a 403 still proves the token is genuine.
            (403, True),
            (402, False),
            (None, False),
        ],
    )
    def test_validate_credentials(self, status, expected_ok):
        script = [ConnectionError("connection reset")] if status is None else always(ScriptedResponse(status=status))
        with scripted_network(script):
            ok, _ = self.source.validate_credentials(self.config, self.team_id)
        assert ok is expected_ok

    @pytest.mark.parametrize(
        "api_version,probed_url",
        [
            (APPFOLLOW_V2, "https://api.appfollow.io/api/v2/account/apps"),
            (APPFOLLOW_V3, "https://api.appfollow.io/api/v3/workspaces"),
            (None, "https://api.appfollow.io/api/v3/workspaces"),
        ],
    )
    def test_validate_credentials_probes_the_pinned_version(self, api_version, probed_url):
        with scripted_network([ScriptedResponse(json={})]) as network:
            ok, _ = self.source.validate_credentials(self.config, self.team_id, api_version=api_version)
        assert ok is True
        assert network.requests_log[0].url == probed_url

    @pytest.mark.parametrize("pinned", [APPFOLLOW_V2, APPFOLLOW_V3])
    def test_source_for_pipeline_dispatches_on_the_pin(self, pinned):
        result = SourceDriver(self.source, self.config).run("reviews", [ScriptedResponse(json={})], api_version=pinned)
        assert result.raised is None
        assert result.paths == [f"/api/{pinned}/account/apps" if pinned == APPFOLLOW_V2 else "/api/v3/workspaces"]
