import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.intercom import (
    IntercomSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.intercom.settings import INTERCOM_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.intercom.source import IntercomSource


class TestIntercomSource:
    def setup_method(self):
        self.source = IntercomSource()
        self.team_id = 123
        self.config = IntercomSourceConfig(intercom_integration_id=456)
        self.manager = mock.MagicMock()

    @pytest.mark.parametrize("schema_name,expected", [("contacts", True), ("companies", False)])
    def test_retry_budget_excludes_companies_scroll(self, schema_name, expected):
        assert self.source.resume_covers_run(incremental_or_append=False, schema_name=schema_name) is expected

    def test_default_version_is_latest(self):
        # New sources are stamped with the default; keep it on the newest supported version.
        assert self.source.default_version == "2.17"
        assert self.source.default_version in self.source.supported_versions

    @pytest.mark.parametrize(
        "error_msg",
        [
            "400 Client Error: Bad Request for url: https://api.intercom.io/companies/scroll",
        ],
    )
    def test_companies_scroll_exists_exhaustion_is_retryable(self, error_msg):
        # Opening a companies scroll retries a `scroll_exists` lock inline (see
        # `_open_companies_scroll`), but a lock held longer than that budget exhausts it and
        # the raw error propagates. A fresh Temporal attempt opens cleanly once the stale
        # scroll expires, so this should stay out of error tracking the same way the 404
        # scroll-expiry case above does.
        retryable_errors = self.source.get_retryable_errors()
        assert any(key in error_msg for key in retryable_errors)

    @pytest.mark.parametrize(
        "pin,has_macros,has_contact_activities",
        [
            ("2.13", False, False),
            ("2.15", False, False),
            ("2.16", True, False),
            ("2.17", True, True),
            (None, True, True),
        ],
    )
    def test_get_schemas_hides_tables_the_pinned_version_does_not_serve(
        self, pin: str | None, has_macros: bool, has_contact_activities: bool
    ):
        names = {s.name for s in self.source.get_schemas(self.config, self.team_id, api_version=pin)}

        assert {name for name, cfg in INTERCOM_ENDPOINTS.items() if cfg.api_versions is None} <= names
        assert ("macros" in names) is has_macros
        assert ("contact_activities" in names) is has_contact_activities

    @pytest.mark.parametrize(
        "pin,expected", [("2.13", "2.13"), ("2.15", "2.15"), ("2.16", "2.16"), ("2.17", "2.17"), (None, "2.17")]
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.intercom.source.IntercomSource.get_oauth_integration"
    )
    def test_validate_credentials_probes_under_resolved_pin(self, mock_get_integration, pin, expected):
        # The probe must run on the source's pin, not a hardcoded version — otherwise a
        # 2.13-pinned source validates against 2.15 and can report a scope it doesn't have.
        mock_get_integration.return_value = mock.MagicMock(access_token="token")

        with scripted_network([ScriptedResponse(status=200, json={"type": "admin"})]) as network:
            result = self.source.validate_credentials(self.config, self.team_id, api_version=pin)

        assert result == (True, None)
        assert network.requests_log[0].path == "/me"
        assert network.requests_log[0].headers["intercom-version"] == expected

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.intercom.source.IntercomSource.get_oauth_integration"
    )
    def test_validate_credentials_integration_value_error(self, mock_get_integration):
        mock_get_integration.side_effect = ValueError("Integration not found: 162559")

        is_valid, error = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is False
        assert error == "Intercom integration not found. Please reconnect your Intercom integration."

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.intercom.source.IntercomSource.get_oauth_integration"
    )
    def test_validate_credentials_no_access_token(self, mock_get_integration):
        mock_get_integration.return_value = mock.MagicMock(access_token=None)

        is_valid, error = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is False
        assert error is not None and "no access token" in error

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.intercom.source.intercom_source")
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.intercom.source.IntercomSource.get_oauth_integration"
    )
    def test_source_for_pipeline_plumbing(self, mock_get_integration, mock_intercom_source):
        mock_get_integration.return_value = mock.MagicMock(access_token="token")
        sentinel = mock.MagicMock()
        mock_intercom_source.return_value = sentinel

        inputs = mock.MagicMock()
        inputs.team_id = self.team_id
        inputs.job_id = "job-1"
        inputs.schema_name = "contacts"
        inputs.api_version = "2.13"
        inputs.should_use_incremental_field = True
        inputs.incremental_field = "updated_at"
        inputs.db_incremental_field_last_value = "1700000000"

        result = self.source.source_for_pipeline(self.config, self.manager, inputs)

        assert result is sentinel
        mock_intercom_source.assert_called_once_with(
            access_token="token",
            endpoint="contacts",
            team_id=self.team_id,
            job_id="job-1",
            api_version="2.13",
            resumable_source_manager=self.manager,
            should_use_incremental_field=True,
            incremental_field="updated_at",
            db_incremental_field_last_value="1700000000",
            cursor_manager=None,
        )

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.intercom.source.intercom_source")
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.intercom.source.IntercomSource.get_oauth_integration"
    )
    def test_source_for_pipeline_drops_incremental_args_when_not_incremental(
        self, mock_get_integration, mock_intercom_source
    ):
        mock_get_integration.return_value = mock.MagicMock(access_token="token")

        inputs = mock.MagicMock()
        inputs.team_id = self.team_id
        inputs.job_id = "job-1"
        inputs.schema_name = "companies"
        inputs.should_use_incremental_field = False
        inputs.incremental_field = "updated_at"
        inputs.db_incremental_field_last_value = "1700000000"

        self.source.source_for_pipeline(self.config, self.manager, inputs)

        _, kwargs = mock_intercom_source.call_args
        assert kwargs["incremental_field"] is None
        assert kwargs["db_incremental_field_last_value"] is None

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.intercom.source.IntercomSource.get_oauth_integration"
    )
    def test_source_for_pipeline_no_access_token_raises(self, mock_get_integration):
        mock_get_integration.return_value = mock.MagicMock(access_token=None)

        result = SourceDriver(self.source, self.config).run("contacts", [], team_id=self.team_id, job_id="job-1")

        assert isinstance(result.raised, ValueError)
        assert str(result.raised) == "Intercom access token not found for job job-1"
