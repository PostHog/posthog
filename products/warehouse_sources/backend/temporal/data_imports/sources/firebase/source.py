from typing import Optional, cast

from products.warehouse_sources.backend.facade.codebase_detection import detect
from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
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
    get_incremental_fields,
    get_tables,
    validate_credentials as validate_firebase_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.firebase.settings import (
    API_VERSION,
    DEFAULT_DATABASE_ID,
    FIRESTORE_INDEX_REQUIRED_ERROR,
    REALTIME_DATABASE_NOT_FOUND_ERROR,
    RESPONSE_TOO_LARGE_ERROR,
    parse_realtime_database_paths,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.firebase import (
    FirebaseSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class FirebaseSource(ResumableSource[FirebaseSourceConfig, FirebaseResumeConfig]):
    # Firebase authenticates with a service-account JSON key file, not a
    # pasteable string. The terminal credential prompt only collects
    # single-line text, so there is no safe in-cli path: the file upload lives
    # in the app's new-source form. Deep-link there instead of dead-ending on a
    # credential the CLI cannot accept.
    # NOTE: the `firebase` client SDK also covers auth-only projects, which
    # have no Firestore data to import. We accept the false positives - the
    # package is a strong signal for the common case.
    codebase_detection = detect(
        env=("^FIREBASE_", "^NEXT_PUBLIC_FIREBASE_", "^FIRESTORE_EMULATOR_HOST$"),
        script_hosts=("cdn.firebase.com",),
        npm=(
            "firebase-admin",
            "firebase",
            "firebase-tools",
            "firebase-functions",
            "firebase-functions-test",
            "@firebase/app",
            "@firebase/ai",
            "@firebase/app-check",
            "@firebase/auth",
            "@firebase/data-connect",
            "@firebase/database",
            "@firebase/firestore",
            "@firebase/functions",
            "@firebase/installations",
            "@firebase/messaging",
            "@firebase/performance",
            "@firebase/remote-config",
            "@firebase/storage",
            "@firebase/vertexai",
            "@firebase/rules-unit-testing",
            "firebaseui",
            "react-firebaseui",
            "reactfire",
            "rxfire",
            "geofire",
            "@angular/fire",
            "angularfire",
            "emberfire",
            "vuefire",
            "nuxt-vuefire",
            "@nuxtjs/firebase",
            "react-firebase-hooks",
            "@genkit-ai/firebase",
            "@react-native-firebase/app",
            "@react-native-firebase/ai",
            "@react-native-firebase/app-check",
            "@react-native-firebase/app-distribution",
            "@react-native-firebase/auth",
            "@react-native-firebase/crashlytics",
            "@react-native-firebase/database",
            "@react-native-firebase/dynamic-links",
            "@react-native-firebase/firestore",
            "@react-native-firebase/functions",
            "@react-native-firebase/in-app-messaging",
            "@react-native-firebase/installations",
            "@react-native-firebase/messaging",
            "@react-native-firebase/ml",
            "@react-native-firebase/perf",
            "@react-native-firebase/remote-config",
            "@react-native-firebase/storage",
            "@capacitor-firebase/app",
            "@capacitor-firebase/authentication",
            "@capacitor-firebase/messaging",
            "@capacitor-firebase/crashlytics",
            "@capacitor-firebase/firestore",
        ),
        pypi=("firebase-admin", "firebase-functions", "pyrebase4"),
        cocoapods=(
            "FirebaseFirestore",
            "Firebase",
            "FirebaseCore",
            "FirebaseAuth",
            "FirebaseMessaging",
            "FirebaseCrashlytics",
            "FirebaseDatabase",
            "FirebaseStorage",
            "FirebaseRemoteConfig",
            "FirebasePerformance",
            "FirebaseFunctions",
            "FirebaseAppCheck",
            "FirebaseInAppMessaging",
            "FirebaseDynamicLinks",
            "FirebaseInstallations",
            "FirebaseFirestoreSwift",
            "FirebaseAI",
            "FirebaseVertexAI",
            "FirebaseAppDistribution",
            "FirebaseMLModelDownloader",
            "FirebaseUI",
            "FirebaseInstanceID",
        ),
        composer=("kreait/firebase-php", "kreait/laravel-firebase", "kreait/firebase-bundle", "kreait/firebase-tokens"),
        go=("firebase.google.com/go",),
        maven=(
            "com.google.firebase:firebase-firestore",
            "com.google.firebase:firebase-admin",
            "com.google.firebase:firebase-server-sdk",
            "com.google.firebase:firebase-bom",
            "com.google.firebase:firebase-core",
            "com.google.firebase:firebase-common",
            "com.google.firebase:firebase-auth",
            "com.google.firebase:firebase-auth-ktx",
            "com.google.firebase:firebase-messaging",
            "com.google.firebase:firebase-messaging-ktx",
            "com.google.firebase:firebase-crashlytics",
            "com.google.firebase:firebase-crashlytics-ktx",
            "com.google.firebase:firebase-crashlytics-ndk",
            "com.google.firebase:firebase-crashlytics-gradle",
            "com.google.firebase:firebase-database",
            "com.google.firebase:firebase-database-ktx",
            "com.google.firebase:firebase-firestore-ktx",
            "com.google.firebase:firebase-storage",
            "com.google.firebase:firebase-storage-ktx",
            "com.google.firebase:firebase-config",
            "com.google.firebase:firebase-config-ktx",
            "com.google.firebase:firebase-perf",
            "com.google.firebase:firebase-perf-ktx",
            "com.google.firebase:perf-plugin",
            "com.google.firebase:firebase-functions",
            "com.google.firebase:firebase-functions-ktx",
            "com.google.firebase:firebase-appcheck",
            "com.google.firebase:firebase-appcheck-playintegrity",
            "com.google.firebase:firebase-appcheck-debug",
            "com.google.firebase:firebase-inappmessaging",
            "com.google.firebase:firebase-inappmessaging-display",
            "com.google.firebase:firebase-dynamic-links",
            "com.google.firebase:firebase-dynamic-links-ktx",
            "com.google.firebase:firebase-installations",
            "com.google.firebase:firebase-appdistribution",
            "com.google.firebase:firebase-appdistribution-api",
            "com.google.firebase:firebase-appdistribution-gradle",
            "com.google.firebase:firebase-ai",
            "com.google.firebase:firebase-vertexai",
            "com.google.firebase:firebase-dataconnect",
            "com.google.firebase:firebase-ml-modeldownloader",
            "com.google.firebase:firebase-iid",
            "com.google.firebase:firebase-crash",
            "com.firebaseui:firebase-ui-auth",
            "com.firebaseui:firebase-ui-database",
            "com.firebaseui:firebase-ui-firestore",
            "com.firebaseui:firebase-ui-storage",
        ),
        pub=(
            "cloud_firestore",
            "firebase_core",
            "firebase_auth",
            "firebase_messaging",
            "firebase_crashlytics",
            "firebase_database",
            "firebase_storage",
            "firebase_remote_config",
            "firebase_performance",
            "cloud_functions",
            "firebase_functions",
            "firebase_app_check",
            "firebase_in_app_messaging",
            "firebase_app_installations",
            "firebase_dynamic_links",
            "firebase_ml_model_downloader",
            "firebase_ai",
            "firebase_vertexai",
            "firebase_data_connect",
            "cloud_firestore_odm",
            "firebase_ui_auth",
            "firebase_ui_firestore",
            "firebase_ui_database",
            "firebase_ui_storage",
            "firebase_ui_oauth",
            "firebase_ui_oauth_google",
            "firebase_ui_oauth_apple",
            "firebase_ui_oauth_facebook",
            "firebase_ui_oauth_twitter",
            "firebase_admin_sdk",
        ),
        rubygems=("firebase",),
        swiftpm=(
            "github.com/firebase/firebase-ios-sdk",
            "github.com/firebase/firebaseui-ios",
            "github.com/firebase/data-connect-ios-sdk",
        ),
    )

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
            REALTIME_DATABASE_NOT_FOUND_ERROR: "No Realtime Database exists at this source's URL. Copy the URL from the Firebase console's Realtime Database page into the source, then re-enable the sync.",
            RESPONSE_TOO_LARGE_ERROR: "Firebase returned a page too large to process. Reduce the size of the documents in this collection or path, then re-run the sync.",
            # Firestore indexes every field on its own by default, so this only appears once someone
            # exempts the chosen field from indexing. Google's message carries a console link that
            # builds the index in one click, and no message of ours beats that, so it passes through
            # unchanged. Building the index takes minutes, which outlasts every retry.
            FIRESTORE_INDEX_REQUIRED_ERROR: None,
            # Identity Toolkit's `accounts:batchGet` rejects every request this way when the project
            # has no Firebase Authentication configuration at all — retrying can't create one.
            "message=CONFIGURATION_NOT_FOUND": "This Firebase project doesn't have Firebase Authentication enabled, so PostHog can't read its Auth users. Enable Firebase Authentication in the Firebase console, or remove the Auth users table from this source.",
            # Identity Toolkit also rejects `accounts:batchGet` this way, as a 400 rather than a 403,
            # when the service account lacks the IAM role to list Auth users at all.
            "message=INSUFFICIENT_PERMISSION": "This service account can't read Firebase Authentication users. Grant it the Firebase Authentication Viewer role (or Firebase Viewer), then reconnect.",
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.FIREBASE,
            category=DataWarehouseSourceCategory.DATABASES,
            label="Firebase",
            caption="""Connect a Firebase project to pull Cloud Firestore collections, Firebase Auth users, and Realtime Database paths into the PostHog Data warehouse.

Create a service account key in the Firebase console under Project settings, Service accounts, Generate new private key, then upload that JSON file here. Grant the service account **Firebase Viewer** to read Auth users, **Cloud Datastore Viewer** to read Firestore, and **Firebase Realtime Database Viewer** to read the Realtime Database.""",
            iconPath="/static/services/firebase.png",
            docsUrl="https://posthog.com/docs/cdp/sources/firebase",
            releaseStatus=ReleaseStatus.GA,
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
        # from the live project.
        credentials = self._credentials(config)
        tables = get_tables(credentials, force_refresh=force_refresh)
        if names is not None:
            wanted = set(names)
            tables = [table for table in tables if table in wanted]

        # Costs one request per Firestore collection, so it stays behind the `names` filter above:
        # the sync settings for one table ask for that table alone.
        incremental_fields = get_incremental_fields(credentials, tables)
        return [
            SourceSchema(
                name=table,
                supports_incremental=bool(incremental_fields.get(table)),
                supports_append=bool(incremental_fields.get(table)),
                incremental_fields=incremental_fields.get(table, []),
            )
            for table in tables
        ]

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
            should_use_incremental_field=inputs.should_use_incremental_field,
            incremental_field_name=inputs.incremental_field,
            incremental_field_type=inputs.incremental_field_type,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value,
        )
