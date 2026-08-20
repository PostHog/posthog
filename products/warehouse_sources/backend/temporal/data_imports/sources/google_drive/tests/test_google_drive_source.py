import json
from typing import Any, Optional, cast

import pytest
from unittest import mock

import structlog
from rest_framework.exceptions import ValidationError

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldOauthConfig, SourceFieldSelectConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.googledrive import (
    GoogleDriveAuthMethodConfig,
    GoogleDriveSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.google_drive.google_drive import (
    GoogleDriveAuth,
    GoogleDriveResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.google_drive.source import GoogleDriveSource
from products.warehouse_sources.backend.types import ExternalDataSourceType, IncrementalFieldType

SERVICE_ACCOUNT_KEY = json.dumps({"client_email": "sa@project.iam.gserviceaccount.com", "private_key": "-----KEY-----"})


def _config(
    selection: str = "service_account",
    service_account_key: Optional[str] = SERVICE_ACCOUNT_KEY,
    impersonated_user_email: Optional[str] = None,
    integration_id: Optional[int] = None,
    drive_id: Optional[str] = None,
) -> GoogleDriveSourceConfig:
    return GoogleDriveSourceConfig(
        auth_method=GoogleDriveAuthMethodConfig(
            selection=cast(Any, selection),
            service_account_key=service_account_key,
            impersonated_user_email=impersonated_user_email,
            google_drive_integration_id=integration_id,
        ),
        drive_id=drive_id,
    )


def _oauth_config(integration_id: Optional[int] = 42) -> GoogleDriveSourceConfig:
    return _config(selection="oauth", service_account_key=None, integration_id=integration_id)


def _source_inputs(
    schema_name: str = "files",
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: Optional[str] = None,
    api_version: Optional[str] = None,
) -> SourceInputs:
    return SourceInputs(
        schema_name=schema_name,
        schema_id="schema-1",
        source_id="source-1",
        team_id=1,
        should_use_incremental_field=should_use_incremental_field,
        db_incremental_field_last_value=db_incremental_field_last_value,
        db_incremental_field_earliest_value=None,
        incremental_field=incremental_field,
        incremental_field_type=IncrementalFieldType.DateTime,
        job_id="job-1",
        logger=structlog.get_logger(__name__),
        reset_pipeline=False,
        api_version=api_version,
    )


def test_source_type() -> None:
    assert GoogleDriveSource().source_type == ExternalDataSourceType.GOOGLEDRIVE


def test_source_ships_visible_and_labelled_alpha() -> None:
    config = GoogleDriveSource().get_source_config
    assert config.unreleasedSource is None
    assert config.releaseStatus == ReleaseStatus.ALPHA


def test_api_version_is_pinned_to_the_path_segment_the_code_calls() -> None:
    source = GoogleDriveSource()
    assert source.supported_versions == ("v3",)
    assert source.default_version == "v3"
    assert source.resolve_api_version(None) == "v3"


@pytest.mark.parametrize(
    "endpoint,supports_incremental,expected_primary_keys",
    [
        # Drive's search syntax filters modifiedTime/createdTime server-side, so files is genuinely
        # incremental; neither shared drives nor permissions expose a filterable timestamp.
        ("files", True, ["id"]),
        ("drives", False, ["id"]),
        ("drive_permissions", False, ["drive_id", "id"]),
    ],
)
def test_get_schemas_advertises_the_right_sync_methods(
    endpoint: str, supports_incremental: bool, expected_primary_keys: list[str]
) -> None:
    schemas = {schema.name: schema for schema in GoogleDriveSource().get_schemas(_config(), team_id=1)}

    assert schemas[endpoint].supports_incremental is supports_incremental
    assert schemas[endpoint].supports_append is supports_incremental
    assert bool(schemas[endpoint].incremental_fields) is supports_incremental
    assert schemas[endpoint].detected_primary_keys == expected_primary_keys


def test_files_offers_both_filterable_timestamps_as_cursors() -> None:
    schemas = {schema.name: schema for schema in GoogleDriveSource().get_schemas(_config(), team_id=1)}
    fields = [field["field"] for field in schemas["files"].incremental_fields]

    assert fields == ["modifiedTime", "createdTime"]


def test_get_schemas_filters_by_names() -> None:
    schemas = GoogleDriveSource().get_schemas(_config(), team_id=1, names=["drives"])

    assert [schema.name for schema in schemas] == ["drives"]


def test_table_catalog_is_published_without_credentials() -> None:
    # `get_schemas` does no I/O, so the public docs can render the table list from a blank config
    source = GoogleDriveSource()
    assert source.lists_tables_without_credentials is True

    tables = source.get_documented_tables()
    assert sorted(table["name"] for table in tables) == ["drive_permissions", "drives", "files"]
    assert all(table["description"] for table in tables)


def test_canonical_descriptions_cover_every_endpoint() -> None:
    source = GoogleDriveSource()
    descriptions = source.get_canonical_descriptions()
    endpoints = {schema.name for schema in source.get_schemas(_config(), team_id=1)}

    assert endpoints <= set(descriptions)
    # The injected parent columns are PostHog's own, so nothing else documents them
    assert "drive_id" in (descriptions["drive_permissions"].get("columns") or {})


@pytest.mark.parametrize(
    "config,expected_auth",
    [
        (
            _config(),
            GoogleDriveAuth(service_account_key=SERVICE_ACCOUNT_KEY),
        ),
        (
            _config(impersonated_user_email="user@example.com"),
            GoogleDriveAuth(service_account_key=SERVICE_ACCOUNT_KEY, impersonated_user_email="user@example.com"),
        ),
        # A blank impersonation field must not be sent as an empty subject
        (
            _config(impersonated_user_email=""),
            GoogleDriveAuth(service_account_key=SERVICE_ACCOUNT_KEY),
        ),
        (
            _oauth_config(),
            GoogleDriveAuth(integration_id=42, team_id=7),
        ),
    ],
)
def test_get_auth_builds_the_right_credential(config: GoogleDriveSourceConfig, expected_auth: GoogleDriveAuth) -> None:
    with mock.patch.object(GoogleDriveSource, "get_oauth_integration") as get_integration:
        assert GoogleDriveSource()._get_auth(config, team_id=7) == expected_auth

    if config.auth_method.selection == "oauth":
        get_integration.assert_called_once_with(42, 7)


@pytest.mark.parametrize(
    "config,expected_fragment",
    [
        (_config(service_account_key=None), "No Google Drive service account key"),
        (_oauth_config(integration_id=None), "No Google account is connected"),
    ],
)
def test_validate_credentials_maps_missing_config_to_a_friendly_error(
    config: GoogleDriveSourceConfig, expected_fragment: str
) -> None:
    valid, message = GoogleDriveSource().validate_credentials(config, team_id=1)

    assert valid is False
    assert expected_fragment in cast(str, message)


def test_validate_credentials_reports_a_deleted_integration_without_leaking_its_id() -> None:
    with mock.patch.object(
        GoogleDriveSource, "get_oauth_integration", side_effect=ValueError("Integration not found: 42")
    ):
        valid, message = GoogleDriveSource().validate_credentials(_oauth_config(), team_id=1)

    assert valid is False
    assert message == "The linked Google account no longer exists in PostHog. Please reconnect the source."


def test_validate_credentials_passes_the_connected_account_to_the_transport() -> None:
    with mock.patch.object(GoogleDriveSource, "get_oauth_integration"):
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.google_drive.source.validate_google_drive_credentials",
            return_value=(True, None),
        ) as validate:
            assert GoogleDriveSource().validate_credentials(_oauth_config(), team_id=7) == (True, None)

    validate.assert_called_once_with(GoogleDriveAuth(integration_id=42, team_id=7), "v3")


def test_validate_credentials_delegates_to_the_transport_with_the_resolved_version() -> None:
    with mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.google_drive.source.validate_google_drive_credentials",
        return_value=(True, None),
    ) as validate:
        assert GoogleDriveSource().validate_credentials(_config(), team_id=1) == (True, None)

    validate.assert_called_once_with(GoogleDriveAuth(service_account_key=SERVICE_ACCOUNT_KEY), "v3")


