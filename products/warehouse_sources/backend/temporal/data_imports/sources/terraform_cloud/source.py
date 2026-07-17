import re
from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import (
    SourceInputs,
    SourceResponse,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import (
    TerraformCloudSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.terraform_cloud.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.terraform_cloud.terraform_cloud import (
    TerraformCloudResumeConfig,
    terraform_cloud_source,
    validate_credentials as validate_terraform_cloud_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

# HCP Terraform organization names: letters, digits, hyphens, underscores.
_ORGANIZATION_NAME_REGEX = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9-_]*$")


@SourceRegistry.register
class TerraformCloudSource(ResumableSource[TerraformCloudSourceConfig, TerraformCloudResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.TERRAFORMCLOUD

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.TERRAFORM_CLOUD,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="HashiCorp (HCP Terraform / Terraform Cloud)",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["tfc", "hcp", "infrastructure as code", "iac"],
            caption="""Sync organizations, projects, teams, workspaces, runs, and state versions from HCP Terraform (formerly Terraform Cloud) into the PostHog Data warehouse to analyze infrastructure change frequency, plan/apply durations, and failure rates.

Create an API token in your HCP Terraform organization settings under **API tokens** — an organization token is recommended so every workspace is visible. Team and user tokens also work but only see the workspaces they have access to.

Only the SaaS API at `app.terraform.io` is supported; self-hosted Terraform Enterprise is not currently supported.""",
            iconPath="/static/services/terraform_cloud.png",
            docsUrl="https://posthog.com/docs/cdp/sources/terraform-cloud",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_token",
                        label="API token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="organization",
                        label="Organization name",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="my-organization",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.terraform_cloud.canonical_descriptions import (  # noqa: PLC0415 — lazy import of sibling metadata, per the source architecture contract
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://app.terraform.io": "Your HCP Terraform API token is invalid or has been revoked. Create a new token in your organization settings, then reconnect.",
            "403 Client Error: Forbidden for url: https://app.terraform.io": "Your HCP Terraform API token does not have access to this data. Check the token's permissions, then reconnect.",
        }

    def get_schemas(
        self,
        config: TerraformCloudSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=len(INCREMENTAL_FIELDS.get(endpoint, [])) > 0,
                supports_append=len(INCREMENTAL_FIELDS.get(endpoint, [])) > 0,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: TerraformCloudSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        organization = config.organization.strip()
        if not _ORGANIZATION_NAME_REGEX.match(organization):
            return False, "HCP Terraform organization name is invalid"
        return validate_terraform_cloud_credentials(config.api_token, organization)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[TerraformCloudResumeConfig]:
        return ResumableSourceManager[TerraformCloudResumeConfig](inputs, TerraformCloudResumeConfig)

    def source_for_pipeline(
        self,
        config: TerraformCloudSourceConfig,
        resumable_source_manager: ResumableSourceManager[TerraformCloudResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return terraform_cloud_source(
            api_token=config.api_token,
            organization=config.organization.strip(),
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
