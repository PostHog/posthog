"""Helpers for external data source API requests."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from django.db.models import Q, QuerySet

from posthog.schema import (
    SourceFieldFileUploadConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldOauthAccountSelectConfig,
    SourceFieldOauthConfig,
    SourceFieldSelectConfig,
    SourceFieldSSHTunnelConfig,
    SourceFieldSwitchGroupConfig,
)

from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception

from products.data_warehouse.backend.facade.api import (
    DirectQueryEngine,
    apply_on_refresh as apply_sql_warehouse_refresh_migration,
    get_postgres_source_location,
    is_multi_schema_capable_sql_source,
    source_namespace_is_blank,
)
from products.warehouse_sources.backend.facade.models import MANAGED_WAREHOUSE_SOURCE_PREFIX, ExternalDataSource
from products.warehouse_sources.backend.facade.source_management import (
    AnySource,
    Config,
    FieldType,
    SourceSchema,
    source_requires_ssl,
)
from products.warehouse_sources.backend.facade.types import ManagedWarehouseSQLMode

REFRESH_SCHEMAS_FALLBACK_ERROR_MESSAGE = "Could not fetch schemas from source."

RESERVED_SOURCE_NAME_MESSAGE = "This source name is reserved by PostHog."

INVALID_CREDENTIALS_FALLBACK_MESSAGE = (
    "We couldn't validate those credentials. Check they're correct and have the required access, then try again."
)


def _source_unavailable_message(source_type: str) -> str:
    # A source with no schema discovery is an unreleased scaffold the UI normally hides. Tell the
    # user it isn't ready rather than exposing the internal "schema discovery" wording.
    return (
        f"The {source_type} source isn't available to connect yet. "
        "Choose a different source, or contact support if you were expecting it."
    )


def _canonical_legacy_managed_warehouse_source(
    queryset: QuerySet[ExternalDataSource],
) -> ExternalDataSource | None:
    candidates = (
        queryset.select_related(None)
        .filter(ExternalDataSource.legacy_managed_warehouse_q())
        .only(
            "id",
            "team_id",
            "created_at",
            "prefix",
            "connection_metadata",
            "source_type",
            "access_method",
            "direct_query_enabled",
            "job_inputs",
        )
        .order_by("-created_at")
    )
    return next(
        (source for source in candidates if source.managed_warehouse_sql_mode == ManagedWarehouseSQLMode.EXTERNAL),
        None,
    )


def _hide_noncanonical_managed_warehouse_sources(
    queryset: QuerySet[ExternalDataSource], canonical_source: ExternalDataSource | None
) -> QuerySet[ExternalDataSource]:
    hidden_sources = Q(prefix=MANAGED_WAREHOUSE_SOURCE_PREFIX)
    if canonical_source is not None:
        hidden_sources &= ~Q(pk=canonical_source.pk)
    return queryset.exclude(hidden_sources)


REFRESH_SCHEMAS_EXPECTED_ERROR_MESSAGES = {
    "timeout": "Connection timed out while fetching schemas from the source.",
    "timed out": "Connection timed out while fetching schemas from the source.",
    "connection refused": "Could not connect to the source. Check the host, port, and network access.",
    "could not connect": "Could not connect to the source. Check the host, port, and network access.",
    "could not translate host name": "Could not resolve the source host.",
    "name or service not known": "Could not resolve the source host.",
    "network is unreachable": "Could not reach the source network.",
    "no route to host": "Could not reach the source host.",
    "access denied": "Could not authenticate with the source. Check the connection credentials.",
    "authentication failed": "Could not authenticate with the source. Check the connection credentials.",
    "password authentication failed": "Could not authenticate with the source. Check the connection credentials.",
    "unauthorized": "Could not authenticate with the source. Check the connection credentials.",
    "forbidden": "The source credentials do not have permission to fetch schemas.",
    "ssl/tls connection is required": "SSL/TLS is required to connect to the source.",
    "could not establish session to ssh gateway": "Could not establish an SSH tunnel to the source.",
}


def _exception_text(error: Exception) -> str:
    message = " ".join(str(arg) for arg in error.args if arg is not None) or str(error)
    return f"{type(error).__name__}: {message}"


def _classify_refresh_schemas_error(source: AnySource | None, error: Exception) -> tuple[str, bool]:
    error_text = _exception_text(error)
    normalized_error_text = error_text.lower()
    matched_source_error = False

    if source is not None:
        for pattern, friendly_message in source.get_non_retryable_errors().items():
            if pattern and pattern.lower() in normalized_error_text:
                if friendly_message:
                    return friendly_message, True
                matched_source_error = True

    for pattern, friendly_message in REFRESH_SCHEMAS_EXPECTED_ERROR_MESSAGES.items():
        if pattern in normalized_error_text:
            return friendly_message, True

    if matched_source_error:
        return REFRESH_SCHEMAS_FALLBACK_ERROR_MESSAGE, True

    return REFRESH_SCHEMAS_FALLBACK_ERROR_MESSAGE, False


def _credentials_validation_failed(source: AnySource, team_id: int, error: Exception) -> tuple[bool, str | None]:
    """Fallback result for an *unexpected* exception raised by a source's credential probe.

    Sources are expected to catch their own errors and return ``(False, message)``. One that raises
    instead would 500 the create/update request and show someone mid-onboarding an opaque server
    error, so capture it for us and hand back an actionable message — the same treatment schema
    discovery already gives an unexpected error just below the credential check."""
    capture_exception(error, {"source_type": str(source.source_type), "team_id": team_id})
    return False, INVALID_CREDENTIALS_FALLBACK_MESSAGE


def get_sensitive_field_names(fields: list[FieldType]) -> set[str]:
    """Extract field names that contain sensitive data from a source config's fields."""
    sensitive: set[str] = set()
    for field in fields:
        if isinstance(field, SourceFieldInputConfig) and (
            field.type == SourceFieldInputConfigType.PASSWORD or field.secret
        ):
            sensitive.add(field.name)
        elif isinstance(field, SourceFieldFileUploadConfig):
            sensitive.add(field.name)
        elif isinstance(field, SourceFieldSwitchGroupConfig):
            sensitive.update(get_sensitive_field_names(field.fields))
        elif isinstance(field, SourceFieldSelectConfig):
            for option in field.options:
                if option.fields:
                    sensitive.update(get_sensitive_field_names(option.fields))
    return sensitive


def get_oauth_integration_kinds(fields: list[FieldType]) -> set[str]:
    """The integration kinds a source connects with, declared by its `oauth` fields (`kind`) and its
    `oauth-account-select` fields (`integrationKind`). Every OAuth account listing is served by one
    endpoint that takes an integration id from the caller, so this is what the endpoint checks that id
    against — a Google integration id must not be able to route its token into the LinkedIn Ads client
    just because both rows belong to the caller's team.

    Both field types are read because a source can list accounts without rendering a picker: GitHub
    serves repositories to its own component off a plain `oauth` field."""
    kinds: set[str] = set()
    for field in fields:
        if isinstance(field, SourceFieldOauthAccountSelectConfig):
            kinds.add(field.integrationKind)
        elif isinstance(field, SourceFieldOauthConfig):
            kinds.add(field.kind)
        elif isinstance(field, SourceFieldSwitchGroupConfig):
            kinds.update(get_oauth_integration_kinds(field.fields))
        elif isinstance(field, SourceFieldSelectConfig):
            for option in field.options:
                if option.fields:
                    kinds.update(get_oauth_integration_kinds(option.fields))
    return kinds


def _name_variants(name: str) -> tuple[str, ...]:
    """The spellings a declared field name can be stored under, declared spelling first.

    Source field names may use hyphens (e.g. "temporary-dataset") while
    dataclasses.asdict() persists the snake_case field name ("temporary_dataset").
    """
    normalised = name.replace("-", "_")
    return (name,) if normalised == name else (name, normalised)


def _add_name_variants(target: set[str], name: str) -> None:
    """Add a field name and its underscore variant to a set.

    We need to recognise both forms when classifying persisted job_inputs.
    """
    target.update(_name_variants(name))


def _stored_key(data: Mapping[str, Any], name: str) -> str | None:
    """The key `data` holds a declared field under, or None when it holds neither spelling.

    Prefers the declared spelling when both are present, matching how config parsing
    resolves the alias.
    """
    return next((key for key in _name_variants(name) if key in data), None)


def _stored_value(data: Mapping[str, Any], name: str) -> Any:
    """The value `data` holds for a declared field under either spelling."""
    key = _stored_key(data, name)
    return data[key] if key is not None else None


@frozen
class DeclaredFieldNames:
    """Declared field names that need special handling when reading or merging job_inputs.

    `hyphenated` are names the source declares with a hyphen. `dataclasses.asdict()` persists
    the Python attribute name instead, so stored configs can hold either spelling.
    `switch_groups` are switch-group container names, whose stored value is a nested dict.
    """

    hyphenated: set[str]
    switch_groups: set[str]


def get_declared_field_names(fields: list[FieldType]) -> DeclaredFieldNames:
    """Collect hyphenated and switch-group field names, flattened across all nesting levels."""
    hyphenated: set[str] = set()
    switch_groups: set[str] = set()

    for field in fields:
        if "-" in field.name:
            hyphenated.add(field.name)
        if isinstance(field, SourceFieldSwitchGroupConfig):
            switch_groups.add(field.name)
            nested = get_declared_field_names(field.fields)
            hyphenated.update(nested.hyphenated)
            switch_groups.update(nested.switch_groups)
        elif isinstance(field, SourceFieldSelectConfig):
            for option in field.options:
                if option.fields:
                    nested = get_declared_field_names(option.fields)
                    hyphenated.update(nested.hyphenated)
                    switch_groups.update(nested.switch_groups)

    return DeclaredFieldNames(hyphenated=hyphenated, switch_groups=switch_groups)


def restore_declared_field_names(data: dict, hyphenated: set[str]) -> dict:
    """Return a copy of data re-keyed to the names the source config declares.

    A hyphenated field round-trips through `dataclasses.asdict()`, which writes the Python
    attribute name ("temporary_dataset") rather than the declared one ("temporary-dataset").
    Clients key off the declared name, so restore it. When both spellings are present the
    declared one wins, matching how config parsing prefers the alias.
    """
    if not hyphenated:
        return data

    variants = {name.replace("-", "_"): name for name in hyphenated}
    result: dict = {}
    for key, value in data.items():
        declared = variants.get(key)
        if declared is not None:
            if declared in data:
                continue
            key = declared
        if isinstance(value, dict):
            value = restore_declared_field_names(value, hyphenated)
        result[key] = value
    return result


@frozen
class FieldSensitivitySplit:
    nonsensitive: set[str]
    sensitive: set[str]


def get_nonsensitive_and_sensitive_field_names(fields: list[FieldType]) -> FieldSensitivitySplit:
    """Classify source config field names as nonsensitive or sensitive.

    Returns the field-name sets flattened across all nesting levels.
    """
    nonsensitive: set[str] = set()
    sensitive: set[str] = set()

    for field in fields:
        if isinstance(field, SourceFieldInputConfig):
            if field.type == SourceFieldInputConfigType.PASSWORD or field.secret:
                _add_name_variants(sensitive, field.name)
            else:
                _add_name_variants(nonsensitive, field.name)
        elif isinstance(field, SourceFieldFileUploadConfig):
            _add_name_variants(sensitive, field.name)
        elif isinstance(field, SourceFieldSelectConfig):
            _add_name_variants(nonsensitive, field.name)
            for option in field.options:
                if option.fields:
                    nested = get_nonsensitive_and_sensitive_field_names(option.fields)
                    nonsensitive.update(nested.nonsensitive)
                    sensitive.update(nested.sensitive)
        elif isinstance(field, SourceFieldSwitchGroupConfig):
            _add_name_variants(nonsensitive, field.name)
            nested = get_nonsensitive_and_sensitive_field_names(field.fields)
            nonsensitive.update(nested.nonsensitive)
            sensitive.update(nested.sensitive)
        elif isinstance(field, SourceFieldOauthConfig | SourceFieldOauthAccountSelectConfig):
            # The selected account/property is a plain identifier (e.g. Bing Ads account_id,
            # GSC site_url), not a secret — keep it so the form can prefill on edit.
            _add_name_variants(nonsensitive, field.name)
        elif isinstance(field, SourceFieldSSHTunnelConfig):
            _add_name_variants(nonsensitive, field.name)
            # SSH tunnel has a known nested structure not declared in the field tree.
            # "auth"/"auth_type" are container keys for SSHTunnelAuthConfig.
            nonsensitive.update({"host", "port", "username", "auth", "auth_type", "require_tls"})
            sensitive.update({"password", "passphrase", "private_key"})

    return FieldSensitivitySplit(nonsensitive=nonsensitive, sensitive=sensitive)