def test_get_resumable_source_manager_binds_the_resume_config() -> None:
    manager = GoogleDriveSource().get_resumable_source_manager(_source_inputs())

    assert isinstance(manager, ResumableSourceManager)
    assert manager._data_class is GoogleDriveResumeConfig


@pytest.mark.parametrize(
    "should_use_incremental,last_value,expected_last_value",
    [
        (True, "2024-06-01", "2024-06-01"),
        # A stale watermark must not leak into a full-refresh run
        (False, "2024-06-01", None),
    ],
)
def test_source_for_pipeline_plumbs_arguments(
    should_use_incremental: bool, last_value: Any, expected_last_value: Any
) -> None:
    inputs = _source_inputs(
        schema_name="files",
        should_use_incremental_field=should_use_incremental,
        db_incremental_field_last_value=last_value,
        incremental_field="modifiedTime",
    )
    manager = GoogleDriveSource().get_resumable_source_manager(inputs)

    with mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.google_drive.source.google_drive_source"
    ) as transport:
        GoogleDriveSource().source_for_pipeline(_config(drive_id="drive-9"), manager, inputs)

    transport.assert_called_once_with(
        auth=GoogleDriveAuth(service_account_key=SERVICE_ACCOUNT_KEY),
        endpoint="files",
        api_version="v3",
        source_logger=inputs.logger,
        resumable_source_manager=manager,
        drive_id="drive-9",
        should_use_incremental_field=should_use_incremental,
        db_incremental_field_last_value=expected_last_value,
        incremental_field="modifiedTime",
    )


