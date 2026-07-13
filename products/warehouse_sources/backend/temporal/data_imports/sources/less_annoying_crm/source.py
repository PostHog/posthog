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
    LessAnnoyingCRMSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.less_annoying_crm.less_annoying_crm import (
    LessAnnoyingCRMResumeConfig,
    less_annoying_crm_source,
    validate_credentials as validate_less_annoying_crm_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.less_annoying_crm.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    LESS_ANNOYING_CRM_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class LessAnnoyingCRMSource(ResumableSource[LessAnnoyingCRMSourceConfig, LessAnnoyingCRMResumeConfig]):
    # `get_schemas` iterates a static endpoint catalog with no I/O, so the table list is safe to
    # render in public docs without credentials.
    lists_tables_without_credentials = True

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.LESSANNOYINGCRM

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.LESS_ANNOYING_CRM,
            category=DataWarehouseSourceCategory.CRM,
            label="Less Annoying CRM",
            caption="""Enter your Less Annoying CRM API key to pull your CRM data into the PostHog Data warehouse.

Create an API key on the [Programmer API settings page](https://account.lessannoyingcrm.com/app/Settings/Api). Grant the key **read** access — the tables sync via the `GetUsers`, `GetTeams`, `GetContacts`, `GetTasks`, `GetNotes` and `GetEvents` functions.

API keys can't be retrieved after creation, so store the key somewhere safe when you create it.""",
            iconPath="/static/services/less_annoying_crm.png",
            docsUrl="https://posthog.com/docs/cdp/sources/less-annoying-crm",
            keywords=["lacrm", "less annoying"],
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
                ],
            ),
            releaseStatus=ReleaseStatus.ALPHA,
            unreleasedSource=True,
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.less_annoying_crm.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # LACRM returns credential/permission failures as HTTP 400 with an ErrorDescription, which
            # the transport re-raises verbatim. Retrying can never satisfy a bad key, so stop the sync.
            "Invalid credentials": "Your Less Annoying CRM API key is invalid or has been disabled. Create a new API key in your account's Programmer API settings, then reconnect.",
        }

    def get_schemas(
        self,
        config: LessAnnoyingCRMSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                # LACRM has no server-side modified-since filter, so every table is full refresh only.
                supports_incremental=False,
                supports_append=False,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                detected_primary_keys=LESS_ANNOYING_CRM_ENDPOINTS[endpoint].primary_keys,
                should_sync_default=LESS_ANNOYING_CRM_ENDPOINTS[endpoint].should_sync_default,
            )
            for endpoint in ENDPOINTS
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self, config: LessAnnoyingCRMSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_less_annoying_crm_credentials(config.api_key):
            return True, None

        return False, "Invalid Less Annoying CRM API key"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[LessAnnoyingCRMResumeConfig]:
        return ResumableSourceManager[LessAnnoyingCRMResumeConfig](inputs, LessAnnoyingCRMResumeConfig)

    def source_for_pipeline(
        self,
        config: LessAnnoyingCRMSourceConfig,
        resumable_source_manager: ResumableSourceManager[LessAnnoyingCRMResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return less_annoying_crm_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