# Config metadata keys that are always safe to include in nested dicts
_CONFIG_META_KEYS = {"selection", "enabled"}

# CDC config lives in job_inputs but isn't part of any source's user-facing form field
# tree, so it would otherwise be stripped from API reads as "unknown". None of these are
# secrets — they're operational config the Configuration page needs to render CDC state.
_CDC_EXPOSED_JOB_INPUT_KEYS = {
    "cdc_enabled",
    "cdc_management_mode",
    "cdc_slot_name",
    "cdc_publication_name",
    "cdc_auto_drop_slot",
    "cdc_lag_warning_threshold_mb",
    "cdc_lag_critical_threshold_mb",
    "cdc_consistent_point",
    # Set by migrate_cdc_source_to_buffered, never by the API. Losing it on an unrelated PATCH
    # would resume legacy delivery from an advanced slot and strand the unread buffer.
    "cdc_ingest_mode",
}


def strip_sensitive_from_dict(data: dict, nonsensitive: set[str], sensitive: set[str]) -> dict:
    """Return a copy of data with sensitive and unknown keys removed.

    Keys in the nonsensitive set or config metadata keys are kept.
    Keys in the sensitive set or not in any known set are stripped.
    Nested dicts are processed recursively.
    """
    result: dict = {}
    for key, value in data.items():
        if key in sensitive:
            continue
        if key not in nonsensitive and key not in _CONFIG_META_KEYS:
            continue
        if isinstance(value, dict):
            result[key] = strip_sensitive_from_dict(value, nonsensitive, sensitive)
        else:
            result[key] = value
    return result


# Fields whose change could redirect the database connection to a different server
# (and therefore exfiltrate credentials via a poisoned SSH tunnel — VERIA-311).
_SSH_TUNNEL_CONNECTION_FIELDS = ("enabled", "host", "port")

# Top-level job_input fields that name the connection target. Changing any of them
# repoints the source at a different server, so preserved credentials must not be
# reused without re-entry (e.g. ServiceNow's `instance_url` could otherwise be swapped
# to an attacker host that then receives the stored API key / password — VERIA-311).
_CONNECTION_TARGET_FIELDS = ("host", "instance_url")


def ssh_tunnel_connection_changed(existing: Any, incoming: Any) -> bool:
    """True if the SSH tunnel's connection target (enabled/host/port) changed.

    Scalars are coerced to strings to ignore type drift between stored values
    (often strings) and JSON-parsed input (bools/ints). Only `None` collapses to ""
    — `or ""` would also swallow falsy-but-meaningful values like `False` and 0,
    making stored "False" falsely diverge from JSON `false`.
    """
    existing = existing if isinstance(existing, dict) else {}
    incoming = incoming if isinstance(incoming, dict) else {}

    def _coerce(value: Any) -> str:
        return "" if value is None else str(value)

    return any(_coerce(existing.get(key)) != _coerce(incoming.get(key)) for key in _SSH_TUNNEL_CONNECTION_FIELDS)


# Nested containers that keep their secrets one level down, not at the top level: the
# SourceFieldSelectConfig ones (Stripe `auth_method`, Snowflake `auth_type`, ServiceNow
# `auth_method`) key their selected branch as `selection`; the SourceFieldSwitchGroupConfig
# one (Billomat's `registered_app`) keys it as `enabled` instead, but the same carried-over-
# secret check below applies either way.
_NESTED_AUTH_CONTAINERS = ("auth_method", "auth_type", "registered_app")

# Secrets the edit form can never re-supply (parsed into the individual fields on create, then
# stripped from API reads and hidden in the edit form), so gating credential re-entry on them would
# permanently block host changes. Excluded from the gate but still preserved by the merge: MongoDB
# connects via `connection_string`, while SQL sources use the individual fields and gate `password`.
_CREATION_ONLY_SECRET_FIELDS = frozenset({"connection_string"})