def test_source_for_pipeline_honors_a_pinned_api_version() -> None:
    inputs = _source_inputs(api_version="v3")
    manager = GoogleDriveSource().get_resumable_source_manager(inputs)

    with mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.google_drive.source.google_drive_source"
    ) as transport:
        GoogleDriveSource().source_for_pipeline(_config(), manager, inputs)

    assert transport.call_args.kwargs["api_version"] == "v3"


def test_a_blank_drive_id_is_passed_as_no_scope() -> None:
    inputs = _source_inputs()
    manager = GoogleDriveSource().get_resumable_source_manager(inputs)

    with mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.google_drive.source.google_drive_source"
    ) as transport:
        GoogleDriveSource().source_for_pipeline(_config(drive_id=""), manager, inputs)

    assert transport.call_args.kwargs["drive_id"] is None


def test_source_for_pipeline_hands_the_transport_the_connected_account() -> None:
    # The token itself is read per request off the integration row, so only the reference travels
    inputs = _source_inputs()
    manager = GoogleDriveSource().get_resumable_source_manager(inputs)

    with mock.patch.object(GoogleDriveSource, "get_oauth_integration"):
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.google_drive.source.google_drive_source"
        ) as transport:
            GoogleDriveSource().source_for_pipeline(_oauth_config(), manager, inputs)

    assert transport.call_args.kwargs["auth"] == GoogleDriveAuth(integration_id=42, team_id=inputs.team_id)


def test_connecting_a_google_account_is_the_default_auth_method() -> None:
    fields = GoogleDriveSource().get_source_config.fields
    auth_field = next(field for field in fields if isinstance(field, SourceFieldSelectConfig))

    assert auth_field.defaultValue == "oauth"

    options = {option.value: option.fields or [] for option in auth_field.options}
    assert set(options) == {"oauth", "service_account"}

    oauth_field = options["oauth"][0]
    assert isinstance(oauth_field, SourceFieldOauthConfig)
    assert oauth_field.name == "google_drive_integration_id"
    assert oauth_field.kind == "google-drive"
    # drives.list is not reachable with the narrower drive.metadata.readonly scope
    assert oauth_field.requiredScopes == "https://www.googleapis.com/auth/drive.readonly"

    # The service account key stays as a second method, and users never paste OAuth client secrets
    service_account_fields = [field.name for field in options["service_account"]]
    assert service_account_fields == ["service_account_key", "impersonated_user_email"]
    for field in options["service_account"]:
        if isinstance(field, SourceFieldInputConfig) and field.name == "service_account_key":
            assert field.secret is True


def test_non_retryable_errors_cover_auth_and_permission_failures() -> None:
    errors = GoogleDriveSource().get_non_retryable_errors()

    assert "401 Client Error" in errors
    assert "403 Client Error" in errors
    assert "Google Drive authentication failed" in errors
    # A revoked or deleted connection needs a reconnect, not a retry
    assert "Integration not found" in errors


def test_rate_limits_are_reported_as_self_recovering() -> None:
    # Drive's 403 quota errors are retried inside the source, so they must not land in error tracking
    assert "Google Drive rate limit" in GoogleDriveSource().get_retryable_errors()


def _stored_service_account_inputs(impersonated_user_email: Optional[str] = None) -> dict[str, Any]:
    return {
        "auth_method": {
            "selection": "service_account",
            "service_account_key": SERVICE_ACCOUNT_KEY,
            "impersonated_user_email": impersonated_user_email,
        }
    }


def test_repointing_the_delegated_user_needs_the_key_re_entered() -> None:
    # Domain-wide delegation makes the impersonated user a credential target: an editor who never
    # held the key must not be able to aim the stored one at somebody else's Drive
    existing = _stored_service_account_inputs()
    incoming = {
        "auth_method": {
            "selection": "service_account",
            "impersonated_user_email": "ceo@yourcompany.com",
        }
    }

    with pytest.raises(ValidationError):
        GoogleDriveSource().job_inputs_add_connection_host(incoming, existing)


def test_repointing_the_delegated_user_is_allowed_with_a_fresh_key() -> None:
    existing = _stored_service_account_inputs("analytics@yourcompany.com")
    incoming = {
        "auth_method": {
            "selection": "service_account",
            "service_account_key": json.dumps({"client_email": "other@project.iam.gserviceaccount.com"}),
            "impersonated_user_email": "ceo@yourcompany.com",
        }
    }

    assert GoogleDriveSource().job_inputs_add_connection_host(incoming, existing) is False


@pytest.mark.parametrize(
    "incoming",
    [
        pytest.param({"drive_id": "0ABCdef"}, id="unrelated_field"),
        pytest.param(
            {"auth_method": {"selection": "service_account", "impersonated_user_email": "analyst@yourcompany.com"}},
            id="unchanged_identity",
        ),
        pytest.param(
            {"auth_method": {"selection": "service_account", "impersonated_user_email": ""}},
            id="cleared_identity",
        ),
        pytest.param(
            {"auth_method": {"selection": "oauth", "google_drive_integration_id": 42}},
            id="switched_to_a_google_account",
        ),
    ],
)
def test_updates_that_cannot_retarget_the_stored_key_are_left_alone(incoming: dict[str, Any]) -> None:
    existing = _stored_service_account_inputs("analyst@yourcompany.com")

    assert GoogleDriveSource().job_inputs_add_connection_host(incoming, existing) is False


def test_a_source_without_a_stored_key_is_not_gated() -> None:
    # Nothing to preserve, so the editor has to supply a key anyway
    existing = {"auth_method": {"selection": "service_account", "service_account_key": ""}}
    incoming = {"auth_method": {"selection": "service_account", "impersonated_user_email": "ceo@yourcompany.com"}}

    assert GoogleDriveSource().job_inputs_add_connection_host(incoming, existing) is False
