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

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import (
    SourceInputs,
    SourceResponse,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import _is_host_safe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import JotformSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.jotform.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.jotform.jotform import (
    JotformResumeConfig,
    jotform_source,
    normalize_enterprise_host,
    validate_credentials as validate_jotform_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.jotform.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class JotformSource(ResumableSource[JotformSourceConfig, JotformResumeConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.JOTFORM

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.JOTFORM,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Jotform",
            caption="""Enter your Jotform API key to pull your forms and submissions into the PostHog Data warehouse.

You can create an API key in your [Jotform API settings](https://www.jotform.com/myaccount/api). A **Read-only** key is enough.

Pick the region that matches where your Jotform account is hosted. For Jotform Enterprise, leave the region as US and enter your Enterprise domain instead.

Supported tables:
- `forms`
- `submissions`
- `reports`
- `questions`
""",
            iconPath="/static/services/jotform.png",
            docsUrl="https://posthog.com/docs/cdp/sources/jotform",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldSelectConfig(
                        name="region",
                        label="Region",
                        required=True,
                        defaultValue="us",
                        options=[
                            SourceFieldSelectConfigOption(label="US (api.jotform.com)", value="us"),
                            SourceFieldSelectConfigOption(label="EU (eu-api.jotform.com)", value="eu"),
                            SourceFieldSelectConfigOption(label="HIPAA (hipaa-api.jotform.com)", value="hipaa"),
                        ],
                    ),
                    SourceFieldInputConfig(
                        name="enterprise_domain",
                        label="Enterprise domain (optional)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="forms.your-company.com",
                        secret=False,
                    ),
                ],
            ),
        )

    @property
    def connection_host_fields(self) -> list[str]:
        # The stored API key is sent to whatever host `enterprise_domain` resolves to, so editing it
        # must re-require the secret — otherwise it could be retargeted at an attacker-controlled host.
        return ["enterprise_domain"]

    def get_canonical_descriptions(self):
        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        # Auth failures can never be fixed by retrying. Match the stable status text only (not the
        # per-request URL) so it covers every regional and Enterprise host.
        return {
            "401 Client Error": "Your Jotform API key is invalid or has been revoked. Create a new key in your Jotform API settings, then reconnect.",
            "403 Client Error": "Your Jotform API key does not have permission to read this data. Grant it read access in your Jotform API settings, then reconnect.",
        }

    def get_schemas(
        self,
        config: JotformSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=endpoint in INCREMENTAL_FIELDS,
                supports_append=endpoint in INCREMENTAL_FIELDS,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in ENDPOINTS
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def _check_enterprise_host_safe(self, enterprise_domain: Optional[str], team_id: int) -> tuple[bool, str | None]:
        # `enterprise_domain` is user-supplied and the stored API key is sent to whatever it resolves
        # to, so reject internal/private hosts. Run at validation *and* before each sync, since DNS
        # can be repointed at an internal host after setup (Smokescreen re-resolves per hop too).
        host = normalize_enterprise_host(enterprise_domain)
        if host is None:
            return True, None
        is_safe, host_error = _is_host_safe(host, team_id)
        if not is_safe:
            return False, host_error or "Enterprise domain is not allowed"
        return True, None

    def validate_credentials(
        self, config: JotformSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        enterprise_domain = config.enterprise_domain

        is_safe, host_error = self._check_enterprise_host_safe(enterprise_domain, team_id)
        if not is_safe:
            return False, host_error

        if validate_jotform_credentials(config.api_key, config.region, enterprise_domain):
            return True, None

        return False, "Invalid Jotform API key, region, or Enterprise domain"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[JotformResumeConfig]:
        return ResumableSourceManager[JotformResumeConfig](inputs, JotformResumeConfig)

    def source_for_pipeline(
        self,
        config: JotformSourceConfig,
        resumable_source_manager: ResumableSourceManager[JotformResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        is_safe, host_error = self._check_enterprise_host_safe(config.enterprise_domain, inputs.team_id)
        if not is_safe:
            raise ValueError(host_error or "Jotform Enterprise domain is not allowed")

        return jotform_source(
            api_key=config.api_key,
            region=config.region,
            enterprise_domain=config.enterprise_domain,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )
