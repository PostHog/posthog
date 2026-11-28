"""Which stored source and integration values are secrets, and masking them in error messages.

Lives outside the presentation layer so the facade can mask errors it hands to other products.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING, Any
from urllib.parse import unquote, urlsplit

from posthog.dataclasses import frozen
from posthog.integrations.secret_reads import UndecryptedIntegrationSecretError, looks_encrypted

from products.warehouse_sources.backend.facade.contracts import UnreadableSourceInputsError
from products.warehouse_sources.backend.facade.source_config import (
    SourceFieldFileUploadConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldOauthAccountSelectConfig,
    SourceFieldOauthConfig,
    SourceFieldSelectConfig,
    SourceFieldSSHTunnelConfig,
    SourceFieldSwitchGroupConfig,
)
from products.warehouse_sources.backend.logic.source_inputs import SourceInputsStore

if TYPE_CHECKING:
    from uuid import UUID

    from posthog.integrations import IntegrationRecord

    from products.warehouse_sources.backend.facade.source_management import FieldType
    from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource


def field_name_variants(name: str) -> tuple[str, ...]:
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
    target.update(field_name_variants(name))


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
            nonsensitive.update({"host", "port", "username", "auth", "auth_type", "require_tls", "host_key"})
            sensitive.update({"password", "passphrase", "private_key"})

    return FieldSensitivitySplit(nonsensitive=nonsensitive, sensitive=sensitive)


def get_sensitive_field_names(fields: list[FieldType]) -> set[str]:
    """Extract field names that contain sensitive data from a source config's fields."""
    return get_nonsensitive_and_sensitive_field_names(fields).sensitive


REDACTED_VALUE = "***"

# Shorter stored values (e.g. a port or a boolean flag) would match unrelated parts of an error message.
_MIN_REDACTED_SECRET_LENGTH = 4

# Matches job_input keys that hold secrets even when a source config does not declare them.
_SECRET_KEY_NAME_PATTERN = re.compile(
    r"pass(word|wd|phrase)?|secret|token|api[_-]?key|private[_-]?key|credential|connection[_-]?string",
    re.IGNORECASE,
)

_SECRET_PARAM_NAMES = (
    r"api[_-]?key|apikey|access[_-]?key|secret[_-]?key|client[_-]?secret|secret|access[_-]?token|"
    r"refresh[_-]?token|auth[_-]?token|token|password|passwd|pwd|signature|sig|key"
)

_ERROR_REDACTION_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # Password in URL userinfo: postgres://user:secret@host
    (re.compile(r"(\b[a-z][a-z0-9+.-]{0,31}://[^\s:/@?#]+:)[^\s/?#@]+@", re.IGNORECASE), rf"\1{REDACTED_VALUE}@"),
    # Query string or key=value pairs: ?api_key=secret, password=secret
    (
        re.compile(rf"((?<![a-z0-9_])(?:{_SECRET_PARAM_NAMES})=)[^\s&;,'\"]+", re.IGNORECASE),
        rf"\1{REDACTED_VALUE}",
    ),
    # JSON-like pairs: "password": "secret"
    (
        re.compile(rf"(['\"](?:{_SECRET_PARAM_NAMES})['\"]\s*:\s*['\"])[^'\"]*", re.IGNORECASE),
        rf"\1{REDACTED_VALUE}",
    ),
    # Authorization header values: Bearer abc.def, Basic dXNlcjpwYXNz
    (re.compile(r"\b(Bearer|Basic|Token)\s+[a-z0-9._~+/=-]{8,}", re.IGNORECASE), rf"\1 {REDACTED_VALUE}"),
)


def _collect_string_leaves(value: Any, into: set[str]) -> None:
    if isinstance(value, str):
        into.add(value)
        url_password = _url_password(value)
        if url_password:
            into.add(url_password)
    elif isinstance(value, Mapping):
        for nested in value.values():
            _collect_string_leaves(nested, into)
    elif isinstance(value, list | tuple):
        for nested in value:
            _collect_string_leaves(nested, into)