def has_preserved_credentials(
    existing: dict[str, Any],
    incoming: dict[str, Any],
    sensitive_fields: set[str],
    nested_containers: Iterable[str] = _NESTED_AUTH_CONTAINERS,
) -> bool:
    """True if any stored secret would be reused because the update didn't re-supply it.

    Checks both top-level secret fields and the nested containers where sources like
    ServiceNow, Stripe and Snowflake keep their credentials. Used to force credential
    re-entry when the connection target changes, so a redirected host can't receive a
    preserved secret. A secret only counts as preserved when it would survive the merge:
    an absent container carries the whole existing block over, a same-selection container
    preserves any field the update omits, and a selection switch replaces the block wholesale.

    Switch groups merge the same way, so callers pass their names too. A switch group carries
    no `selection`, which reads as unchanged and lands on the omitted-field check — the branch
    that matches how the merge treats them. A group declared with a hyphen can be stored under
    either spelling, so containers are resolved the same way the merge resolves them.
    """
    if any(existing.get(key) and not incoming.get(key) for key in sensitive_fields):
        return True

    for container_key in nested_containers:
        existing_container = _stored_value(existing, container_key)
        if not isinstance(existing_container, dict):
            continue
        incoming_container = _stored_value(incoming, container_key)
        if not isinstance(incoming_container, dict):
            # Container not re-supplied — the existing secrets carry over wholesale.
            if any(existing_container.get(key) for key in sensitive_fields):
                return True
            continue
        if existing_container.get("selection") != incoming_container.get("selection"):
            continue
        if any(existing_container.get(key) and not incoming_container.get(key) for key in sensitive_fields):
            return True

    return False


def get_direct_connection_metadata(
    *,
    source_impl: Any,
    source_config: Config,
    team_id: int,
    source_model: ExternalDataSource | None = None,
    fallback: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metadata_fetcher = getattr(source_impl, "get_connection_metadata", None)
    if not callable(metadata_fetcher):
        return fallback or {}

    require_ssl = source_model is not None and source_requires_ssl(source_model, source_config)

    try:
        metadata = metadata_fetcher(source_config, team_id, require_ssl=require_ssl)
    except Exception as error:
        # Connection metadata is best-effort — we fall back below regardless. An expected
        # user/upstream connection failure (unreachable or misconfigured host, refused connection,
        # bad credentials) is the customer's to fix and is already surfaced by credential
        # validation, so don't capture it as error-tracking noise. Mirrors `refresh_schemas`.
        _, is_expected_source_error = _classify_refresh_schemas_error(source_impl, error)
        if not is_expected_source_error:
            capture_exception(error)
        return fallback or {}

    return metadata if isinstance(metadata, dict) else (fallback or {})


def get_postgres_source_table_location(
    *,
    schema_name: str,
    source_schema: SourceSchema | None,
    default_schema: str | None,
) -> tuple[str | None, str, str]:  # nosemgrep: tuple-return-prefer-dataclass -- grandfathered backlog
    return get_postgres_source_location(
        schema_name=schema_name,
        schema_metadata={
            "source_catalog": source_schema.source_catalog if source_schema else None,
            "source_schema": source_schema.source_schema if source_schema else None,
            "source_table_name": source_schema.source_table_name if source_schema else None,
        },
        default_schema=default_schema,
    )


DIRECT_QUERY_UNSUPPORTED_SOURCE_MESSAGE = "Direct query mode is currently supported only for Postgres, MySQL, Snowflake, Redshift, ClickHouse, MotherDuck, and Trino sources."

# Engines surfaced on a direct connection's `connection_metadata.engine` (duckdb backs direct Postgres).
DIRECT_CONNECTION_ENGINE_CHOICES = [
    "duckdb",
    "postgres",
    "mysql",
    "snowflake",
    "redshift",
    "clickhouse",
    "motherduck",
    "trino",
]


def count_active_sources(team_id: int, source_type: str) -> int:
    return ExternalDataSource.objects.filter(team_id=team_id, source_type=source_type).exclude(deleted=True).count()


def _refresh_name_substitutions(
    engine: DirectQueryEngine | None, *, source: ExternalDataSource, source_schemas: list[Any], team_id: int
) -> dict[str, str]:
    """Legacy-row name remapping applied before schema sync on refresh. The engine adapter's
    remapping wins when it has one (Postgres's bespoke dedup — an empty dict still counts as
    "handled" and suppresses the fallback); otherwise a multi-schema-capable SQL source with a
    blank namespace gets the generic migration. Neither applies to any other source."""
    if engine is not None:
        engine_subs = engine.refresh_name_substitutions(source=source, source_schemas=source_schemas, team_id=team_id)
        if engine_subs is not None:
            return engine_subs
    if source_namespace_is_blank(source) and is_multi_schema_capable_sql_source(source.source_type):
        return apply_sql_warehouse_refresh_migration(source=source, team_id=team_id)
    return {}
