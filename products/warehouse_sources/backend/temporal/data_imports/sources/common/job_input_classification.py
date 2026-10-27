"""Split a source's ``job_inputs`` into connection fields, sync settings and runtime state.

The split is per top-level key. A nested value (``ssh_tunnel``, an ``auth_method`` select, a
switch group) goes with its top-level key as a whole. A key that no form field declares, such as
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
    SourceFieldSelectConfig,
    SourceFieldSwitchGroupConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import AnySource, FieldType
from products.warehouse_sources.backend.temporal.data_imports.sources.common.config import META_KEY, MetaConfig
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

CLASSIFICATION_AUDIT_PATH = Path(__file__).resolve().parents[1] / "field_classification.csv"


class JobInputKind(StrEnum):
    CONNECTION = "connection"
    SETTING = "setting"
    RUNTIME = "runtime"


@frozen
class SplitJobInputs:
    connection: dict[str, Any]
    settings: dict[str, Any]
    runtime: dict[str, Any]

    def __post_init__(self) -> None:
        overlap = (
            (self.connection.keys() & self.settings.keys())
            | (self.connection.keys() & self.runtime.keys())
            | (self.settings.keys() & self.runtime.keys())
        )
        if overlap:
            raise ValueError(f"job_inputs keys in more than one part: {sorted(overlap)}")


def field_kind(field: FieldType) -> JobInputKind:
    if isinstance(field, SYNC_SETTING_FIELD_TYPES) and field.sync_setting:
        return JobInputKind.SETTING
    return JobInputKind.CONNECTION


def is_runtime_key(source: AnySource, key: str) -> bool:
    return key in source.runtime_job_input_keys or key.startswith(RUNTIME_KEY_PREFIXES)


@functools.cache
def declared_field_kinds(source_type: ExternalDataSourceType) -> Mapping[str, JobInputKind]:
    """Kinds of the source's top-level form fields. The form is static per deploy, so the result is cached."""
    source = SourceRegistry.get_source(source_type)
    return {field.name: field_kind(field) for field in source.get_source_config.fields}


@functools.cache
def stored_field_kinds(source_type: ExternalDataSourceType) -> Mapping[str, JobInputKind]:
    """`declared_field_kinds` plus the key each aliased field is stored under.

    `serialize_config` stores a parsed config with `dataclasses.asdict`, so a form field whose name is
    not a Python identifier (BigQuery `temporary-dataset`) lands in `job_inputs` under its attribute
    name (`temporary_dataset`). Both spellings get the form field's kind.
    """
    source = SourceRegistry.get_source(source_type)
    kinds = dict(declared_field_kinds(source_type))
    for config_field in dataclasses.fields(source._config_class):
        meta: MetaConfig | None = config_field.metadata.get(META_KEY)
        if meta is not None and meta.alias in kinds:
            kinds.setdefault(config_field.name, kinds[meta.alias])
    return kinds


def classify_job_input_key(source_type: ExternalDataSourceType, key: str) -> JobInputKind:
    if is_runtime_key(SourceRegistry.get_source(source_type), key):
        return JobInputKind.RUNTIME
    return stored_field_kinds(source_type).get(key, JobInputKind.CONNECTION)


def split_job_inputs(source_type: ExternalDataSourceType, job_inputs: Mapping[str, Any] | None) -> SplitJobInputs:
    parts: dict[JobInputKind, dict[str, Any]] = {kind: {} for kind in JobInputKind}
    for key, value in (job_inputs or {}).items():
        parts[classify_job_input_key(source_type, key)][key] = value
    return SplitJobInputs(
        connection=parts[JobInputKind.CONNECTION],
        settings=parts[JobInputKind.SETTING],
        runtime=parts[JobInputKind.RUNTIME],
    )


def merge_job_inputs(split: SplitJobInputs) -> dict[str, Any]:
    return {**split.connection, **split.settings, **split.runtime}


def render_classification_audit() -> str:
    """A CSV of every registered source's top-level field kinds, for reviewers.

    Cells list field names separated by spaces. Keys that start with a `RUNTIME_KEY_PREFIXES` entry are
    runtime state for every source, so the runtime column lists only the keys a source adds.
    """
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(["source_type", "connection_fields", "sync_settings", "runtime_keys"])
    sources = SourceRegistry.get_all_sources()
    for source_type in sorted(sources, key=lambda source_type: source_type.value):
        kinds = declared_field_kinds(source_type)
        writer.writerow(
            [
                source_type.value,
                " ".join(name for name, kind in kinds.items() if kind == JobInputKind.CONNECTION),
                " ".join(name for name, kind in kinds.items() if kind == JobInputKind.SETTING),
                " ".join(sorted(sources[source_type].runtime_job_input_keys)),
            ]
        )
    return output.getvalue()