def _url_password(value: str) -> str | None:
    if "://" not in value:
        return None
    try:
        password = urlsplit(value).password
    except ValueError:
        return None
    return unquote(password) if password else None


def _collect_secret_values(data: Any, sensitive: set[str], into: set[str]) -> None:
    if isinstance(data, Mapping):
        for key, value in data.items():
            if isinstance(key, str) and (key in sensitive or _SECRET_KEY_NAME_PATTERN.search(key)):
                _collect_string_leaves(value, into)
            else:
                _collect_secret_values(value, sensitive, into)
    elif isinstance(data, list | tuple):
        for nested in data:
            _collect_secret_values(nested, sensitive, into)


def source_secret_values(source_type: str, job_inputs: Mapping[str, Any]) -> frozenset[str]:
    """The stored secret values in a source's inputs, to mask wherever they appear in its error messages."""
    # The registry loads source modules, so keep it off this module's import path.
    from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import (  # noqa: PLC0415
        SourceRegistry,
    )

    try:
        source_config = SourceRegistry.get_source(source_type).get_source_config
        sensitive = get_sensitive_field_names(source_config.fields)
    except (ValueError, KeyError):
        sensitive = set()
    values: set[str] = set()
    _collect_secret_values(job_inputs, sensitive, values)
    return frozenset(value for value in values if len(value) >= _MIN_REDACTED_SECRET_LENGTH)


def source_secret_values_by_source(sources: Iterable[ExternalDataSource]) -> dict[UUID, frozenset[str]]:
    """The stored secret values of each source, read with one inputs query for all of them.

    A source whose inputs can't be read is left out, since its errors can't be masked.
    """
    sources = list(sources)
    inputs = SourceInputsStore.load_many(sources)
    secrets: dict[UUID, frozenset[str]] = {}
    for source in sources:
        if source.id not in inputs:
            # `load_many` also drops a source when its credentials read fails; `load` raises that instead.
            try:
                inputs[source.id] = SourceInputsStore.load(source)
            except UnreadableSourceInputsError:
                continue
        secrets[source.id] = source_secret_values(source.source_type, inputs[source.id])
    return secrets


def get_integration_error_redaction_values(integration: IntegrationRecord | None) -> frozenset[str]:
    """The secret values of a destination's integration, to mask wherever they appear in its delivery errors.

    Every value in `sensitive_config` is a secret, so each one is masked whatever its length. In `config`,
    only keys named like a secret are, and short values there are left alone like a source's.

    Raises `UndecryptedIntegrationSecretError` when a secret cannot be read, so it cannot be masked.
    """
    if integration is None:
        return frozenset()
    sensitive: set[str] = set()
    _collect_string_leaves(integration.sensitive_config, sensitive)
    # The Django backend gives back a secret that no key can decrypt as its ciphertext, without raising.
    if any(looks_encrypted(value) for value in sensitive):
        raise UndecryptedIntegrationSecretError()
    named_like_secret: set[str] = set()
    _collect_secret_values(integration.config, set(), named_like_secret)
    return frozenset(value for value in sensitive if value) | frozenset(
        value for value in named_like_secret if len(value) >= _MIN_REDACTED_SECRET_LENGTH
    )


def redact_error_message(message: str | None, secret_values: Iterable[str]) -> str | None:
    """Mask credentials in a sync error message before an API response returns it.

    Source errors often embed the failed request URL, a connection string or a raw driver message,
    so the source's own stored secrets and common credential patterns are both masked.
    """
    if not message:
        return message
    # Replace longer values first, so a secret that contains a shorter one is masked whole.
    for value in sorted(secret_values, key=len, reverse=True):
        message = message.replace(value, REDACTED_VALUE)
    for pattern, replacement in _ERROR_REDACTION_PATTERNS:
        message = pattern.sub(replacement, message)
    return message
