import pytest
from unittest import mock

from parameterized import parameterized

from posthog.schema import SourceFieldSelectConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.cal_com.source import CalComSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.calcom import CalComSourceConfig

SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.cal_com.source"


class TestCalComSource:
    def setup_method(self) -> None:
        self.source = CalComSource()
        self.team_id = 123
        self.config = CalComSourceConfig(api_key="cal_live_key", region="us")

    def test_region_field_defaults_to_us(self) -> None:
        # Every connection made before this field existed talks to the US host, so the default must
        # stay "us" or those syncs start pointing at the EU host.
        config = self.source.get_source_config
        field = next(f for f in config.fields if isinstance(f, SourceFieldSelectConfig) and f.name == "region")
        assert field.defaultValue == "us"
        assert {option.value for option in field.options} == {"us", "eu"}

    def test_no_connection_host_fields(self) -> None:
        # `region` only picks between two fixed Cal.com hosts, so it can't be used to retarget a
        # preserved key at a server the editor controls.
        assert self.source.connection_host_fields == []

    @parameterized.expand(
        [
            ("401 Client Error: Unauthorized for url: https://api.cal.com/v2/bookings?limit=250",),
            ("403 Client Error: Forbidden for url: https://api.cal.com/v2/me",),
            ("401 Client Error: Unauthorized for url: https://api.cal.eu/v2/bookings?limit=250",),
            ("403 Client Error: Forbidden for url: https://api.cal.eu/v2/me",),
        ]
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            ("500 Server Error: Internal Server Error for url: https://api.cal.com/v2/bookings",),
            ("429 Client Error: Too Many Requests for url: https://api.cal.com/v2/teams",),
        ]
    )
    def test_non_retryable_errors_ignore_transient(self, unrelated_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in unrelated_error for key in non_retryable)

    @mock.patch(f"{SOURCE_MODULE}.cal_com_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "bookings"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"
        inputs.incremental_field = "updatedAt"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_key"] == "cal_live_key"
        assert kwargs["endpoint"] == "bookings"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["region"] == "us"
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01T00:00:00Z"
        assert kwargs["incremental_field"] == "updatedAt"

    @mock.patch(f"{SOURCE_MODULE}.cal_com_source")
    def test_source_for_pipeline_drops_incremental_value_when_disabled(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "bookings"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        kwargs = mock_source.call_args.kwargs
        assert kwargs["db_incremental_field_last_value"] is None

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "not_a_table"
        with pytest.raises(ValueError, match="Unknown Cal.com schema 'not_a_table'"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

    @parameterized.expand(
        [
            ("organization_users", True),
            ("routing_form_responses", True),
            ("bookings", False),
        ]
    )
    @mock.patch(f"{SOURCE_MODULE}.cal_com_source")
    @mock.patch(f"{SOURCE_MODULE}.resolve_organization_id", return_value=77)
    def test_source_for_pipeline_resolves_the_org_only_where_a_path_needs_it(
        self, schema_name: str, needs_org: bool, mock_resolve: mock.MagicMock, mock_source: mock.MagicMock
    ) -> None:
        # An org lookup is an extra request per sync; a path with no {orgId} must not pay it.
        inputs = mock.MagicMock()
        inputs.schema_name = schema_name

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_source.call_args.kwargs["organization_id"] == (77 if needs_org else None)
        assert mock_resolve.called is needs_org


class TestCalComEndpointPermissions:
    def setup_method(self) -> None:
        self.source = CalComSource()
        self.config = CalComSourceConfig(api_key="cal_live_key", region="us")
        self.endpoints = ["bookings", "organization_users", "routing_form_responses"]

    @mock.patch(f"{SOURCE_MODULE}.resolve_organization_id", return_value=None)
    def test_org_tables_are_flagged_for_a_personal_account(self, _mock_resolve: mock.MagicMock) -> None:
        permissions = self.source.get_endpoint_permissions(self.config, 1, self.endpoints)

        assert permissions["bookings"] is None
        assert "not in a Cal.com organization" in (permissions["organization_users"] or "")
        assert "not in a Cal.com organization" in (permissions["routing_form_responses"] or "")

    @mock.patch(f"{SOURCE_MODULE}.check_organization_access", return_value="needs an admin key")
    @mock.patch(f"{SOURCE_MODULE}.resolve_organization_id", return_value=77)
    def test_org_tables_are_flagged_for_a_non_admin_member(
        self, _mock_resolve: mock.MagicMock, _mock_access: mock.MagicMock
    ) -> None:
        permissions = self.source.get_endpoint_permissions(self.config, 1, self.endpoints)

        assert permissions == {
            "bookings": None,
            "organization_users": "needs an admin key",
            "routing_form_responses": "needs an admin key",
        }

    @mock.patch(f"{SOURCE_MODULE}.resolve_organization_id", side_effect=Exception("boom"))
    def test_an_unreachable_probe_leaves_every_table_selectable(self, _mock_resolve: mock.MagicMock) -> None:
        # The table picker must never be blocked by a failed probe.
        assert self.source.get_endpoint_permissions(self.config, 1, self.endpoints) == dict.fromkeys(self.endpoints)

    @mock.patch(f"{SOURCE_MODULE}.resolve_organization_id")
    def test_no_probe_when_no_org_table_is_requested(self, mock_resolve: mock.MagicMock) -> None:
        assert self.source.get_endpoint_permissions(self.config, 1, ["bookings"]) == {"bookings": None}
        mock_resolve.assert_not_called()
