from typing import Optional, cast

from products.warehouse_sources.sources.bexio._config import BexioSourceConfig
from products.warehouse_sources.sources.bexio.bexio import BexioResumeConfig, bexio_source, probe_token
from products.warehouse_sources.sources.bexio.settings import ENDPOINTS, INCREMENTAL_FIELDS
from products.warehouse_sources.sources.sdk import (
    CanonicalDescriptions,
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    ReleaseStatus,
    ResumableSource,
    ResumableSourceManager,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceInputs,
    SourceRegistry,
    SourceResponse,
    SourceSchema,
    build_endpoint_schemas,
    detect,
)


@SourceRegistry.register
class BexioSource(ResumableSource[BexioSourceConfig, BexioResumeConfig]):
    codebase_detection = detect(env=("^BEXIO_",))

    lists_tables_without_credentials = True

    # bexio versions each resource on its own (`/2.0/contact`, `/3.0/users`, `/4.0/purchase/bills`) and
    # has no account-wide version to pin, so the source keeps the unversioned default.
    api_docs_url = "https://docs.bexio.com/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.BEXIO

    @property
    def credential_auth_type(self) -> str:
        # `facade/credential_auth_types.py` froze "credentials" for the scaffold, which had no fields.
        # Integration rows store this value, so it must not change to the "token" that the one secret field derives.
        return "credentials"

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url": "Bexio rejected your personal access token. Tokens expire after 60 days. Create a new token in the bexio developer portal, then update the source.",
            "403 Client Error: Forbidden for url": "Your Bexio user can't read one of the tables you sync. Ask a Bexio admin to give your user access to that data, or turn off the table.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.sources.bexio.canonical_descriptions import CANONICAL_DESCRIPTIONS

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: BexioSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: BexioSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        status = probe_token(config.api_token)
        if status == 200:
            return True, None
        if status == 401:
            return False, "Bexio rejected this token. Check that you copied the whole token and that it hasn't expired."
        # A personal access token has every default scope, and the probe reads only the token's own user.
        # So a 403 means that bexio refuses the user, not that one table is out of scope.
        if status == 403:
            return (
                False,
                "Bexio refused access for this token. Check that its user can still sign in to your Bexio company.",
            )
        return False, "Couldn't reach Bexio to check the token. Try again in a few minutes."

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[BexioResumeConfig]:
        return ResumableSourceManager[BexioResumeConfig](inputs, BexioResumeConfig)

    def source_for_pipeline(
        self,
        config: BexioSourceConfig,
        resumable_source_manager: ResumableSourceManager[BexioResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return bexio_source(
            api_token=config.api_token,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.BEXIO,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Bexio",
            caption=(
                "Import contacts, sales documents, bills, projects and accounting data from Bexio. "
                "Create a personal access token in the [bexio developer portal](https://developer.bexio.com/pat) "
                "and paste it below. Tokens expire after 60 days, so create a new token and update the source before then."
            ),
            docsUrl="https://posthog.com/docs/cdp/sources/bexio",
            iconPath="/static/services/bexio.png",
            releaseStatus=ReleaseStatus.BETA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_token",
                        label="Personal access token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )
