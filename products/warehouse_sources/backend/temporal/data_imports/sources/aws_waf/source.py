from typing import cast

from products.warehouse_sources.backend.facade.codebase_detection import detect
from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldSelectConfig,
    SourceFieldSelectConfigOption,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_waf.aws_waf import (
    AwsWafResumeConfig,
    aws_waf_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_waf.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_waf.settings import (
    ENDPOINT_DESCRIPTIONS,
    ENDPOINTS,
    ERROR_MESSAGES,
    INCREMENTAL_FIELDS,
    INCREMENTAL_LOOKBACK_SECONDS,
    SHOULD_SYNC_DEFAULT,
    WAF_API_VERSION,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.awswaf import AwsWafSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AwsWafSource(ResumableSource[AwsWafSourceConfig, AwsWafResumeConfig]):
    codebase_detection = detect(
        env=("^(AWS_WAF|AWSWAF)_",),
        npm=("@aws-sdk/client-wafv2", "@aws-sdk/client-waf"),
        cargo=("aws-sdk-wafv2", "aws-sdk-waf"),
        go=("github.com/aws/aws-sdk-go-v2/service/wafv2", "github.com/aws/aws-sdk-go-v2/service/waf"),
        maven=(
            "software.amazon.awssdk:wafv2",
            "software.amazon.awssdk:waf",
            "com.amazonaws:aws-java-sdk-wafv2",
            "com.amazonaws:aws-java-sdk-waf",
        ),
        rubygems=("aws-sdk-wafv2", "aws-sdk-waf"),
    )

    lists_tables_without_credentials = True
    supported_versions = (WAF_API_VERSION,)
    default_version = WAF_API_VERSION
    api_docs_url = "https://docs.aws.amazon.com/waf/latest/APIReference/Welcome.html"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AWSWAF

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {f"AWS WAF request failed: {code}": message for code, message in ERROR_MESSAGES.items()}

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: AwsWafSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(
            ENDPOINTS,
            INCREMENTAL_FIELDS,
            names,
            descriptions=ENDPOINT_DESCRIPTIONS,
            should_sync_default=SHOULD_SYNC_DEFAULT,
            default_incremental_lookback_seconds=INCREMENTAL_LOOKBACK_SECONDS,
        )

    def validate_credentials(
        self,
        config: AwsWafSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_credentials(config, schema_name, self.resolve_api_version(api_version))

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[AwsWafResumeConfig]:
        return ResumableSourceManager(inputs, AwsWafResumeConfig)

    def source_for_pipeline(
        self,
        config: AwsWafSourceConfig,
        resumable_source_manager: ResumableSourceManager[AwsWafResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return aws_waf_source(
            config,
            inputs.schema_name,
            resumable_source_manager,
            self.resolve_api_version(inputs.api_version),
            inputs.db_incremental_field_last_value if inputs.should_use_incremental_field else None,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.AWSWAF,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="AWS WAF",
            caption="""Sync AWS WAF configurations into the PostHog Data warehouse.

Grant `wafv2:ListWebACLs` and `wafv2:GetWebACL` to sync web ACLs.
Grant `wafv2:ListRuleGroups` and `wafv2:GetRuleGroup` to sync rule groups.
Grant `wafv2:ListIPSets` and `wafv2:GetIPSet` to sync IP sets.
Grant `wafv2:ListRegexPatternSets` and `wafv2:GetRegexPatternSet` to sync regex pattern sets.
Grant `wafv2:ListAvailableManagedRuleGroups` and `wafv2:DescribeManagedRuleGroup` to sync managed rule groups.
Grant `wafv2:ListWebACLs` and `wafv2:ListResourcesForWebACL`, plus the read permissions for each protected resource type, to sync protected resources.
Grant `wafv2:ListWebACLs`, `wafv2:GetWebACL`, and `wafv2:GetSampledRequests` to sync sampled requests.
Grant `cloudwatch:ListMetrics` and `cloudwatch:GetMetricData` to sync request metrics.

Select a region for regional resources. CloudFront resources use us-east-1.
Sampled requests cover at most the last 3 hours, so sync them at least every 3 hours to keep a continuous history.
Protected resources are only listed for the regional scope.""",
            iconPath="/static/services/aws_waf.png",
            docsUrl="https://docs.aws.amazon.com/waf/latest/APIReference/Welcome.html",
            releaseStatus=ReleaseStatus.BETA,
            keywords=["aws", "waf", "firewall", "security"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="aws_access_key_id",
                        label="AWS access key ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="AKIA...",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="aws_secret_access_key",
                        label="AWS secret access key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="aws_session_token",
                        label="AWS session token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=False,
                        placeholder="Only needed for temporary credentials",
                        secret=True,
                        caption="Temporary credentials expire. Scheduled syncs fail after the session token expires.",
                    ),
                    SourceFieldInputConfig(
                        name="aws_region",
                        label="AWS region",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="us-east-1",
                        secret=False,
                    ),
                    SourceFieldSelectConfig(
                        name="scope",
                        label="Resource scope",
                        required=True,
                        defaultValue="REGIONAL",
                        options=[
                            SourceFieldSelectConfigOption(label="Regional", value="REGIONAL"),
                            SourceFieldSelectConfigOption(label="CloudFront", value="CLOUDFRONT"),
                        ],
                        caption="CloudFront resources always use us-east-1.",
                    ),
                ],
            ),
        )
