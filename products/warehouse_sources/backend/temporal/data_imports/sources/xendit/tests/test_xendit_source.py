import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.xendit import XenditSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.xendit.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.xendit.settings import ENDPOINTS, XENDIT_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.xendit.source import XenditSource
from products.warehouse_sources.backend.temporal.data_imports.sources.xendit.xendit import XenditResumeConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType

VALIDATE_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.xendit.source.validate_xendit_credentials"
)
SOURCE_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.xendit.source.xendit_source"


def _make_inputs(schema_name: str = "transactions", **overrides):
    defaults = {
        "schema_name": schema_name,
        "schema_id": "schema-1",
        "source_id": "source-1",
        "team_id": 1,
        "should_use_incremental_field": False,
        "db_incremental_field_last_value": None,
        "db_incremental_field_earliest_value": None,
        "incremental_field": None,
        "incremental_field_type": None,
        "job_id": "job-1",
        "logger": mock.MagicMock(),
        "reset_pipeline": False,
    }
    defaults.update(overrides)
    return mock.MagicMock(**defaults)


class TestXenditSource:
    def setup_method(self):
        self.source = XenditSource()
        self.team_id = 123
        self.config = XenditSourceConfig(api_key="xnd_test_key")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.XENDIT

    def test_connection_host_fields_pin_sub_account(self):
        # Retargeting the stored key at another sub-account must force credential re-entry.
        assert self.source.connection_host_fields == ["sub_account_user_id"]

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Xendit"
        assert config.label == "Xendit"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        # A finished source ships visible: unreleasedSource hides it from users entirely.
        assert not config.unreleasedSource
        assert config.iconPath == "/static/services/xendit.png"

        fields = {field.name: field for field in config.fields if isinstance(field, SourceFieldInputConfig)}
        assert set(fields) == {"api_key", "sub_account_user_id"}
        assert fields["api_key"].type == SourceFieldInputConfigType.PASSWORD
        assert fields["api_key"].required is True
        assert fields["api_key"].secret is True
        # The sub-account id is a xenPlatform-only routing hint, not a credential.
        assert fields["sub_account_user_id"].required is False
        assert fields["sub_account_user_id"].secret is False

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.xendit.co/transactions?limit=50",
            "403 Client Error: Forbidden for url: https://api.xendit.co/v2/accounts?limit=50",
        ],
    )
    def test_auth_failures_are_non_retryable(self, observed_error):
        assert any(key in observed_error for key in self.source.get_non_retryable_errors())

    def test_get_schemas_lists_every_endpoint(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)

    @pytest.mark.parametrize("name", sorted(ENDPOINTS))
    def test_endpoints_advertise_both_server_side_filters(self, name):
        schema = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}[name]

        assert schema.supports_incremental is True
        assert {field["field"] for field in schema.incremental_fields} == {"updated", "created"}

    def test_sub_account_table_is_not_synced_by_default(self):
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}

        assert schemas["transactions"].should_sync_default is True
        # Sub-accounts only exist for xenPlatform merchants, so selecting it is opt-in.
        assert schemas["accounts"].should_sync_default is False

    @pytest.mark.parametrize(
        "names, expected",
        [
            (["transactions"], {"transactions"}),
            (["nonexistent"], set()),
        ],
    )
    def test_get_schemas_filtered_by_names(self, names, expected):
        assert {s.name for s in self.source.get_schemas(self.config, self.team_id, names=names)} == expected

    def test_canonical_descriptions_cover_every_endpoint(self):
        assert set(CANONICAL_DESCRIPTIONS) == set(ENDPOINTS)

    @pytest.mark.parametrize(
        "status, schema_name, expected_valid, expected_message",
        [
            (200, None, True, None),
            (200, "transactions", True, None),
            # A key without a table's permission is still a real key, so source creation succeeds
            # and only the per-table check rejects it.
            (403, None, True, None),
            (403, "accounts", False, "Your Xendit API key is missing the Accounts Read permission"),
            (401, None, False, "Invalid Xendit API key"),
            (None, None, False, "Invalid Xendit API key"),
        ],
    )
    @mock.patch(VALIDATE_PATCH)
    def test_validate_credentials(self, mock_validate, status, schema_name, expected_valid, expected_message):
        mock_validate.return_value = (status == 200, status)

        is_valid, message = self.source.validate_credentials(self.config, self.team_id, schema_name=schema_name)

        assert (is_valid, message) == (expected_valid, expected_message)

    @mock.patch(VALIDATE_PATCH)
    def test_validate_credentials_probes_the_requested_table(self, mock_validate):
        mock_validate.return_value = (True, 200)

        self.source.validate_credentials(self.config, self.team_id, schema_name="accounts")

        assert mock_validate.call_args.args[1] == XENDIT_ENDPOINTS["accounts"].path

    @pytest.mark.parametrize(
        "status, expected",
        [
            (200, None),
            (403, "Your Xendit API key is missing the Transaction Read permission"),
            # A throttle or a blip is not a permission problem, so the table stays selectable.
            (429, None),
            (None, None),
        ],
    )
    @mock.patch(VALIDATE_PATCH)
    def test_get_endpoint_permissions(self, mock_validate, status, expected):
        mock_validate.return_value = (status == 200, status)

        permissions = self.source.get_endpoint_permissions(self.config, self.team_id, ["transactions"])

        assert permissions == {"transactions": expected}

    @mock.patch(VALIDATE_PATCH)
    def test_get_endpoint_permissions_ignores_unknown_tables(self, mock_validate):
        assert self.source.get_endpoint_permissions(self.config, self.team_id, ["nonexistent"]) == {"nonexistent": None}
        mock_validate.assert_not_called()

    def test_get_resumable_source_manager_bound_to_resume_config(self):
        manager = self.source.get_resumable_source_manager(_make_inputs())

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is XenditResumeConfig

    @mock.patch(SOURCE_PATCH)
    def test_source_for_pipeline_plumbs_arguments(self, mock_xendit_source):
        config = XenditSourceConfig(api_key="xnd_test_key", sub_account_user_id="sub-1")
        inputs = _make_inputs(
            schema_name="transactions",
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-01-01T00:00:00.000Z",
            incremental_field="updated",
        )
        manager = mock.MagicMock()

        self.source.source_for_pipeline(config, manager, inputs)

        kwargs = mock_xendit_source.call_args.kwargs
        assert kwargs["api_key"] == "xnd_test_key"
        assert kwargs["endpoint"] == "transactions"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01T00:00:00.000Z"
        assert kwargs["incremental_field"] == "updated"
        assert kwargs["for_user_id"] == "sub-1"

    @mock.patch(SOURCE_PATCH)
    def test_source_for_pipeline_drops_last_value_when_not_incremental(self, mock_xendit_source):
        inputs = _make_inputs(
            should_use_incremental_field=False,
            db_incremental_field_last_value="2026-01-01T00:00:00.000Z",
        )

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_xendit_source.call_args.kwargs["db_incremental_field_last_value"] is None
