from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldSelectConfig,
    SourceFieldSelectConfigOption,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.docusign.docusign import (
    DocusignCredentials,
    DocusignResumeConfig,
    docusign_source,
    validate_credentials as validate_docusign_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.docusign.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.docusign import (
    DocusignSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class DocusignSource(ResumableSource[DocusignSourceConfig, DocusignResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    supported_versions = ("v2.1",)
    default_version = "v2.1"
    api_docs_url = "https://developers.docusign.com/docs/esign-rest-api/reference/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.DOCUSIGN

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "error=consent_required": "DocuSign needs one-time consent for this integration key. Grant consent for the impersonated user, then reconnect.",
            "error=invalid_grant": "DocuSign rejected these credentials. Check the integration key, the impersonated user ID, and that the key is authorized for the selected environment.",
            "error=unauthorized_client": "This DocuSign integration key is not authorized for the selected environment. Production keys have to pass DocuSign's go-live review first.",
            "DocuSign token request failed": "DocuSign could not issue an access token. Please check your integration key and credentials.",
            "401 Client Error: Unauthorized": "DocuSign authentication failed. Your credentials may have been revoked — please reconnect.",
            "403 Client Error: Forbidden": "DocuSign denied access. Check that the impersonated user can read this account's data.",
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.DOCUSIGN,
            category=DataWarehouseSourceCategory.SALES,
            label="DocuSign",
            caption="""Connect your DocuSign account to pull envelopes, recipients, documents, templates, users, and folders into the PostHog Data warehouse.

Create an integration key in [DocuSign Apps and Keys](https://apps.docusign.com/admin/apps-and-keys). JWT grant is the option to pick: add an RSA keypair to the key, grant consent once for the user you want to impersonate, and paste that user's API user ID. Production keys have to pass DocuSign's go-live review before they work outside the demo environment.""",
            iconPath="/static/services/docusign.png",
            docsUrl="https://posthog.com/docs/cdp/sources/docusign",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["esignature", "e-signature", "contracts", "agreements"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldSelectConfig(
                        name="environment",
                        label="Environment",
                        required=True,
                        defaultValue="production",
                        options=[
                            SourceFieldSelectConfigOption(label="Production", value="production"),
                            SourceFieldSelectConfigOption(label="Demo (sandbox)", value="demo"),
                        ],
                    ),
                    SourceFieldSelectConfig(
                        name="auth_type",
                        label="Authentication type",
                        required=True,
                        defaultValue="jwt",
                        options=[
                            SourceFieldSelectConfigOption(
                                label="JWT grant",
                                value="jwt",
                                fields=cast(
                                    list[FieldType],
                                    [
                                        SourceFieldInputConfig(
                                            name="integration_key",
                                            label="Integration key",
                                            type=SourceFieldInputConfigType.TEXT,
                                            required=True,
                                            placeholder="00000000-0000-0000-0000-000000000000",
                                            secret=False,
                                        ),
                                        SourceFieldInputConfig(
                                            name="user_id",
                                            label="Impersonated user ID",
                                            type=SourceFieldInputConfigType.TEXT,
                                            required=False,
                                            placeholder="00000000-0000-0000-0000-000000000000",
                                            secret=False,
                                        ),
                                        SourceFieldInputConfig(
                                            name="private_key",
                                            label="RSA private key",
                                            type=SourceFieldInputConfigType.TEXTAREA,
                                            required=False,
                                            placeholder="-----BEGIN RSA PRIVATE KEY-----",
                                            secret=True,
                                        ),
                                    ],
                                ),
                            ),
                            SourceFieldSelectConfigOption(
                                label="Refresh token",
                                value="refresh_token",
                                fields=cast(
                                    list[FieldType],
                                    [
                                        SourceFieldInputConfig(
                                            name="integration_key",
                                            label="Integration key",
                                            type=SourceFieldInputConfigType.TEXT,
                                            required=True,
                                            placeholder="00000000-0000-0000-0000-000000000000",
                                            secret=False,
                                        ),
                                        SourceFieldInputConfig(
                                            name="secret_key",
                                            label="Secret key",
                                            type=SourceFieldInputConfigType.PASSWORD,
                                            required=False,
                                            placeholder="",
                                            secret=True,
                                        ),
                                        SourceFieldInputConfig(
                                            name="refresh_token",
                                            label="Refresh token",
                                            type=SourceFieldInputConfigType.PASSWORD,
                                            required=False,
                                            placeholder="",
                                            secret=True,
                                        ),
                                    ],
                                ),
                            ),
                        ],
                    ),
                    SourceFieldInputConfig(
                        name="account_id",
                        label="Account ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="Leave blank to use your default account",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="start_date",
                        label="Start date",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="2023-01-01T00:00:00Z (defaults to the last 2 years)",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.docusign.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: DocusignSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def _credentials(self, config: DocusignSourceConfig) -> DocusignCredentials:
        return DocusignCredentials(
            environment=config.environment,
            selection=config.auth_type.selection,
            integration_key=config.auth_type.integration_key,
            user_id=config.auth_type.user_id,
            private_key=config.auth_type.private_key,
            secret_key=config.auth_type.secret_key,
            refresh_token=config.auth_type.refresh_token,
            account_id=config.account_id,
        )

    def validate_credentials(
        self,
        config: DocusignSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        # The per-option fields are optional on the form (only one auth branch is ever filled
        # in), so the combination is checked here rather than by the config schema.
        auth = config.auth_type
        if auth.selection == "jwt" and not (auth.user_id and auth.private_key):
            return False, "JWT grant needs both an impersonated user ID and an RSA private key."
        if auth.selection == "refresh_token" and not (auth.secret_key and auth.refresh_token):
            return False, "Refresh token auth needs both a secret key and a refresh token."

        return validate_docusign_credentials(self._credentials(config))

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[DocusignResumeConfig]:
        return ResumableSourceManager[DocusignResumeConfig](inputs, DocusignResumeConfig)

    def source_for_pipeline(
        self,
        config: DocusignSourceConfig,
        resumable_source_manager: ResumableSourceManager[DocusignResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return docusign_source(
            credentials=self._credentials(config),
            endpoint_name=inputs.schema_name,
            start_date=config.start_date,
            resumable_source_manager=resumable_source_manager,
            logger=inputs.logger,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
