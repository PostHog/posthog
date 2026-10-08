import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.appfollow.settings import (
    APPFOLLOW_V2,
    APPFOLLOW_V3,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.appfollow.source import AppfollowSource
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

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["reviews"])
        assert len(schemas) == 1
        assert schemas[0].name == "reviews"

    @pytest.mark.parametrize(
        "status,expected_ok",
        [
            (200, True),
            # A single account-wide token: a 403 still proves the token is genuine.
            (403, True),
            (401, False),
            (402, False),
            (500, False),
            (None, False),
        ],
    )
    def test_validate_credentials(self, status, expected_ok):
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.appfollow.source.check_credentials",
            return_value=status,
        ):
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
        session = mock.MagicMock()
        session.get.return_value.status_code = 200
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.appfollow.appfollow.make_tracked_session",
            return_value=session,
        ):
            ok, _ = self.source.validate_credentials(self.config, self.team_id, api_version=api_version)
        assert ok is True
        assert session.get.call_args.args[0] == probed_url

    @pytest.mark.parametrize("pinned", [APPFOLLOW_V2, APPFOLLOW_V3])
    def test_source_for_pipeline_dispatches_on_the_pin(self, pinned):
        inputs = mock.MagicMock(api_version=pinned, schema_name="reviews", should_use_incremental_field=False)
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.appfollow.source.appfollow_source"
        ) as appfollow_source:
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
        assert appfollow_source.call_args.kwargs["api_version"] == pinned
