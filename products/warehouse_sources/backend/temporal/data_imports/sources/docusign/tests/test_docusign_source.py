from typing import Any, Optional

import pytest
from unittest import mock

import structlog

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType, SourceFieldSelectConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.docusign.docusign import DocusignResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.docusign.settings import (
    DOCUSIGN_ENDPOINTS,
    ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.docusign.source import DocusignSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.docusign import (
    DocusignAuthTypeConfig,
    DocusignSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

_VALIDATE = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.docusign.source.validate_docusign_credentials"
)


def jwt_config(**overrides: Any) -> DocusignSourceConfig:
    auth_kwargs: dict[str, Any] = {
        "selection": "jwt",
        "integration_key": "int-key",
        "user_id": "user-guid",
        "private_key": "-----BEGIN RSA PRIVATE KEY-----",
    }
    auth_kwargs.update(overrides.pop("auth", {}))
    return DocusignSourceConfig(
        auth_type=DocusignAuthTypeConfig(**auth_kwargs),
        environment=overrides.pop("environment", "production"),
        account_id=overrides.pop("account_id", None),
        start_date=overrides.pop("start_date", None),
    )


def source_inputs(schema_name: str, **overrides: Any) -> SourceInputs:
    defaults: dict[str, Any] = {
        "schema_name": schema_name,
        "schema_id": "schema-id",
        "source_id": "source-id",
        "team_id": 1,
        "should_use_incremental_field": False,
        "db_incremental_field_last_value": None,
        "db_incremental_field_earliest_value": None,
        "incremental_field": None,
        "incremental_field_type": None,
        "job_id": "job-id",
        "logger": structlog.get_logger("docusign-test"),
        "reset_pipeline": False,
    }
    defaults.update(overrides)
    return SourceInputs(**defaults)


class TestDocusignSource:
    def setup_method(self) -> None:
        self.source = DocusignSource()
        self.team_id = 123

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.DOCUSIGN

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config

        assert config.name.value == "Docusign"
        assert config.label == "DocuSign"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is None
        assert config.iconPath == "/static/services/docusign.png"
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/docusign"

        select_names = [f.name for f in config.fields if isinstance(f, SourceFieldSelectConfig)]
        assert select_names == ["environment", "auth_type"]
        input_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert input_names == ["account_id", "start_date"]

    def test_api_version_metadata_pins_what_the_transport_calls(self) -> None:
        assert self.source.supported_versions == ("v2.1",)
        assert self.source.default_version in self.source.supported_versions
        assert self.source.api_docs_url is not None
        assert self.source.api_docs_url.startswith("https://")

    @pytest.mark.parametrize("secret_field", ["private_key", "secret_key", "refresh_token"])
    def test_credential_fields_are_marked_secret(self, secret_field: str) -> None:
        auth_field = next(
            f
            for f in self.source.get_source_config.fields
            if isinstance(f, SourceFieldSelectConfig) and f.name == "auth_type"
        )
        candidates = [
            sub
            for option in auth_field.options
            for sub in (option.fields or [])
            if isinstance(sub, SourceFieldInputConfig) and sub.name == secret_field
        ]

        assert candidates, f"{secret_field} is not offered by any auth option"
        for field in candidates:
            assert field.secret is True
            assert field.type in (SourceFieldInputConfigType.PASSWORD, SourceFieldInputConfigType.TEXTAREA)

    def test_get_schemas_lists_every_endpoint(self) -> None:
        schemas = self.source.get_schemas(jwt_config(), self.team_id)

        assert [s.name for s in schemas] == list(ENDPOINTS)

    @pytest.mark.parametrize("endpoint_name", sorted(DOCUSIGN_ENDPOINTS))
    def test_incremental_support_matches_the_endpoint_catalog(self, endpoint_name: str) -> None:
        endpoint = DOCUSIGN_ENDPOINTS[endpoint_name]
        schema = self.source.get_schemas(jwt_config(), self.team_id, names=[endpoint_name])[0]

        # Only endpoints with a real server-side date filter advertise incremental sync.
        assert schema.supports_incremental is bool(endpoint.date_filter_param)
        assert [f["field"] for f in schema.incremental_fields] == [f["field"] for f in endpoint.incremental_fields]

    def test_get_schemas_filters_by_name(self) -> None:
        schemas = self.source.get_schemas(jwt_config(), self.team_id, names=["envelopes", "users"])

        assert {s.name for s in schemas} == {"envelopes", "users"}

    def test_documented_tables_render_for_public_docs(self) -> None:
        tables = self.source.get_documented_tables()

        assert {t["name"] for t in tables} == set(ENDPOINTS)
        assert all(t["description"] for t in tables)

    def test_canonical_descriptions_cover_every_endpoint(self) -> None:
        descriptions = self.source.get_canonical_descriptions()

        assert set(descriptions) == set(ENDPOINTS)
        for name, entry in descriptions.items():
            primary_keys = DOCUSIGN_ENDPOINTS[name].primary_key
            assert set(primary_keys) <= set(entry.get("columns", {})), name

    @pytest.mark.parametrize(
        "auth_overrides,expected_fragment",
        [
            ({"private_key": None}, "RSA private key"),
            ({"user_id": None}, "impersonated user ID"),
            (
                {"selection": "refresh_token", "user_id": None, "private_key": None, "secret_key": "s"},
                "refresh token",
            ),
            (
                {"selection": "refresh_token", "user_id": None, "private_key": None, "refresh_token": "r"},
                "secret key",
            ),
        ],
    )
    def test_validate_credentials_rejects_a_half_filled_auth_option(
        self, auth_overrides: dict[str, Any], expected_fragment: str
    ) -> None:
        config = jwt_config(auth=auth_overrides)

        with mock.patch(_VALIDATE) as probe:
            valid, message = self.source.validate_credentials(config, self.team_id)

        assert valid is False
        assert message is not None and expected_fragment in message
        # A half-filled form must not cost a DocuSign round trip.
        probe.assert_not_called()

    def test_validate_credentials_delegates_to_the_transport(self) -> None:
        with mock.patch(_VALIDATE, return_value=(True, None)) as probe:
            assert self.source.validate_credentials(jwt_config(account_id="222"), self.team_id) == (True, None)

        credentials = probe.call_args.args[0]
        assert credentials.environment == "production"
        assert credentials.selection == "jwt"
        assert credentials.integration_key == "int-key"
        assert credentials.account_id == "222"

    def test_validate_credentials_passes_the_transport_failure_through(self) -> None:
        with mock.patch(_VALIDATE, return_value=(False, "nope")):
            assert self.source.validate_credentials(jwt_config(), self.team_id) == (False, "nope")

    def test_resumable_manager_is_bound_to_the_docusign_cursor(self) -> None:
        manager = self.source.get_resumable_source_manager(source_inputs("envelopes"))

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is DocusignResumeConfig

    @pytest.mark.parametrize("endpoint_name", sorted(DOCUSIGN_ENDPOINTS))
    def test_source_for_pipeline_wires_the_endpoint_through(self, endpoint_name: str) -> None:
        manager: ResumableSourceManager[DocusignResumeConfig] = ResumableSourceManager(
            source_inputs(endpoint_name), DocusignResumeConfig
        )

        response = self.source.source_for_pipeline(jwt_config(), manager, source_inputs(endpoint_name))

        assert response.name == endpoint_name
        assert response.primary_keys == DOCUSIGN_ENDPOINTS[endpoint_name].primary_key

    def test_source_for_pipeline_only_forwards_the_watermark_when_incremental(self) -> None:
        target = "products.warehouse_sources.backend.temporal.data_imports.sources.docusign.source.docusign_source"
        manager: ResumableSourceManager[DocusignResumeConfig] = ResumableSourceManager(
            source_inputs("envelopes"), DocusignResumeConfig
        )
        inputs = source_inputs(
            "envelopes", should_use_incremental_field=False, db_incremental_field_last_value="2024-01-01T00:00:00Z"
        )

        with mock.patch(target) as build:
            self.source.source_for_pipeline(jwt_config(start_date="2020-01-01T00:00:00Z"), manager, inputs)

        assert build.call_args.kwargs["db_incremental_field_last_value"] is None
        assert build.call_args.kwargs["start_date"] == "2020-01-01T00:00:00Z"

    @pytest.mark.parametrize(
        "observed_error",
        [
            "DocuSign token request failed: status=400 error=consent_required description=None",
            "DocuSign token request failed: status=400 error=invalid_grant description=bad user",
            "401 Client Error: Unauthorized for url: https://na3.docusign.net/restapi/v2.1/accounts/222/envelopes",
            "403 Client Error: Forbidden for url: https://na3.docusign.net/restapi/v2.1/accounts/222/users",
        ],
    )
    def test_non_retryable_errors_match_permanent_failures(self, observed_error: str) -> None:
        assert any(key in observed_error for key in self.source.get_non_retryable_errors())

    @pytest.mark.parametrize(
        "transient_error",
        [
            "429 Client Error: Too Many Requests for url: https://na3.docusign.net/restapi/v2.1/accounts/222/envelopes",
            "500 Server Error: Internal Server Error for url: https://na3.docusign.net/restapi",
        ],
    )
    def test_transient_errors_stay_retryable(self, transient_error: str) -> None:
        assert not any(key in transient_error for key in self.source.get_non_retryable_errors())

    def test_optional_config_fields_default_to_none(self) -> None:
        config: Optional[DocusignSourceConfig] = jwt_config()

        assert config is not None
        assert config.account_id is None
        assert config.start_date is None
        assert config.environment == "production"
