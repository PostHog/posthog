from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.gainsight_cs.gainsight_cs import (
    GainsightCsResumeConfig,
    gainsight_cs_source,
    parse_custom_objects,
    resolve_object_name,
    validate_credentials as validate_gainsight_cs_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gainsight_cs.settings import (
    ENDPOINTS,
    GAINSIGHT_CS_OBJECTS,
    GSID,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.gainsightcs import (
    GainsightCsSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

# Probed at source-create to confirm the access key works. Company is the root object of every
# Gainsight CS tenant, so it exists wherever the source is worth connecting.
CREDENTIAL_PROBE_OBJECT = "company"


@SourceRegistry.register
class GainsightCsSource(ResumableSource[GainsightCsSourceConfig, GainsightCsResumeConfig]):
    lists_tables_without_credentials = True  # static object catalog — safe for public docs
    api_docs_url = "https://support.gainsight.com/gainsight_nxt/API_and_Developer_Docs"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GAINSIGHTCS

    @property
    def connection_host_fields(self) -> list[str]:
        # `domain` is where the stored access key is sent; retargeting it must re-require the key.
        return ["domain"]

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        message = (
            "Gainsight rejected the access key. Generate one under Administration → Connectors in "
            "Gainsight, then reconnect."
        )
        return {
            "401 Client Error: Unauthorized": message,
            "403 Client Error: Forbidden": message,
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.gainsight_cs.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: GainsightCsSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        custom_objects = parse_custom_objects(config.custom_objects)
        return build_endpoint_schemas((*ENDPOINTS, *custom_objects), INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: GainsightCsSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if schema_name is None:
            object_name = CREDENTIAL_PROBE_OBJECT
        else:
            try:
                object_name = resolve_object_name(schema_name, config.custom_objects)
            except ValueError as e:
                return False, str(e)

        return validate_gainsight_cs_credentials(config.domain, config.access_key, object_name, team_id)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[GainsightCsResumeConfig]:
        return ResumableSourceManager[GainsightCsResumeConfig](inputs, GainsightCsResumeConfig)

    def source_for_pipeline(
        self,
        config: GainsightCsSourceConfig,
        resumable_source_manager: ResumableSourceManager[GainsightCsResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        object_name = resolve_object_name(inputs.schema_name, config.custom_objects)
        known = GAINSIGHT_CS_OBJECTS.get(inputs.schema_name)

        return gainsight_cs_source(
            domain=config.domain,
            access_key=config.access_key,
            schema_name=inputs.schema_name,
            object_name=object_name,
            # Custom objects aren't in the catalog, but Gsid is Gainsight's universal record id, so
            # it's the merge key there too.
            primary_keys=known.primary_keys if known else [GSID],
            team_id=inputs.team_id,
            resumable_source_manager=resumable_source_manager,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.GAINSIGHT_CS,
            category=DataWarehouseSourceCategory.CRM,
            label="Gainsight CS",
            keywords=["gainsight nxt", "customer success"],
            caption=(
                "Connect Gainsight CS (NXT) with your tenant **domain** and an **access key**. An "
                "admin can generate a key on the **Administration → Connectors** page in Gainsight.\n\n"
                "All objects are synced as full refresh."
            ),
            docsUrl="https://posthog.com/docs/cdp/sources/gainsight-cs",
            iconPath="/static/services/gainsight_cs.png",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="domain",
                        label="Gainsight domain",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="acme.gainsightcloud.com",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="access_key",
                        label="Access key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="custom_objects",
                        label="Custom objects (optional)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="health_score__gc, renewal_forecast__gc",
                        secret=False,
                    ),
                ],
            ),
        )
