import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.dynamics365.dynamics365 import (
    INVALID_ORGANIZATION_URL_ERROR,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.dynamics365.settings import (
    DYNAMICS365_ENDPOINTS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.dynamics365.source import (
    CREDENTIALS_REJECTED_ERROR,
    PERMISSION_ERROR,
    TABLE_MISSING_ERROR,
    UNREACHABLE_ERROR,
    Dynamics365Source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.dynamics365 import (
    Dynamics365SourceConfig,
)

PROBE_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.dynamics365.source.probe_credentials"
SOURCE_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.dynamics365.source.dynamics365_source"


class TestDynamics365Source:
    def setup_method(self) -> None:
        self.source = Dynamics365Source()
        self.team_id = 123
        self.config = Dynamics365SourceConfig(
            organization_url="https://contoso.crm.dynamics.com",
            tenant_id="72f988bf-86f1-41af-91ab-2d7cd011db47",
            client_id="cid",
            client_secret="sec",
        )

    def test_retargeting_the_environment_or_tenant_requires_new_secrets(self) -> None:
        # Both fields decide where the client secret and the minted token are sent.
        assert self.source.connection_host_fields == ["organization_url", "tenant_id"]

    def test_api_version_is_pinned_to_the_path_the_code_calls(self) -> None:
        assert self.source.supported_versions == ("v9.2",)
        assert self.source.default_version == "v9.2"
        assert self.source.resolve_api_version(None) == "v9.2"

    @pytest.mark.parametrize(
        "observed_error",
        [
            "HTTP 401 from the OAuth2 token endpoint: invalid_client [oauth2_token_config_error]",
            "401 Client Error: Unauthorized for url: https://contoso.crm.dynamics.com/api/data/v9.2/accounts",
            "403 Client Error: Forbidden for url: https://contoso.crm.dynamics.com/api/data/v9.2/incidents",
            "404 Client Error: Not Found for url: https://contoso.crm.dynamics.com/api/data/v9.2/campaigns",
            INVALID_ORGANIZATION_URL_ERROR,
        ],
    )
    def test_permanent_failures_are_non_retryable(self, observed_error: str) -> None:
        assert any(key in observed_error for key in self.source.get_non_retryable_errors())

    @pytest.mark.parametrize(
        "other_error",
        [
            "429 Client Error: Too Many Requests for url: https://contoso.crm.dynamics.com/api/data/v9.2/accounts",
            "503 Server Error: Service Unavailable for url: https://contoso.crm.dynamics.com/api/data/v9.2/accounts",
            "HTTP 429 from the OAuth2 token endpoint",
        ],
    )
    def test_throttles_and_server_errors_stay_retryable(self, other_error: str) -> None:
        assert not any(key in other_error for key in self.source.get_non_retryable_errors())

    def test_get_schemas_lists_every_endpoint_as_incrementable(self) -> None:
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert set(schemas) == set(ENDPOINTS)
        assert all(schema.supports_incremental for schema in schemas.values())
        # Dataverse exposes both tracking columns on every standard table.
        assert [field["field"] for field in schemas["Accounts"].incremental_fields] == ["modifiedon", "createdon"]
        assert schemas["Cases"].incremental_fields == INCREMENTAL_FIELDS["Cases"]

    def test_canonical_descriptions_cover_every_endpoint(self) -> None:
        descriptions = self.source.get_canonical_descriptions()

        assert set(descriptions) == set(ENDPOINTS)
        for name, entry in descriptions.items():
            columns = entry.get("columns") or {}
            # The GUID primary key and both tracking columns are always documented.
            assert DYNAMICS365_ENDPOINTS[name].primary_keys[0] in columns
            assert {"createdon", "modifiedon"} <= set(columns)

    @mock.patch(PROBE_PATCH)
    def test_validate_credentials_accepts_a_working_probe(self, mock_probe: mock.MagicMock) -> None:
        mock_probe.return_value = (True, 200)

        assert self.source.validate_credentials(self.config, self.team_id) == (True, None)
        assert mock_probe.call_args.args[4] == "v9.2"

    @pytest.mark.parametrize(
        "status, expected_message",
        [
            (401, CREDENTIALS_REJECTED_ERROR),
            (403, PERMISSION_ERROR),
            (404, TABLE_MISSING_ERROR),
            (500, UNREACHABLE_ERROR),
            (None, UNREACHABLE_ERROR),
        ],
    )
    @mock.patch(PROBE_PATCH)
    def test_validate_credentials_explains_the_failure(
        self, mock_probe: mock.MagicMock, status: int | None, expected_message: str
    ) -> None:
        mock_probe.return_value = (False, status)

        is_valid, message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is False
        assert message == expected_message

    @pytest.mark.parametrize(
        "schema_name, expected_ok_statuses",
        [
            # At source-create a valid token that can't read accounts must not block setup.
            (None, (200, 403)),
            # Checking one table must surface a missing grant for that table.
            ("Cases", (200,)),
        ],
    )
    @mock.patch(PROBE_PATCH)
    def test_validate_credentials_tolerates_403_only_at_source_create(
        self, mock_probe: mock.MagicMock, schema_name: str | None, expected_ok_statuses: tuple[int, ...]
    ) -> None:
        mock_probe.return_value = (True, 200)

        self.source.validate_credentials(self.config, self.team_id, schema_name)

        assert mock_probe.call_args.kwargs["ok_statuses"] == expected_ok_statuses
        assert mock_probe.call_args.args[5] == schema_name

    def test_validate_credentials_rejects_a_non_dataverse_environment_url(self) -> None:
        config = Dynamics365SourceConfig(
            organization_url="https://evil.test",
            tenant_id="72f988bf-86f1-41af-91ab-2d7cd011db47",
            client_id="cid",
            client_secret="sec",
        )

        is_valid, message = self.source.validate_credentials(config, self.team_id)

        assert is_valid is False
        assert message == INVALID_ORGANIZATION_URL_ERROR

    @mock.patch(SOURCE_PATCH)
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "Opportunities"
        inputs.team_id = 7
        inputs.job_id = "job-7"
        inputs.api_version = None
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2024-01-02T03:04:05Z"
        inputs.incremental_field = "createdon"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_source.call_args.kwargs
        assert kwargs["organization_url"] == "https://contoso.crm.dynamics.com"
        assert kwargs["tenant_id"] == "72f988bf-86f1-41af-91ab-2d7cd011db47"
        assert kwargs["client_id"] == "cid"
        assert kwargs["client_secret"] == "sec"
        assert kwargs["endpoint"] == "Opportunities"
        assert kwargs["api_version"] == "v9.2"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2024-01-02T03:04:05Z"
        assert kwargs["incremental_field"] == "createdon"

    @mock.patch(SOURCE_PATCH)
    def test_source_for_pipeline_omits_last_value_on_full_refresh(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "Accounts"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2024-01-02T03:04:05Z"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_source.call_args.kwargs["db_incremental_field_last_value"] is None

    @mock.patch(SOURCE_PATCH)
    def test_source_for_pipeline_honours_a_pinned_api_version(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "Accounts"
        inputs.api_version = "v9.1"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_source.call_args.kwargs["api_version"] == "v9.1"
