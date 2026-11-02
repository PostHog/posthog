"""Split a source's ``job_inputs`` into connection fields, references, selectors, sync settings and runtime state.

The split is per top-level key. A nested value (``ssh_tunnel``, an ``auth_method`` select, a
switch group) goes with its top-level key as a whole. One exception: a select whose chosen option
holds only an OAuth integration field (``auth_method`` = ``oauth``) is a reference, and any other
chosen option is a connection field. The stored value decides. A key that no form field declares, such as
a legacy flat key, is a connection field: a setting stored with the connection fields still
works when the two halves merge again, but a credential stored with the settings leaks.
"""

import io
import csv
import functools
import dataclasses
from collections.abc import Mapping
from enum import StrEnum
from pathlib import Path
from typing import Any

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.facade.source_config import (
    SourceFieldInputConfig,
    SourceFieldOauthAccountSelectConfig,
    SourceFieldOauthConfig,
    SourceFieldSelectConfig,
    SourceFieldSwitchGroupConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import AnySource, FieldType
from products.warehouse_sources.backend.temporal.data_imports.sources.common.config import META_KEY, MetaConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.credential_kind import (
    compute_credential_kinds,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.types import ExternalDataSourceType

RUNTIME_KEY_PREFIXES: tuple[str, ...] = ("cdc_",)

# The only field types that carry `sync_setting`. OAuth, SSH tunnel and file upload fields always hold credentials.
SYNC_SETTING_FIELD_TYPES = (
    SourceFieldInputConfig,
    SourceFieldSelectConfig,
    SourceFieldSwitchGroupConfig,
    SourceFieldOauthAccountSelectConfig,
)

# The only field types that carry `account_selector`. An `oauth-account-select` field is a selector without the flag.
ACCOUNT_SELECTOR_FLAG_FIELD_TYPES = (
    SourceFieldInputConfig,
    SourceFieldSelectConfig,
    SourceFieldSwitchGroupConfig,
)

SELECT_OPTION_KEY = "selection"

CLASSIFICATION_AUDIT_PATH = Path(__file__).resolve().parents[1] / "field_classification.csv"


class JobInputKind(StrEnum):
    # Typed-in secrets and the details that identify the connection. These move to a credentials row.
    CONNECTION = "connection"
    # A pointer to an existing `Integration` row (`*_integration_id`). The value stays in `job_inputs`.
    REFERENCE = "reference"
    # An account chosen after auth (ad account, property, site). Stays in `job_inputs`, because several
    # sources can share one OAuth row.
    SELECTOR = "selector"
    SETTING = "setting"
    RUNTIME = "runtime"


@frozen
class SplitJobInputs:
    connection: dict[str, Any]
    settings: dict[str, Any]
    runtime: dict[str, Any]
    references: dict[str, Any] = dataclasses.field(default_factory=dict)
    selectors: dict[str, Any] = dataclasses.field(default_factory=dict)

    def __post_init__(self) -> None:
        parts = [self.connection, self.references, self.selectors, self.settings, self.runtime]
        seen: set[str] = set()
        overlap: set[str] = set()
        for part in parts:
            overlap |= seen & part.keys()
            seen |= part.keys()
        if overlap:
            raise ValueError(f"job_inputs keys in more than one part: {sorted(overlap)}")


def reference_option_values(field: FieldType) -> frozenset[str]:
    """Values of the options of a select that hold only OAuth integration fields.

    Choosing such an option makes the whole select value a reference. An option that mixes an OAuth
    field with a typed-in field is not a reference option, because the typed-in value is a credential.
    """
    if not isinstance(field, SourceFieldSelectConfig):
        return frozenset()
    return frozenset(
        option.value
        for option in field.options
        if option.fields and all(isinstance(nested, SourceFieldOauthConfig) for nested in option.fields)
    )


def field_kind(field: FieldType) -> JobInputKind:
    """Kind of a top-level field. A select with reference options is a connection field here and a reference per stored value."""
    if isinstance(field, SYNC_SETTING_FIELD_TYPES) and field.sync_setting:
        return JobInputKind.SETTING
    if isinstance(field, SourceFieldOauthConfig):
        return JobInputKind.REFERENCE
    if isinstance(field, SourceFieldOauthAccountSelectConfig):
        return JobInputKind.SELECTOR
    if isinstance(field, ACCOUNT_SELECTOR_FLAG_FIELD_TYPES) and field.account_selector:
        return JobInputKind.SELECTOR
    return JobInputKind.CONNECTION


def is_runtime_key(source: AnySource, key: str) -> bool:
    return key in source.runtime_job_input_keys or key.startswith(RUNTIME_KEY_PREFIXES)


@functools.cache
def declared_field_kinds(source_type: ExternalDataSourceType) -> Mapping[str, JobInputKind]:
    """Kinds of the source's top-level form fields. The form is static per deploy, so the result is cached."""
    source = SourceRegistry.get_source(source_type)
    return {field.name: field_kind(field) for field in source.get_source_config.fields}


@functools.cache
def declared_reference_options(source_type: ExternalDataSourceType) -> Mapping[str, frozenset[str]]:
    """Top-level selects that have reference options, with the values of those options."""
    source = SourceRegistry.get_source(source_type)
    options = {field.name: reference_option_values(field) for field in source.get_source_config.fields}
    return {name: values for name, values in options.items() if values}


def _stored_aliases(source_type: ExternalDataSourceType) -> dict[str, str]:
    """Map each stored attribute name of an aliased form field to the form field name.

    `serialize_config` stores a parsed config with `dataclasses.asdict`, so a form field whose name is
    not a Python identifier (BigQuery `temporary-dataset`) lands in `job_inputs` under its attribute
    name (`temporary_dataset`).
    """
    source = SourceRegistry.get_source(source_type)
    aliases: dict[str, str] = {}
    for config_field in dataclasses.fields(source._config_class):
        meta: MetaConfig | None = config_field.metadata.get(META_KEY)
        if meta is not None and meta.alias:
            aliases[config_field.name] = meta.alias
    return aliases


@functools.cache
def stored_field_kinds(source_type: ExternalDataSourceType) -> Mapping[str, JobInputKind]:
    """`declared_field_kinds` plus the key each aliased field is stored under. Both spellings get the form field's kind."""
    kinds = dict(declared_field_kinds(source_type))
    for stored_name, alias in _stored_aliases(source_type).items():
        if alias in kinds:
            kinds.setdefault(stored_name, kinds[alias])
    return kinds


@frozen
class ReferenceOptions:
    """The reference option values of a select, and the OAuth keys those options may hold."""

    values: frozenset[str]
    oauth_keys: frozenset[str]


@functools.cache
def stored_reference_options(source_type: ExternalDataSourceType) -> Mapping[str, ReferenceOptions]:
    """For each stored select key with reference options: the option values and the OAuth keys they may hold."""
    source = SourceRegistry.get_source(source_type)
    fields_by_name = {field.name: field for field in source.get_source_config.fields}
    result: dict[str, ReferenceOptions] = {}
    for stored_name, name in [(name, name) for name in fields_by_name] + list(_stored_aliases(source_type).items()):
        field = fields_by_name.get(name)
        values = reference_option_values(field) if field is not None else frozenset()
        if not values or not isinstance(field, SourceFieldSelectConfig):
            continue
        oauth_keys = frozenset(
            nested.name for option in field.options if option.value in values for nested in option.fields or []
        )
        result.setdefault(stored_name, ReferenceOptions(values=values, oauth_keys=oauth_keys))
    return result


def _is_reference_value(source_type: ExternalDataSourceType, key: str, value: Any) -> bool:
    options = stored_reference_options(source_type).get(key)
    if options is None or not isinstance(value, Mapping):
        return False
    if value.get(SELECT_OPTION_KEY) not in options.values:
        return False
    # `serialize_config` keeps the inactive options' fields as empty values, so an empty stray key is
    # fine. A populated one may be a credential, so the whole value stays a connection field.
    stray_keys = value.keys() - options.oauth_keys - {SELECT_OPTION_KEY}
    return all(value[key] in (None, "") for key in stray_keys)


def classify_job_input_key(source_type: ExternalDataSourceType, key: str, value: Any = None) -> JobInputKind:
    """Kind of a stored key. Pass the stored value to classify a select that has reference options."""
    if is_runtime_key(SourceRegistry.get_source(source_type), key):
        return JobInputKind.RUNTIME
    if _is_reference_value(source_type, key, value):
        return JobInputKind.REFERENCE
    return stored_field_kinds(source_type).get(key, JobInputKind.CONNECTION)


def split_job_inputs(source_type: ExternalDataSourceType, job_inputs: Mapping[str, Any] | None) -> SplitJobInputs:
    parts: dict[JobInputKind, dict[str, Any]] = {kind: {} for kind in JobInputKind}
    for key, value in (job_inputs or {}).items():
        parts[classify_job_input_key(source_type, key, value)][key] = value
    return SplitJobInputs(
        connection=parts[JobInputKind.CONNECTION],
        references=parts[JobInputKind.REFERENCE],
        selectors=parts[JobInputKind.SELECTOR],
        settings=parts[JobInputKind.SETTING],
        runtime=parts[JobInputKind.RUNTIME],
    )


def merge_job_inputs(split: SplitJobInputs) -> dict[str, Any]:
    return {**split.connection, **split.references, **split.selectors, **split.settings, **split.runtime}


def render_classification_audit() -> str:
    """A CSV of every registered source's top-level field kinds, for reviewers.

    Cells list field names separated by spaces. A select that has reference options appears in the
    connection column, and in the reference column as `name=option`: its stored value decides. Keys
    that start with a `RUNTIME_KEY_PREFIXES` entry are runtime state for every source, so the runtime
    column lists only the keys a source adds.
    """
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(
        [
            "source_type",
            "connection_fields",
            "reference_fields",
            "selector_fields",
            "sync_settings",
            "runtime_keys",
            "credential_kind",
        ]
    )
    sources = SourceRegistry.get_all_sources()
    credential_kinds = compute_credential_kinds()
    for source_type in sorted(sources, key=lambda source_type: source_type.value):
        kinds = declared_field_kinds(source_type)
        reference_fields = [name for name, kind in kinds.items() if kind == JobInputKind.REFERENCE]
        reference_fields += [
            f"{name}={value}"
            for name, values in declared_reference_options(source_type).items()
            for value in sorted(values)
        ]
        writer.writerow(
            [
                source_type.value,
                " ".join(name for name, kind in kinds.items() if kind == JobInputKind.CONNECTION),
                " ".join(reference_fields),
                " ".join(name for name, kind in kinds.items() if kind == JobInputKind.SELECTOR),
                " ".join(name for name, kind in kinds.items() if kind == JobInputKind.SETTING),
                " ".join(sorted(sources[source_type].runtime_job_input_keys)),
                credential_kinds.get(source_type.value, ""),
            ]
        )
    return output.getvalue()
