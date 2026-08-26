from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldFileUploadConfig,
    SourceFieldFileUploadJsonFormatConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.firebase.firebase import (
    FirebaseCredentials,
    FirebaseResumeConfig,
    firebase_source,
    get_tables,
    validate_credentials as validate_firebase_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.firebase.settings import (
    API_VERSION,
    DEFAULT_DATABASE_ID,
    RESPONSE_TOO_LARGE_ERROR,
    parse_realtime_database_paths,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.firebase import (
    FirebaseSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class FirebaseSource(ResumableSource[FirebaseSourceConfig, FirebaseResumeConfig]):
    # Firestore and Identity Platform both keep `v1beta*` channels alongside `v1`; `v1` is GA.
    supported_versions = (API_VERSION,)
    default_version = API_VERSION
    api_docs_url = "https://firebase.google.com/docs/firestore/reference/rest"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.FIREBASE

    @property
    def connection_host_fields(self) -> list[str]:
        # The Realtime Database URL is where the minted Google access token gets sent, so
        # retargeting it has to re-require the service account key. `database_id` and
        # `realtime_database_paths` don't change the host, but they do select which Firestore
        # database and which Realtime Database nodes the preserved key reads — the same
        # retargeting risk against a different data scope — so gate all three the same way.
        return ["database_id", "realtime_database_url", "realtime_database_paths"]

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "error=invalid_grant": "Google rejected this service account key. Generate a new key in the Firebase console and reconnect.",
            "Google refused to issue an access token": "Google could not issue an access token for this service account. Check that the key file is complete and the service account still exists.",
            "private key could not be read": "The uploaded key file does not contain a usable private key. Upload the JSON key exactly as Google generated it.",
            "401 Client Error: Unauthorized": "Firebase rejected the access token. The service account key may have been revoked — please reconnect.",
            "403 Client Error: Forbidden": "This service account cannot read the requested Firebase data. Grant it the Firebase Viewer, Cloud Datastore Viewer, or Firebase Realtime Database Viewer role.",
            RESPONSE_TOO_LARGE_ERROR: "Firebase returned a page too large to process. Reduce the size of the documents in this collection or path, then re-run the sync.",
            # Identity Toolkit's `accounts:batchGet` rejects every request this way when the project
            # has no Firebase Authentication configuration at all — retrying can't create one.
            "message=CONFIGURATION_NOT_FOUND": "This Firebase project doesn't have Firebase Authentication enabled, so PostHog can't read its Auth users. Enable Firebase Authentication in the Firebase console, or remove the Auth users table from this source.",
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.FIREBASE,
            category=DataWarehouseSourceCategory.DATABASES,
            label="Firebase",
            caption="""Connect a Firebase project to pull Cloud Firestore collections, Firebase Auth users, and Realtime Database paths into the PostHog Data warehouse.

Create a service account key in the Firebase console under Project settings, Service accounts, Generate new private key, then upload that JSON file here. Grant the service account **Firebase Viewer** to read Auth users, **Cloud Datastore Viewer** to read Firestore, and **Firebase Realtime Database Viewer** to read the Realtime Database.""",
            iconPath="/static/services/firebase.png",
            docsUrl="https://posthog.com/docs/cdp/sources/firebase",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["firestore", "rtdb", "gcp", "nosql"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldFileUploadConfig(
                        name="key_file",
                        label="Firebase service account JSON key file",
                        fileFormat=SourceFieldFileUploadJsonFormatConfig(
                            format=".json",
                            keys=["project_id", "private_key", "private_key_id", "client_email", "token_uri"],
                        ),
                        required=True,
                    ),
                    SourceFieldInputConfig(
                        name="database_id",
                        label="Firestore database ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder=DEFAULT_DATABASE_ID,
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="realtime_database_url",
                        label="Realtime Database URL",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="https://my-project-default-rtdb.firebaseio.com",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="realtime_database_paths",
                        label="Realtime Database paths",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="rooms, messages/lobby",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.firebase.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: FirebaseSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        # Firestore collections are created by the customer's app, so the table list can only come
        # from the live project. Nothing here supports a server-side timestamp filter, so every
        # table is full refresh.
        tables = get_tables(self._credentials(config))
        if names is not None:
            wanted = set(names)
            tables = [table for table in tables if table in wanted]
        return [SourceSchema(name=table, supports_incremental=False, supports_append=False) for table in tables]

    def _credentials(self, config: FirebaseSourceConfig) -> FirebaseCredentials:
        database_id = (config.database_id or "").strip() or DEFAULT_DATABASE_ID
        return FirebaseCredentials(
            project_id=config.key_file.project_id,
            client_email=config.key_file.client_email,
            private_key=config.key_file.private_key,
            private_key_id=config.key_file.private_key_id,
            token_uri=config.key_file.token_uri,
            database_id=database_id,
            realtime_database_url=(config.realtime_database_url or "").strip() or None,
            realtime_database_paths=tuple(parse_realtime_database_paths(config.realtime_database_paths)),
        )

    def validate_credentials(
        self,
        config: FirebaseSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_firebase_credentials(self._credentials(config))

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[FirebaseResumeConfig]:
        return ResumableSourceManager[FirebaseResumeConfig](inputs, FirebaseResumeConfig)

    def source_for_pipeline(
        self,
        config: FirebaseSourceConfig,
        resumable_source_manager: ResumableSourceManager[FirebaseResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return firebase_source(
            credentials=self._credentials(config),
            table_name=inputs.schema_name,
            resumable_source_manager=resumable_source_manager,
            logger=inputs.logger,
        )
