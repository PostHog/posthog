from typing import Any

import pytest
from unittest import mock

from posthog.schema import (
    ReleaseStatus,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldOauthConfig,
    SourceFieldSelectConfig,
)

from posthog.models.integration import Integration

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.display_video_360.display_video_360 import (
    DisplayVideo360ResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.display_video_360.settings import (
    DISPLAY_VIDEO_360_ENDPOINTS,
    ENDPOINTS,
    REPORT_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.display_video_360.source import (
    DisplayVideo360Source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.displayvideo360 import (
    DisplayVideo360AuthTypeConfig,
    DisplayVideo360SourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

INCREMENTAL_ENTITY_ENDPOINTS = {"advertisers", "campaigns", "insertion_orders", "line_items"}
FULL_REFRESH_ENDPOINTS = {"partners", "creatives"}

SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.display_video_360.source"


def _make_config(**overrides: Any) -> DisplayVideo360SourceConfig:
    auth = overrides.pop(
        "auth_type",
        DisplayVideo360AuthTypeConfig(selection="service_account", service_account_key='{"client_email": "a"}'),
    )
    defaults: dict[str, Any] = {"partner_id": "1234", "advertiser_ids": None}
    defaults.update(overrides)
    return DisplayVideo360SourceConfig(auth_type=auth, **defaults)


def _oauth_config(integration_id: int | None = 42) -> DisplayVideo360SourceConfig:
    return _make_config(
        auth_type=DisplayVideo360AuthTypeConfig(selection="oauth", display_video_360_integration_id=integration_id)
    )


def _make_inputs(**overrides: Any) -> SourceInputs:
    defaults: dict[str, Any] = {
        "schema_name": "line_items",
        "schema_id": "schema-1",
        "source_id": "source-1",
        "team_id": 7,
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
    return SourceInputs(**defaults)


class TestDisplayVideo360Source:
    def setup_method(self) -> None:
        self.source = DisplayVideo360Source()
        self.team_id = 7
        self.config = _make_config()

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.DISPLAYVIDEO360

    def test_source_config_is_released_in_alpha(self) -> None:
        config = self.source.get_source_config

        assert not config.unreleasedSource
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.iconPath == "/static/services/display_video_360.png"
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/display-video-360"

    def test_api_version_metadata(self) -> None:
        assert self.source.supported_versions == ("v4",)
        assert self.source.default_version == "v4"
        assert self.source.api_docs_url.startswith("https://")

    def test_lists_tables_without_credentials(self) -> None:
        # get_schemas walks a static endpoint catalog with no I/O, so the public docs can render it.
        assert self.source.lists_tables_without_credentials is True

    def test_account_scope_fields_require_credential_reentry(self) -> None:
        # Changing the partner or advertiser scope must re-require the credential (exfiltration gate).
        assert self.source.connection_host_fields == ["partner_id", "advertiser_ids"]

    def test_oauth_scope_change_keeps_the_row_backed_grant_gated(self) -> None:
        # The OAuth refresh token lives in an Integration row, not job_inputs, so the serializer's
        # generic preserved-credentials check can't see it. Report it as preserved so a
        # partner_id/advertiser_ids change can't silently reuse someone else's Google grant.
        source_model = mock.Mock(
            job_inputs={"auth_type": {"selection": "oauth", "display_video_360_integration_id": 42}}
        )

        assert self.source.has_preserved_row_backed_credentials(source_model, {"partner_id": "999"}) is True
        assert (
            self.source.has_preserved_row_backed_credentials(
                source_model,
                {"partner_id": "999", "auth_type": {"selection": "oauth", "display_video_360_integration_id": 42}},
            )
            is True
        )

    def test_connecting_another_google_account_is_an_explicit_reauthorization(self) -> None:
        source_model = mock.Mock(
            job_inputs={"auth_type": {"selection": "oauth", "display_video_360_integration_id": 42}}
        )

        assert (
            self.source.has_preserved_row_backed_credentials(
                source_model,
                {"partner_id": "999", "auth_type": {"selection": "oauth", "display_video_360_integration_id": 43}},
            )
            is False
        )

    @pytest.mark.parametrize(
        "job_inputs",
        [
            {},
            {"auth_type": {"selection": "service_account", "service_account_key": "{}"}},
            # OAuth selected but no account connected yet — nothing is being reused.
            {"auth_type": {"selection": "oauth", "display_video_360_integration_id": None}},
        ],
        ids=["no-job-inputs", "service-account", "oauth-not-connected"],
    )
    def test_no_row_backed_credentials_without_a_connected_account(self, job_inputs: dict[str, Any]) -> None:
        # Service-account keys live in job_inputs, where the generic gate already sees them.
        source_model = mock.Mock(job_inputs=job_inputs)

        assert self.source.has_preserved_row_backed_credentials(source_model, {"partner_id": "999"}) is False

    def test_source_config_fields(self) -> None:
        auth_field, partner_field, advertiser_field = self.source.get_source_config.fields

        assert isinstance(auth_field, SourceFieldSelectConfig)
        assert auth_field.name == "auth_type"
        assert auth_field.required is True
        # OAuth is the default: nobody should have to register their own Google Cloud client.
        assert auth_field.defaultValue == "oauth"
        assert {option.value for option in auth_field.options} == {"service_account", "oauth"}

        service_account_option = next(o for o in auth_field.options if o.value == "service_account")
        assert [f.name for f in service_account_option.fields or []] == ["service_account_key"]

        oauth_option = next(o for o in auth_field.options if o.value == "oauth")
        (oauth_connect,) = oauth_option.fields or []
        assert isinstance(oauth_connect, SourceFieldOauthConfig)
        assert oauth_connect.name == "display_video_360_integration_id"
        assert oauth_connect.kind == "display-video-360"
        # Entity reads need display-video; the performance tables are Bid Manager reports.
        assert oauth_connect.requiredScopes == (
            "https://www.googleapis.com/auth/display-video https://www.googleapis.com/auth/doubleclickbidmanager"
        )

        assert isinstance(partner_field, SourceFieldInputConfig)
        assert partner_field.name == "partner_id"
        assert partner_field.required is True

        assert isinstance(advertiser_field, SourceFieldInputConfig)
        assert advertiser_field.name == "advertiser_ids"
        assert advertiser_field.required is False

    def test_every_secret_field_is_a_password_or_textarea(self) -> None:
        auth_field = self.source.get_source_config.fields[0]
        assert isinstance(auth_field, SourceFieldSelectConfig)

        secret_fields = [
            field
            for option in auth_field.options
            for field in option.fields or []
            if isinstance(field, SourceFieldInputConfig) and field.secret
        ]

        assert {field.name for field in secret_fields} == {"service_account_key"}
        for field in secret_fields:
            assert field.type in (SourceFieldInputConfigType.PASSWORD, SourceFieldInputConfigType.TEXTAREA)

    @pytest.mark.parametrize(
        "expected_key",
        [
            "401 Client Error",
            "403 Client Error",
            "invalid_grant",
            "ACCESS_TOKEN_SCOPE_INSUFFICIENT",
            "Missing integration ID",
            "Integration not found",
            "not under Display & Video 360 partner",
        ],
    )
    def test_non_retryable_errors(self, expected_key: str) -> None:
        assert expected_key in self.source.get_non_retryable_errors()

    def test_get_schemas_returns_every_endpoint(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {schema.name for schema in schemas} == set(ENDPOINTS)

    @pytest.mark.parametrize("endpoint", sorted(INCREMENTAL_ENTITY_ENDPOINTS))
    def test_entity_endpoints_are_incremental_on_update_time(self, endpoint: str) -> None:
        schema = next(s for s in self.source.get_schemas(self.config, self.team_id) if s.name == endpoint)

        assert schema.supports_incremental is True
        assert schema.supports_append is True
        assert schema.incremental_fields == [
            {"label": "updateTime", "type": "datetime", "field": "updateTime", "field_type": "datetime"}
        ]

    @pytest.mark.parametrize("endpoint", sorted(FULL_REFRESH_ENDPOINTS))
    def test_full_refresh_endpoints_advertise_no_cursor(self, endpoint: str) -> None:
        schema = next(s for s in self.source.get_schemas(self.config, self.team_id) if s.name == endpoint)

        assert schema.supports_incremental is False
        assert schema.supports_append is False
        assert schema.incremental_fields == []

    @pytest.mark.parametrize("endpoint", sorted(REPORT_ENDPOINTS))
    def test_report_endpoints_are_incremental_on_date(self, endpoint: str) -> None:
        schema = next(s for s in self.source.get_schemas(self.config, self.team_id) if s.name == endpoint)

        assert schema.supports_incremental is True
        assert schema.incremental_fields == [{"label": "date", "type": "date", "field": "date", "field_type": "date"}]
        assert schema.description is not None

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["line_items", "nonexistent"])
        assert [schema.name for schema in schemas] == ["line_items"]

    def test_canonical_descriptions_cover_every_endpoint(self) -> None:
        descriptions = self.source.get_canonical_descriptions()
        assert set(descriptions) == set(ENDPOINTS)

    def test_canonical_descriptions_document_the_primary_keys(self) -> None:
        descriptions = self.source.get_canonical_descriptions()

        for name, endpoint in DISPLAY_VIDEO_360_ENDPOINTS.items():
            columns = descriptions[name]["columns"]
            missing = [key for key in endpoint.primary_key if key not in columns]
            assert missing == [], f"{name} is missing descriptions for {missing}"

    @pytest.mark.parametrize(
        ("probe_result", "expected"),
        [((True, None), (True, None)), ((False, "nope"), (False, "nope"))],
    )
    def test_validate_credentials_delegates_to_the_transport(
        self, probe_result: tuple[bool, str | None], expected: tuple[bool, str | None]
    ) -> None:
        with mock.patch(f"{SOURCE_MODULE}.validate_display_video_360_credentials", return_value=probe_result) as probe:
            assert self.source.validate_credentials(self.config, self.team_id) == expected

        # No integration: the service account path never touches the Integration table.
        probe.assert_called_once_with(self.config, "v4", None)

    def test_validate_credentials_honors_a_pinned_api_version(self) -> None:
        with mock.patch(f"{SOURCE_MODULE}.validate_display_video_360_credentials", return_value=(True, None)) as probe:
            self.source.validate_credentials(self.config, self.team_id, api_version="v3")

        probe.assert_called_once_with(self.config, "v3", None)

    def test_validate_credentials_passes_the_connected_integration(self) -> None:
        config = _oauth_config()
        integration = Integration(kind="display-video-360")

        with (
            mock.patch.object(DisplayVideo360Source, "get_oauth_integration", return_value=integration) as fetch,
            mock.patch(f"{SOURCE_MODULE}.validate_display_video_360_credentials", return_value=(True, None)) as probe,
        ):
            assert self.source.validate_credentials(config, self.team_id) == (True, None)

        fetch.assert_called_once_with(42, self.team_id)
        probe.assert_called_once_with(config, "v4", integration)

    @pytest.mark.parametrize(
        ("config_factory", "fetch_error"),
        [
            (lambda: _oauth_config(integration_id=None), None),
            (lambda: _oauth_config(), ValueError("Integration not found: 42")),
        ],
    )
    def test_validate_credentials_reports_a_missing_connection(
        self, config_factory: Any, fetch_error: Exception | None
    ) -> None:
        with (
            mock.patch.object(DisplayVideo360Source, "get_oauth_integration", side_effect=fetch_error),
            mock.patch(f"{SOURCE_MODULE}.validate_display_video_360_credentials") as probe,
        ):
            is_valid, error = self.source.validate_credentials(config_factory(), self.team_id)

        assert is_valid is False
        assert error is not None and "Connect a Google account" in error
        probe.assert_not_called()

    def test_resume_manager_is_namespaced_per_schema(self) -> None:
        # Entity page tokens and report windows are not interchangeable, so a retry that switches
        # schema must not load the other schema's cursor.
        manager = self.source.get_resumable_source_manager(_make_inputs(schema_name="campaigns"))

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is DisplayVideo360ResumeConfig
        assert manager._namespace == "campaigns"

    def test_source_for_pipeline_plumbs_arguments(self) -> None:
        inputs = _make_inputs(schema_name="campaigns")
        manager = mock.MagicMock(spec=ResumableSourceManager)

        with mock.patch(f"{SOURCE_MODULE}.display_video_360_source") as build_source:
            self.source.source_for_pipeline(self.config, manager, inputs)

        build_source.assert_called_once_with(
            config=self.config,
            endpoint="campaigns",
            api_version="v4",
            integration=None,
            logger=inputs.logger,
            resumable_source_manager=manager,
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
        )

    def test_source_for_pipeline_resolves_the_connected_integration(self) -> None:
        config = _oauth_config()
        inputs = _make_inputs(schema_name="campaigns")
        integration = Integration(kind="display-video-360")

        with (
            mock.patch.object(DisplayVideo360Source, "get_oauth_integration", return_value=integration) as fetch,
            mock.patch(f"{SOURCE_MODULE}.display_video_360_source") as build_source,
        ):
            self.source.source_for_pipeline(config, mock.MagicMock(spec=ResumableSourceManager), inputs)

        fetch.assert_called_once_with(42, inputs.team_id)
        assert build_source.call_args.kwargs["integration"] is integration

    def test_source_for_pipeline_drops_the_cursor_when_incremental_is_off(self) -> None:
        inputs = _make_inputs(should_use_incremental_field=False, db_incremental_field_last_value="2026-01-01")
        manager = mock.MagicMock(spec=ResumableSourceManager)

        with mock.patch(f"{SOURCE_MODULE}.display_video_360_source") as build_source:
            self.source.source_for_pipeline(self.config, manager, inputs)

        assert build_source.call_args.kwargs["db_incremental_field_last_value"] is None

    def test_source_for_pipeline_passes_the_cursor_when_incremental_is_on(self) -> None:
        inputs = _make_inputs(
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-01-01T00:00:00Z",
            incremental_field="updateTime",
            api_version="v4",
        )
        manager = mock.MagicMock(spec=ResumableSourceManager)

        with mock.patch(f"{SOURCE_MODULE}.display_video_360_source") as build_source:
            self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = build_source.call_args.kwargs
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01T00:00:00Z"
