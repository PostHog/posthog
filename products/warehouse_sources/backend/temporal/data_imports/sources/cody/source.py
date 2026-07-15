from typing import Optional, cast

import requests

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
from products.warehouse_sources.backend.temporal.data_imports.sources.cody.cody import (
    CODY_BASE_URL,
    CodyCredentialsError,
    CodyResumeConfig,
    CodyRetryableError,
    cody_source,
    validate_credentials as validate_cody_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.cody.settings import (
    CODY_ENDPOINTS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import CodySourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class CodySource(ResumableSource[CodySourceConfig, CodyResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CODY

    @property
    def connection_host_fields(self) -> list[str]:
        # instance_url selects which instance's analytics the stored token is used against;
        # changing it must require re-entering the secret so a preserved token can't be
        # retargeted at another instance.
        return ["instance_url"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.CODY,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Cody",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Sourcegraph Analytics access token to pull Cody and Sourcegraph usage reports into the PostHog Data warehouse.

Sourcegraph Analytics is available to Sourcegraph Enterprise customers. Create an access token at [analytics.sourcegraph.com/access-tokens](https://analytics.sourcegraph.com/access-tokens). The instance URL is your Sourcegraph instance's host, e.g. `example.sourcegraphcloud.com`.
""",
            iconPath="/static/services/cody.svg",
            docsUrl="https://posthog.com/docs/cdp/sources/cody",
            keywords=["ai coding assistant", "developer analytics", "sourcegraph", "usage"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="instance_url",
                        label="Instance URL",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="example.sourcegraphcloud.com",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="access_token",
                        label="Access token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.cody.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # An invalid or revoked access token surfaces as a requests HTTPError when `_fetch`
            # calls `raise_for_status()`. Retrying can never satisfy a credential problem, so stop
            # the sync. Match the stable status text and base host, not the per-request path.
            f"401 Client Error: Unauthorized for url: {CODY_BASE_URL}": "Your Sourcegraph Analytics access token is invalid or has expired. Create a new token at analytics.sourcegraph.com under Access tokens, then reconnect.",
            f"403 Client Error: Forbidden for url: {CODY_BASE_URL}": "Your Sourcegraph account does not have access to this instance's analytics. Check the instance URL and that your account is linked to the instance's usage metrics.",
        }

    def get_schemas(
        self,
        config: CodySourceConfig,
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
                should_sync_default=CODY_ENDPOINTS[endpoint].should_sync_default,
                description=CODY_ENDPOINTS[endpoint].description,
            )
            for endpoint in ENDPOINTS
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self, config: CodySourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        try:
            # validate_cody_credentials returns True or raises — it never returns False — so an
            # unexpected status surfaces its real cause instead of a conflated credential error.
            validate_cody_credentials(config.access_token, config.instance_url)
            return True, None
        except CodyCredentialsError as e:
            return False, str(e)
        except (CodyRetryableError, requests.RequestException):
            # A rate-limit, 5xx, or network blip isn't a bad credential — don't mislabel it.
            return (
                False,
                "Could not reach Sourcegraph Analytics to validate credentials. This may be a temporary rate-limit or network issue — please try again.",
            )

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[CodyResumeConfig]:
        return ResumableSourceManager[CodyResumeConfig](inputs, CodyResumeConfig)

    def source_for_pipeline(
        self,
        config: CodySourceConfig,
        resumable_source_manager: ResumableSourceManager[CodyResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return cody_source(
            access_token=config.access_token,
            instance_url=config.instance_url,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
