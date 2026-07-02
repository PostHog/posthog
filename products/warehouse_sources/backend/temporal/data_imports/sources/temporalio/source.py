from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import TemporalIOSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.temporalio.temporalio import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    TemporalIOResource,
    TemporalIOResumeConfig,
    temporalio_source,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class TemporalIOSource(ResumableSource[TemporalIOSourceConfig, TemporalIOResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.TEMPORALIO

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.temporalio.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        # rustls surfaces mTLS rejections as TLS alert names inside the tonic transport
        # error. These are credential problems — retrying can never recover.
        return {
            # The Temporal core builds the connection target from the configured host:port. An empty
            # or scheme-only host yields no parseable host — a config problem retrying never fixes.
            "invalid target URL: empty host": "Temporal could not connect because the configured host is empty or invalid. Update the source with the hostname of your Temporal namespace's gRPC endpoint (for example, your-namespace.account.tmprl.cloud) — without a protocol scheme or port.",
            # tonic's DNS resolver surfaces getaddrinfo's EAI_NONAME as this exact phrase when the
            # configured host does not resolve at all (a wrong/typo'd hostname, a deleted namespace,
            # or a scheme/port accidentally pasted into the host field). Retrying never recovers a
            # name that doesn't exist in DNS. Match the EAI_NONAME phrase specifically — the transient
            # EAI_AGAIN ("Temporary failure in name resolution") is a different message and stays
            # retryable.
            "failed to lookup address information: Name or service not known": "Temporal could not connect because the configured host could not be found in DNS. Check the source's host points at your Temporal namespace's gRPC endpoint (for example, your-namespace.account.tmprl.cloud) — without a protocol scheme or port — and that the namespace still exists.",
            "received fatal alert: UnknownCA": "Temporal rejected this source's client certificate because it is not signed by a certificate authority the namespace trusts. This usually means the namespace's CA certificates were rotated — update the source with a client certificate and key signed by the current CA.",
            "received fatal alert: CertificateExpired": "This source's client certificate has expired. Update the source with a renewed client certificate and key.",
            "received fatal alert: CertificateRevoked": "This source's client certificate has been revoked. Update the source with a new client certificate and key.",
            "received fatal alert: BadCertificate": "Temporal rejected this source's client certificate as invalid. Update the source with a valid client certificate and key.",
            "received fatal alert: CertificateUnknown": "Temporal rejected this source's client certificate. Update the source with a valid client certificate and key.",
            "invalid peer certificate": "The Temporal server's certificate could not be verified. Check the host and port point at your Temporal namespace's gRPC endpoint.",
            # tonic/rustls raises CertificateParseError when one of the PEM credential blobs cannot be
            # decoded at all (vs the alerts above, which reject an otherwise-parseable cert). The blobs
            # come straight from the source config, so this is a malformed-credential problem — retrying
            # can never recover.
            "CertificateParseError": "PostHog could not parse the TLS certificate or key configured for this source. Check that the client certificate, client private key, and server client root CA are valid PEM and were pasted in full, including the BEGIN and END lines.",
            # tonic surfaces a gRPC UNAUTHENTICATED status when the server requires API key (JWT/Bearer)
            # authentication, which this source does not provide — it authenticates with mTLS client
            # certificates. This is a credential/host configuration problem, so retrying can never recover.
            "code: Unauthenticated": "Temporal rejected the connection because it requires API key (JWT) authentication, which this source does not provide. This usually means the configured host points at a Temporal Cloud API endpoint that uses API key authentication rather than your namespace's mTLS gRPC endpoint (typically <namespace>.<account>.tmprl.cloud:7233). Update the source's host to the namespace's gRPC endpoint that accepts client-certificate (mTLS) authentication.",
        }

    def get_schemas(
        self,
        config: TemporalIOSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=INCREMENTAL_FIELDS.get(endpoint, None) is not None,
                supports_append=INCREMENTAL_FIELDS.get(endpoint, None) is not None,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[TemporalIOResumeConfig]:
        return ResumableSourceManager[TemporalIOResumeConfig](inputs, TemporalIOResumeConfig)

    def source_for_pipeline(
        self,
        config: TemporalIOSourceConfig,
        resumable_source_manager: ResumableSourceManager[TemporalIOResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return temporalio_source(
            config,
            TemporalIOResource(inputs.schema_name),
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            resumable_source_manager=resumable_source_manager,
            logger=inputs.logger,
            should_use_incremental_field=inputs.should_use_incremental_field,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.TEMPORAL_IO,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            keywords=["temporal"],
            label="Temporal.io",
            iconPath="/static/services/temporal.png",
            docsUrl="https://posthog.com/docs/cdp/sources/temporal",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="host",
                        label="Host",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="port",
                        label="Port",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="namespace",
                        label="Namespace",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="encryption_key",
                        label="Encryption key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=False,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="fallback_decryption_keys",
                        label="Fallback decryption keys",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=False,
                        placeholder="key1,key2,key3",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="server_client_root_ca",
                        label="Server client root CA",
                        type=SourceFieldInputConfigType.TEXTAREA,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="client_certificate",
                        label="Client certificate",
                        type=SourceFieldInputConfigType.TEXTAREA,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="client_private_key",
                        label="Client private key",
                        type=SourceFieldInputConfigType.TEXTAREA,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )
