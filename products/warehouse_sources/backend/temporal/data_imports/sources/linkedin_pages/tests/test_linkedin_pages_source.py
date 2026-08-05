import json
import datetime as dt
from typing import Any, Optional

import pytest
from unittest import mock

from requests import Response

from posthog.schema import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceFieldOauthAccountSelectConfig,
    SourceFieldOauthConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.integration_accounts import (
    IntegrationAccountListingError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.linkedinpages import (
    LinkedinPagesSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.linkedin_pages.linkedin_pages import (
    AdministeredOrganization,
    LinkedinPagesClient,
    LinkedinPagesResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.linkedin_pages.settings import (
    ENDPOINTS,
    LINKEDIN_PAGES_ENDPOINTS,
    EndpointKind,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.linkedin_pages.source import (
    INTEGRATION_KIND,
    LinkedinPagesSource,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

PROBE_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.linkedin_pages.source.probe_credentials"
PIPELINE_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.linkedin_pages.source.linkedin_pages_source"
)
INTEGRATION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.linkedin_pages.source"
    ".LinkedinPagesSource.get_oauth_integration"
)
SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.linkedin_pages.linkedin_pages"
    ".make_tracked_session"
)

STATS_ENDPOINTS = sorted(
    name for name, config in LINKEDIN_PAGES_ENDPOINTS.items() if config.kind is EndpointKind.TIME_SERIES
)
FULL_REFRESH_ENDPOINTS = sorted(
    name for name, config in LINKEDIN_PAGES_ENDPOINTS.items() if config.kind is not EndpointKind.TIME_SERIES
)


def _inputs(schema_name: str = "page_statistics", **overrides: Any) -> mock.MagicMock:
    defaults: dict[str, Any] = {
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
        "api_version": None,
    }
    defaults.update(overrides)
    return mock.MagicMock(**defaults)


def _integration(access_token: Optional[str] = "at_1", kind: str = INTEGRATION_KIND) -> mock.MagicMock:
    integration = mock.MagicMock()
    integration.access_token = access_token
    integration.kind = kind
    return integration


def _error_from_status(status: int, body: dict[str, Any]) -> str:
    """Raise the client's own error for a status and return its message.

    Keeps `get_non_retryable_errors` honest: the keys have to match what the transport actually
    raises, not a message written from memory.
    """
    response = Response()
    response.status_code = status
    response._content = json.dumps(body).encode()
    session = mock.MagicMock()
    session.get.return_value = response

    with mock.patch(SESSION_PATCH, return_value=session):
        client = LinkedinPagesClient("at_1")
        with pytest.raises(Exception) as excinfo:
            client.request("/organizationPageStatistics", {"q": "organization"})
    return str(excinfo.value)


class TestLinkedinPagesSource:
    def setup_method(self) -> None:
        self.source = LinkedinPagesSource()
        self.team_id = 123
        self.config = LinkedinPagesSourceConfig(
            linkedin_pages_integration_id=7,
            organization_ids=None,
        )

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.LINKEDINPAGES

    def test_get_source_config_ships_released(self) -> None:
        config = self.source.get_source_config

        assert config.name.value == "LinkedinPages"
        assert config.label == "LinkedIn Pages"
        assert config.category == DataWarehouseSourceCategory.COMMUNICATION
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert not config.unreleasedSource
        assert config.iconPath == "/static/services/linkedin_pages.png"

    def test_credentials_come_from_a_posthog_owned_oauth_app(self) -> None:
        fields = {field.name: field for field in self.source.get_source_config.fields}

        oauth = fields["linkedin_pages_integration_id"]
        assert isinstance(oauth, SourceFieldOauthConfig)
        assert oauth.kind == "linkedin-pages"
        assert oauth.required is True
        # Without these the frontend can't warn a user whose grant predates a scope change.
        assert oauth.requiredScopes is not None
        assert set(oauth.requiredScopes.split()) == {"rw_organization_admin", "r_organization_social"}

        pages = fields["organization_ids"]
        assert isinstance(pages, SourceFieldOauthAccountSelectConfig)
        assert pages.integrationField == "linkedin_pages_integration_id"
        assert pages.multiple is True
        # Blank means every page the connected account administers, so it can't be required.
        assert not pages.required

        # The user never supplies their own OAuth client or token.
        assert not {"client_id", "client_secret", "refresh_token"} & set(fields)

    def test_api_version_metadata(self) -> None:
        assert self.source.default_version in self.source.supported_versions
        assert len(self.source.supported_versions) == 1
        # LinkedIn requires a dated version header on every request.
        assert self.source.default_version.isdigit()
        assert self.source.api_docs_url.startswith("https://")

    def test_get_schemas_lists_every_endpoint(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)

    @pytest.mark.parametrize("name", STATS_ENDPOINTS)
    def test_statistics_endpoints_are_incremental_on_date(self, name: str) -> None:
        schema = next(s for s in self.source.get_schemas(self.config, self.team_id) if s.name == name)

        assert schema.supports_incremental is True
        assert {field["field"] for field in schema.incremental_fields} == {"date"}

    @pytest.mark.parametrize("name", FULL_REFRESH_ENDPOINTS)
    def test_endpoints_without_a_server_side_filter_are_full_refresh(self, name: str) -> None:
        schema = next(s for s in self.source.get_schemas(self.config, self.team_id) if s.name == name)

        assert schema.supports_incremental is False
        assert schema.incremental_fields == []

    @pytest.mark.parametrize(
        "names, expected",
        [
            (["posts"], {"posts"}),
            (["posts", "organizations"], {"posts", "organizations"}),
            (["nonexistent"], set()),
        ],
    )
    def test_get_schemas_filtered_by_names(self, names: list[str], expected: set[str]) -> None:
        assert {s.name for s in self.source.get_schemas(self.config, self.team_id, names=names)} == expected

    def test_canonical_descriptions_cover_every_endpoint(self) -> None:
        descriptions = self.source.get_canonical_descriptions()

        assert set(descriptions) == set(ENDPOINTS)

    @pytest.mark.parametrize(
        "status, body",
        [
            (401, {"serviceErrorCode": 65601, "message": "Invalid access token"}),
            (403, {"serviceErrorCode": 100, "message": "Not enough permissions"}),
            (404, {"code": "RESOURCE_NOT_FOUND", "message": "unknown organization"}),
        ],
    )
    def test_non_retryable_errors_match_what_the_transport_raises(self, status: int, body: dict[str, Any]) -> None:
        message = _error_from_status(status, body)

        assert any(key in message for key in self.source.get_non_retryable_errors())

    @pytest.mark.parametrize(
        "probe_result, schema_name, expected_valid",
        [
            ((True, 200), None, True),
            ((True, 200), "posts", True),
            ((False, 401), None, False),
            ((False, None), None, False),
            # A valid token missing the admin scope must not block source creation, but it does
            # block the table that needs it.
            ((False, 403), None, True),
            ((False, 403), "page_statistics", False),
        ],
    )
    def test_validate_credentials(
        self, probe_result: tuple[bool, Optional[int]], schema_name: Optional[str], expected_valid: bool
    ) -> None:
        with (
            mock.patch(INTEGRATION_PATCH, return_value=_integration()),
            mock.patch(PROBE_PATCH, return_value=probe_result),
        ):
            is_valid, message = self.source.validate_credentials(self.config, self.team_id, schema_name=schema_name)

        assert is_valid is expected_valid
        assert (message is None) is expected_valid

    @pytest.mark.parametrize(
        "integration_id, integration",
        [
            (0, None),
            (7, ValueError("Missing integration")),
            (7, _integration(access_token=None)),
        ],
    )
    def test_validate_credentials_fails_cleanly_without_a_usable_integration(
        self, integration_id: int, integration: Any
    ) -> None:
        config = LinkedinPagesSourceConfig(linkedin_pages_integration_id=integration_id, organization_ids=None)
        patched = (
            mock.patch(INTEGRATION_PATCH, side_effect=integration)
            if isinstance(integration, Exception)
            else mock.patch(INTEGRATION_PATCH, return_value=integration)
        )

        with patched, mock.patch(PROBE_PATCH) as probe:
            is_valid, message = self.source.validate_credentials(config, self.team_id)

        assert is_valid is False
        assert message is not None
        # Never probe LinkedIn with a token we don't have.
        assert probe.call_count == 0

    def test_validate_credentials_probes_with_the_integration_token(self) -> None:
        with (
            mock.patch(INTEGRATION_PATCH, return_value=_integration()),
            mock.patch(PROBE_PATCH, return_value=(True, 200)) as probe,
        ):
            self.source.validate_credentials(self.config, self.team_id)

        assert probe.call_args.args[0] == "at_1"
        assert probe.call_args.kwargs["api_version"] == self.source.default_version

    def test_get_oauth_accounts_lists_administered_pages(self) -> None:
        integration = _integration()
        integration.errors = ""
        organizations = [
            AdministeredOrganization(urn="urn:li:organization:1", name="Acme"),
            AdministeredOrganization(urn="urn:li:organization:2", name="Acme Labs"),
        ]

        with (
            mock.patch(INTEGRATION_PATCH, return_value=integration),
            mock.patch("posthog.models.integration.OauthIntegration.access_token_expired", return_value=False),
            mock.patch.object(LinkedinPagesClient, "list_administered_organizations", return_value=organizations),
        ):
            accounts = self.source.get_oauth_accounts(7, self.team_id)

        assert [(account.value, account.display_name) for account in accounts] == [
            ("urn:li:organization:1", "Acme"),
            ("urn:li:organization:2", "Acme Labs"),
        ]

    def test_get_oauth_accounts_reports_a_missing_integration_as_actionable(self) -> None:
        with mock.patch(INTEGRATION_PATCH, side_effect=ValueError("Missing integration ID")):
            with pytest.raises(IntegrationAccountListingError):
                self.source.get_oauth_accounts(0, self.team_id)

    def test_get_oauth_accounts_refuses_an_integration_of_another_kind(self) -> None:
        # The integration ID is client-supplied and the lookup filters only on ID and team, so a
        # Slack (or any other) integration's token must never be handed to LinkedIn.
        with (
            mock.patch(INTEGRATION_PATCH, return_value=_integration(kind="slack")),
            mock.patch.object(LinkedinPagesClient, "list_administered_organizations") as list_organizations,
        ):
            with pytest.raises(IntegrationAccountListingError):
                self.source.get_oauth_accounts(7, self.team_id)

        assert list_organizations.call_count == 0

    def test_validate_credentials_refuses_an_integration_of_another_kind(self) -> None:
        with (
            mock.patch(INTEGRATION_PATCH, return_value=_integration(kind="slack")),
            mock.patch(PROBE_PATCH) as probe,
        ):
            is_valid, message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is False
        assert message is not None
        assert probe.call_count == 0

    def test_source_for_pipeline_refuses_an_integration_of_another_kind(self) -> None:
        with (
            mock.patch(INTEGRATION_PATCH, return_value=_integration(kind="slack")),
            mock.patch(PIPELINE_PATCH) as pipeline,
        ):
            with pytest.raises(ValueError):
                self.source.source_for_pipeline(self.config, mock.MagicMock(), _inputs())

        assert pipeline.call_count == 0

    def test_resumable_manager_is_namespaced_per_endpoint(self) -> None:
        manager = self.source.get_resumable_source_manager(_inputs("posts"))
        other = self.source.get_resumable_source_manager(_inputs("page_statistics"))

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is LinkedinPagesResumeConfig
        # A window start and a page token are not interchangeable, so the slots must differ.
        assert manager._key != other._key

    def test_source_for_pipeline_plumbs_the_integration_token(self) -> None:
        inputs = _inputs(
            schema_name="page_statistics",
            should_use_incremental_field=True,
            db_incremental_field_last_value=dt.date(2026, 5, 1),
        )
        manager = mock.MagicMock()
        config = LinkedinPagesSourceConfig(linkedin_pages_integration_id=7, organization_ids=["urn:li:organization:1"])

        with mock.patch(INTEGRATION_PATCH, return_value=_integration()), mock.patch(PIPELINE_PATCH) as pipeline:
            self.source.source_for_pipeline(config, manager, inputs)

        kwargs = pipeline.call_args.kwargs
        assert kwargs["access_token"] == "at_1"
        assert kwargs["organization_ids"] == ["urn:li:organization:1"]
        assert kwargs["endpoint"] == "page_statistics"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == dt.date(2026, 5, 1)
        assert kwargs["api_version"] == self.source.default_version

    def test_source_for_pipeline_refuses_to_run_without_an_access_token(self) -> None:
        with mock.patch(INTEGRATION_PATCH, return_value=_integration(access_token=None)):
            with pytest.raises(ValueError):
                self.source.source_for_pipeline(self.config, mock.MagicMock(), _inputs())

    def test_source_for_pipeline_drops_the_watermark_on_a_full_refresh(self) -> None:
        inputs = _inputs(should_use_incremental_field=False, db_incremental_field_last_value=dt.date(2026, 5, 1))

        with mock.patch(INTEGRATION_PATCH, return_value=_integration()), mock.patch(PIPELINE_PATCH) as pipeline:
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert pipeline.call_args.kwargs["db_incremental_field_last_value"] is None

    def test_documented_tables_are_published_without_credentials(self) -> None:
        # The endpoint catalog is static, so posthog.com can render it.
        assert self.source.lists_tables_without_credentials is True

        tables = self.source.get_documented_tables()

        assert {table["name"] for table in tables} == set(ENDPOINTS)
