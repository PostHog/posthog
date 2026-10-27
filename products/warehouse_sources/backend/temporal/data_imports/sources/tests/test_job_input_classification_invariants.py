from collections.abc import Iterator

import pytest

import products.warehouse_sources.backend.temporal.data_imports.sources._load_all  # noqa: F401
from products.warehouse_sources.backend.facade.source_config import (
    SourceFieldFileUploadConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldOauthConfig,
    SourceFieldSelectConfig,
    SourceFieldSSHTunnelConfig,
    SourceFieldSwitchGroupConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType
from products.warehouse_sources.backend.temporal.data_imports.sources.common.job_input_classification import (
    CLASSIFICATION_AUDIT_PATH,
    SYNC_SETTING_FIELD_TYPES,
    JobInputKind,
    declared_field_kinds,
    field_kind,
    is_runtime_key,
    render_classification_audit,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry

ALL_SOURCES = SourceRegistry.get_all_sources()
SOURCE_TYPES = sorted(ALL_SOURCES.keys(), key=str)


def _nested_fields(field: FieldType) -> list[FieldType]:
    if isinstance(field, SourceFieldSwitchGroupConfig):
        return list(field.fields)
    if isinstance(field, SourceFieldSelectConfig):
        return [nested for option in field.options for nested in option.fields or []]
    return []


def _walk(fields: list[FieldType]) -> Iterator[FieldType]:
    for field in fields:
        yield field
        yield from _walk(_nested_fields(field))


def _holds_credentials(field: FieldType) -> bool:
    if isinstance(field, SourceFieldInputConfig):
        return field.secret or field.type == SourceFieldInputConfigType.PASSWORD
    return isinstance(field, SourceFieldFileUploadConfig | SourceFieldOauthConfig | SourceFieldSSHTunnelConfig)


@pytest.mark.parametrize("source_type", SOURCE_TYPES, ids=str)
def test_every_top_level_field_has_exactly_one_kind(source_type) -> None:
    source = ALL_SOURCES[source_type]
    fields = source.get_source_config.fields

    kinds_by_name: dict[str, set[JobInputKind]] = {}
    for field in fields:
        kinds_by_name.setdefault(field.name, set()).add(field_kind(field))
    conflicting = sorted(name for name, kinds in kinds_by_name.items() if len(kinds) > 1)
    assert not conflicting, f"{source_type}: fields declared twice with different kinds: {conflicting}"

    runtime = sorted(name for name in kinds_by_name if is_runtime_key(source, name))
    assert not runtime, f"{source_type}: form fields that collide with runtime keys: {runtime}"


@pytest.mark.parametrize("source_type", SOURCE_TYPES, ids=str)
def test_sync_settings_never_hold_credentials(source_type) -> None:
    source = ALL_SOURCES[source_type]
    leaking = sorted(
        f"{field.name}.{nested.name}" if nested is not field else field.name
        for field in source.get_source_config.fields
        if field_kind(field) == JobInputKind.SETTING
        for nested in _walk([field])
        if _holds_credentials(nested)
    )
    assert not leaking, f"{source_type}: sync settings that hold credentials: {leaking}"


@pytest.mark.parametrize("source_type", SOURCE_TYPES, ids=str)
def test_connection_host_fields_are_connection_fields(source_type) -> None:
    kinds = declared_field_kinds(source_type)
    host_settings = sorted(
        name
        for name in ALL_SOURCES[source_type].connection_host_fields
        if kinds.get(name, JobInputKind.CONNECTION) != JobInputKind.CONNECTION
    )
    assert not host_settings, f"{source_type}: connection host fields classified as settings: {host_settings}"


@pytest.mark.parametrize("source_type", SOURCE_TYPES, ids=str)
def test_only_top_level_fields_set_sync_setting(source_type) -> None:
    nested_flags = sorted(
        nested.name
        for field in ALL_SOURCES[source_type].get_source_config.fields
        for nested in _walk(_nested_fields(field))
        if isinstance(nested, SYNC_SETTING_FIELD_TYPES) and nested.sync_setting
    )
    assert not nested_flags, (
        f"{source_type}: nested fields set sync_setting, which has no effect because the top-level "
        f"field decides the kind of the whole value: {nested_flags}"
    )


def test_classification_audit_is_up_to_date() -> None:
    assert CLASSIFICATION_AUDIT_PATH.read_text() == render_classification_audit(), (
        "The source field classification audit is out of date. "
        "Run `python manage.py generate_source_field_classification` and commit the result."
    )
