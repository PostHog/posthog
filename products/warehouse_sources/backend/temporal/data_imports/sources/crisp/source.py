from typing import cast
from uuid import UUID

from requests.exceptions import HTTPError

from posthog.schema_enums import ProductKey

from products.warehouse_sources.backend.facade.codebase_detection import detect
from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.crisp.crisp import (
    CrispResumeConfig,
    credential_resource,
    crisp_source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.crisp.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.crisp import CrispSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class CrispSource(ResumableSource[CrispSourceConfig, CrispResumeConfig]):
    codebase_detection = detect(
        env=("^CRISP_", "^(NEXT_PUBLIC|VITE|REACT_APP|NUXT_PUBLIC|EXPO_PUBLIC)_CRISP_"),
        script_hosts=("client.crisp.chat",),
        npm=(
            "crisp-sdk-web",
            "crisp-api",
            "@capgo/capacitor-crisp",
            "crisp-sdk-react-native",
            "react-native-crisp-chat-sdk",
        ),
        pypi=("crisp-api",),
        cocoapods=("Crisp",),
        composer=("crispchat/php-crisp-api",),
        go=("github.com/crisp-im/go-crisp-api/crisp",),
        maven=("im.crisp:crisp-sdk",),
        pub=("crisp_chat",),
        rubygems=("crisp-api",),
        swiftpm=("github.com/crisp-im/crisp-sdk-ios",),
        alternative_to=(ProductKey.CONVERSATIONS,),
    )

    lists_tables_without_credentials = True
    supported_versions = ("v1",)
    default_version = "v1"
    api_docs_url = "https://docs.crisp.chat/references/rest-api/v1/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CRISP

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Crisp rejected the token. Enter a valid website token identifier and key.",
            "403 Client Error": "Crisp denied access. Check that the website token belongs to this workspace.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.crisp.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: CrispSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        schemas = build_endpoint_schemas(
            ENDPOINTS,
            {name: endpoint.incremental_fields for name, endpoint in ENDPOINTS.items()},
            names,
            # An append sync of a child table writes every message of a changed conversation again.
            merge_only=[name for name, endpoint in ENDPOINTS.items() if endpoint.fanout is not None],
            should_sync_default={name: endpoint.should_sync_default for name, endpoint in ENDPOINTS.items()},
        )
        for schema in schemas:
            schema.detected_primary_keys = list(ENDPOINTS[schema.name].primary_keys)
        return schemas

    def validate_credentials(
        self,
        config: CrispSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        try:
            UUID(config.website_id)
        except ValueError:
            return False, "Enter the workspace UUID from Crisp Settings > Workspace Settings > Setup Instructions."
        if not config.token_identifier.isascii() or not config.token_key.isascii() or ":" in config.token_identifier:
            return False, "Enter the website token identifier and key exactly as Crisp provides them."
        try:
            probe = credential_resource(config, team_id, self.resolve_api_version(api_version), schema_name)
            next(iter(probe), None)
        except HTTPError as error:
            status = error.response.status_code if error.response is not None else None
            if status == 401:
                return False, "Crisp rejected the token. Enter a valid website token identifier and key."
            if status == 403:
                if schema_name is None:
                    # Website tokens have no table scopes, so a denied workspace probe must fail validation.
                    return False, "Crisp denied access. Check that the website token belongs to this workspace."
                return False, "Crisp denied access to this table. Check the workspace token permissions."
            if status == 404:
                return False, "Crisp could not find the workspace. Check the workspace UUID."
            raise
        return True, None

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[CrispResumeConfig]:
        return ResumableSourceManager(inputs, CrispResumeConfig)

    def source_for_pipeline(
        self,
        config: CrispSourceConfig,
        resumable_source_manager: ResumableSourceManager[CrispResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return crisp_source(config, inputs, resumable_source_manager, self.resolve_api_version(inputs.api_version))

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.CRISP,
            category=DataWarehouseSourceCategory.CUSTOMER_SUPPORT,
            label="Crisp",
            iconPath="/static/services/crisp.png",
            docsUrl="https://posthog.com/docs/cdp/sources/crisp",
            caption="Use a website token from Crisp Settings > Workspace Settings > Advanced configuration > API Token.",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="website_id",
                        label="Workspace UUID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        secret=False,
                        placeholder="00000000-0000-0000-0000-000000000000",
                        caption="Find this in Crisp Settings > Workspace Settings > Setup Instructions.",
                    ),
                    SourceFieldInputConfig(
                        name="token_identifier",
                        label="Token identifier",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        secret=True,
                        placeholder="",
                    ),
                    SourceFieldInputConfig(
                        name="token_key",
                        label="Token key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        secret=True,
                        placeholder="",
                    ),
                ],
            ),
            releaseStatus=ReleaseStatus.GA,
        )
