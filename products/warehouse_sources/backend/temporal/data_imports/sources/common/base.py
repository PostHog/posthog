import dataclasses
from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Generic, Optional, TypeVar, Union

import structlog

from products.warehouse_sources.backend.temporal.data_imports.sources.common.webhook_s3 import WebhookSourceManager

if TYPE_CHECKING:
    from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC

    from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource

from posthog.schema import (
    SourceConfig,
    SourceFieldFileUploadConfig,
    SourceFieldInputConfig,
    SourceFieldOauthConfig,
    SourceFieldSelectConfig,
    SourceFieldSSHTunnelConfig,
    SourceFieldSwitchGroupConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import (
    ResumableData,
    SourceInputs,
    SourceResponse,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.config import Config
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import get_config_for_source
from products.warehouse_sources.backend.types import ExternalDataSourceType, IncrementalField

logger = structlog.get_logger(__name__)

MARKETING_ANALYTICS_SUGGESTED_TABLE_TOOLTIP = "Required for Marketing analytics to work with this source."


def _incremental_field_labels(fields: list[IncrementalField]) -> list[str]:
    labels = []
    for f in fields:
        label = f.get("label") or f.get("field")
        if label:
            labels.append(label)
    return labels


def _documented_table_from_schema(schema: SourceSchema, canonical: Mapping[str, Any]) -> dict[str, Any]:
    """Shape a `SourceSchema` (+ curated canonical entry) into a public-docs table entry."""
    if schema.webhook_only:
        sync_methods = ["Webhook only"]
    else:
        sync_methods = []
        if schema.supports_webhooks:
            sync_methods.append("Webhook")
        if schema.supports_cdc:
            sync_methods.append("CDC")
        if schema.supports_incremental:
            sync_methods.append("Incremental")
        if schema.supports_append and not schema.supports_incremental:
            sync_methods.append("Append only")
        sync_methods.append("Full refresh")

    return {
        "name": schema.name,
        "label": schema.label or schema.name,
        "description": schema.description or canonical.get("description"),
        "sync_methods": sync_methods,
        "incremental_fields": _incremental_field_labels(schema.incremental_fields),
        "primary_keys": schema.detected_primary_keys or [],
    }


ConfigType = TypeVar("ConfigType", bound=Config)
ConfigType_contra = TypeVar("ConfigType_contra", bound=Config, contravariant=True)

FieldType = Union[
    SourceFieldInputConfig,
    SourceFieldSwitchGroupConfig,
    SourceFieldSelectConfig,
    SourceFieldOauthConfig,
    SourceFieldFileUploadConfig,
    SourceFieldSSHTunnelConfig,
]

SourceCredentialsValidationResult = tuple[bool, str | None]


class _BaseSource(ABC, Generic[ConfigType]):
    """Base class for all data import sources.

    This class provides common functionality for all sources but does NOT define
    source_for_pipeline - use SimpleSource or ResumableSource instead.
    """

    # Default `False` for every source; `SQLSource` flips to `True` (subclasses opt out
    # via their own override if a driver genuinely can't project columns).
    # `True` means the source lists typed columns at schema discovery and applies
    # `enabled_columns` itself (SELECT projection). Sources left `False` still get column
    # selection — the pipeline drops non-enabled columns just before the Delta write and
    # captures the observed columns into `schema_metadata` after the first sync.
    supports_column_selection: bool = False

    # `True` only for sources that push `row_filters` into their query (SQL WHERE).
    # Sources without pushdown must reject filters — a saved-but-ignored filter would
    # silently sync unfiltered rows.
    supports_row_filters: bool = False

    # `True` for sources whose HogQL tables use a PostHog-managed canonical schema
    # (`external_table_definitions`) — Stripe, Paddle, Zendesk. Their query exposes a fixed
    # field set (and powers revenue analytics), so the physical column set must stay complete.
    # Column selection is disabled for these: dropping a canonically-referenced column makes the
    # generated s3() structure miss it and the query fails to resolve the field.
    has_managed_hogql_schema: bool = False

    # Opt-in: set `True` only on sources whose `get_schemas` iterates a static endpoint
    # catalog with NO I/O — no network, no DB, no credentials. Those sources surface their
    # table list in public docs (see `get_documented_tables`). Left `False` for SQL / file /
    # API sources that discover schemas over a live connection, since calling their
    # `get_schemas` with a placeholder config could connect, hang, or close the DB session.
    lists_tables_without_credentials: bool = False

    @property
    @abstractmethod
    def source_type(self) -> ExternalDataSourceType:
        raise NotImplementedError()

    @property
    def _config_class(self) -> type[ConfigType]:
        config = get_config_for_source(self.source_type)
        if not config:
            raise ValueError(f"Config class for {self.source_type} does not exist in SOURCE_CONFIG_MAPPING")

        return config

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        """Returns the errors for which the source should be disabled on.

        Returns `dict[str, str | None]`:
            key = a partial error message to match on
            value = a friendly error message to show to users. We fallback to displaying the key when this is missing
        """

        return {}

    def get_retryable_error_overrides(self) -> tuple[str, ...]:
        """Substrings that force an error to stay retryable even when a `get_non_retryable_errors`
        key also substring-matches it. Use for a transient failure whose message unavoidably
        contains a broad non-retryable phrase, so the narrow, more specific override wins and the
        activity keeps retrying instead of permanently disabling the sync.
        """

        return ()

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        """Curated, documentation-sourced descriptions for this source's well-known tables/endpoints.

        Keyed by schema/endpoint name (matching what `get_schemas` returns). Each entry may carry a
        table `description`, a `docs_url`, and per-`columns` descriptions. The default empty mapping
        means every table falls back to LLM enrichment. Only meaningful for fixed-schema sources
        (SaaS APIs); SQL sources with arbitrary user schemas leave this empty. Override with a lazy
        import of the source's sibling `canonical_descriptions.py`.
        """

        return {}

    def get_schemas(
        self,
        config: ConfigType,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        """Return the list of schemas available for this source.

        ``force_refresh=True`` instructs the source to bypass any internal cache
        of upstream schema discovery (e.g. paginated API listings). Sources
        without caches can ignore the flag.
        """
        raise NotImplementedError()

    def _placeholder_config(self) -> ConfigType:
        """Build a credential-free config instance for static, no-network schema listing.

        Required (no-default) fields are filled with empty placeholders. We construct the
        dataclass directly (bypassing `from_dict`), so no converters or validation run and
        the resulting object only satisfies the `get_schemas` signature — it is never used
        to make a request.
        """
        cls = self._config_class
        kwargs: dict[str, Any] = {}
        for f in dataclasses.fields(cls):
            # `init=False` fields aren't accepted by `__init__`; passing them raises TypeError.
            if not f.init:
                continue
            if f.default is not dataclasses.MISSING or f.default_factory is not dataclasses.MISSING:
                continue
            kwargs[f.name] = ""
        return cls(**kwargs)

    def get_documented_tables(self) -> list[dict[str, Any]]:
        """Credential-free table catalog for public documentation (posthog.com).

        Returns one entry per well-known table for fixed-schema sources, merging
        `get_schemas` metadata (sync methods, incremental fields) with curated
        `get_canonical_descriptions`. SQL / file sources (user-defined schemas) return
        ``[]`` so their docs render a generic "discovered from your source" note. Any
        failure degrades to ``[]`` — this must never break the public endpoint.
        """
        if not self.lists_tables_without_credentials:
            return []
        try:
            schemas = self.get_schemas(self._placeholder_config(), team_id=0)
            canonical = self.get_canonical_descriptions()
            return [_documented_table_from_schema(schema, canonical.get(schema.name, {})) for schema in schemas]
        except Exception:
            logger.exception("get_documented_tables failed", source_type=str(self.source_type))
            return []

    @property
    @abstractmethod
    def get_source_config(self) -> SourceConfig:
        raise NotImplementedError()

    def parse_config(self, job_inputs: dict) -> ConfigType:
        return self._config_class.from_dict(job_inputs)

    def validate_config(self, job_inputs: dict) -> tuple[bool, list[str]]:
        return self._config_class.validate_dict(job_inputs)

    @property
    def webhook_template(self) -> Optional["HogFunctionTemplateDC"]:
        return None

    def validate_credentials(
        self, config: ConfigType, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        """Check whether the provided credentials are valid for this source. Returns an optional error message"""
        return True, None

    def get_endpoint_permissions(self, config: ConfigType, team_id: int, endpoints: list[str]) -> dict[str, str | None]:
        """Per-endpoint access check. ``{name: None}`` if reachable, ``{name: reason}`` if not. Default = all reachable."""
        return dict.fromkeys(endpoints)

    @property
    def connection_host_fields(self) -> list[str]:
        """``job_inputs`` fields that determine where stored credentials are sent.

        Changing one of these on an existing source must require the editor to re-enter the
        source's secrets — otherwise an org member could retarget the preserved credential at a
        server they control and exfiltrate it. The update serializer enforces this. ``host`` and
        the SSH tunnel target are handled separately, so sources whose connection target lives in
        a differently named field (e.g. Okta's ``okta_domain``) should list it here."""
        return []

    def cleanup_cdc_resources_on_deletion(self, source: "ExternalDataSource") -> None:
        """Best-effort teardown of CDC resources tied to the source. No-op by default."""
        return None


class SimpleSource(_BaseSource[ConfigType], Generic[ConfigType]):
    """Base class for sources with standard pipeline creation."""

    def source_for_pipeline(self, config: ConfigType, inputs: SourceInputs) -> SourceResponse:
        raise NotImplementedError()


class ResumableSource(_BaseSource[ConfigType], Generic[ConfigType, ResumableData]):
    """Base class for sources that support resumable full-refresh imports."""

    def source_for_pipeline(
        self, config: ConfigType, resumable_source_manager: ResumableSourceManager[ResumableData], inputs: SourceInputs
    ) -> SourceResponse:
        raise NotImplementedError()

    @abstractmethod
    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[ResumableData]:
        raise NotImplementedError()


@dataclasses.dataclass
class WebhookCreationResult:
    success: bool
    error: str | None = None
    extra_inputs: dict[str, Any] = dataclasses.field(default_factory=dict)
    # Names of `webhookFields` the user still needs to fill in after creation
    # (e.g. when the source's API doesn't return the signing secret on create).
    # Empty list means the auto-created webhook is fully configured.
    pending_inputs: list[str] = dataclasses.field(default_factory=list)


@dataclasses.dataclass
class WebhookSyncResult:
    """Outcome of reconciling an existing webhook's events — success plus an optional actionable
    message. Distinct from WebhookCreationResult, which also carries create-only fields."""

    success: bool
    error: str | None = None


@dataclasses.dataclass
class WebhookDeletionResult:
    success: bool
    error: str | None = None


@dataclasses.dataclass
class ExternalWebhookInfo:
    """Info about an external webhook on the source (e.g. Stripe webhook endpoint)."""

    exists: bool
    url: str | None = None
    enabled_events: list[str] | None = None
    status: str | None = None
    description: str | None = None
    created_at: str | None = None
    error: str | None = None


class WebhookSource(_BaseSource[ConfigType], Generic[ConfigType]):
    """Base class for sources that support webhook based imports."""

    @property
    @abstractmethod
    def webhook_template(self) -> Optional["HogFunctionTemplateDC"]:
        raise NotImplementedError()

    @abstractmethod
    def get_webhook_source_manager(self, inputs: SourceInputs) -> WebhookSourceManager:
        raise NotImplementedError()

    def create_webhook(self, config: ConfigType, webhook_url: str, team_id: int) -> WebhookCreationResult:
        """Create a webhook on the external source pointing to our webhook_url.

        Returns a WebhookCreationResult. If the source doesn't support automatic
        webhook creation, returns a failed result so the user can set it up manually.
        """
        raise NotImplementedError()

    def get_desired_webhook_events(self, config: ConfigType, eligible_schema_names: list[str]) -> list[str] | None:
        """Events the webhook should subscribe to. ``None`` when the source has no
        provider-side subscription to drift (e.g. Slack); such sources skip reconciliation."""
        return None

    def sync_webhook_events(
        self,
        config: ConfigType,
        webhook_url: str,
        team_id: int,
        eligible_schema_names: list[str],
    ) -> WebhookSyncResult:
        """Reconcile the provider's subscribed events with the selected schemas. No-op default
        for sources without a provider-side subscription; override where one exists (Stripe)."""
        return WebhookSyncResult(success=True)

    def webhook_inputs_updated(
        self, config: ConfigType, webhook_url: str, team_id: int, inputs: dict[str, Any]
    ) -> tuple[bool, str | None]:
        """Called when webhook inputs have been set on the underlying hog function.

        Returns ``(success, error)``. Implementations that need to call out to the
        external service (e.g. enabling a previously-disabled webhook) should return
        ``(False, message)`` on failure so the API view can surface the error to the
        user instead of silently dropping it.
        """
        return True, None

    @property
    @abstractmethod
    def webhook_resource_map(self) -> dict[str, str]:
        """The schema mapping to use to be stored on the HogFunction for matching incoming webhooks with tables.
        In most cases this will likely just be the table name -> table name. But in the case of Stripe, it's the
        table name mapped to the Stripe object type"""
        raise NotImplementedError()

    def get_external_webhook_info(
        self, config: ConfigType, webhook_url: str, team_id: int
    ) -> ExternalWebhookInfo | None:
        """Check the external source for webhook status.

        Returns None if the source doesn't support checking webhook info.
        Sources should override this to query their API (e.g. list Stripe webhook endpoints).
        """
        return None

    def delete_webhook(self, config: ConfigType, webhook_url: str, team_id: int) -> WebhookDeletionResult:
        """Delete the webhook on the external source that matches webhook_url.

        Sources should override this to call their API (e.g. delete Stripe webhook endpoint).
        Returns a WebhookDeletionResult indicating success or failure.
        """
        return WebhookDeletionResult(success=False, error="This source does not support automatic webhook deletion.")


AnySource = SimpleSource[ConfigType] | ResumableSource[ConfigType, ResumableData] | WebhookSource[ConfigType]
