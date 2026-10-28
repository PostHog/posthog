import re
from collections.abc import Iterator
from typing import Any

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
    ACCOUNT_SELECTOR_FLAG_FIELD_TYPES,
    CLASSIFICATION_AUDIT_PATH,
    SELECT_OPTION_KEY,
    SYNC_SETTING_FIELD_TYPES,
    JobInputKind,
    declared_field_kinds,
    declared_reference_options,
    field_kind,
    is_runtime_key,
    merge_job_inputs,
    render_classification_audit,
    split_job_inputs,
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


@pytest.mark.parametrize("source_type", SOURCE_TYPES, ids=str)
def test_only_top_level_fields_set_account_selector(source_type) -> None:
    nested_flags = sorted(
        nested.name
        for field in ALL_SOURCES[source_type].get_source_config.fields
        for nested in _walk(_nested_fields(field))
        if isinstance(nested, ACCOUNT_SELECTOR_FLAG_FIELD_TYPES) and nested.account_selector
    )
    assert not nested_flags, f"{source_type}: nested fields set account_selector, which has no effect: {nested_flags}"


@pytest.mark.parametrize("source_type", SOURCE_TYPES, ids=str)
def test_account_selectors_are_not_sync_settings_and_hold_no_credentials(source_type) -> None:
    fields = ALL_SOURCES[source_type].get_source_config.fields
    both = sorted(
        field.name
        for field in fields
        if isinstance(field, ACCOUNT_SELECTOR_FLAG_FIELD_TYPES)
        and field.account_selector
        and isinstance(field, SYNC_SETTING_FIELD_TYPES)
        and field.sync_setting
    )
    assert not both, f"{source_type}: fields that are both account selector and sync setting: {both}"

    leaking = sorted(
        nested.name
        for field in fields
        if field_kind(field) == JobInputKind.SELECTOR
        for nested in _walk([field])
        if _holds_credentials(nested)
    )
    assert not leaking, f"{source_type}: account selectors that hold credentials: {leaking}"


ACCOUNT_SELECTOR_NAME = re.compile(
    r"(^|_)(account|ad_account|customer|property|advertiser|channel|business_unit)_id$|^site_url$"
)


@pytest.mark.parametrize("source_type", SOURCE_TYPES, ids=str)
def test_account_id_fields_of_credential_reference_sources_are_marked(source_type) -> None:
    """Heuristic only. A source that references an `Integration` row shares that row with other sources, so an account id field must be a selector."""
    kinds = declared_field_kinds(source_type)
    if JobInputKind.REFERENCE not in kinds.values() and not declared_reference_options(source_type):
        pytest.skip("source holds no credential reference")
    host_fields = set(ALL_SOURCES[source_type].connection_host_fields)
    unmarked = sorted(
        name
        for name, kind in kinds.items()
        if kind == JobInputKind.CONNECTION and name not in host_fields and ACCOUNT_SELECTOR_NAME.search(name)
    )
    assert not unmarked, f"{source_type}: set account_selector=True on account id fields: {unmarked}"


def _sample_inputs(source_type) -> list[dict[str, Any]]:
    """Job inputs that cover every top-level field and every option of every select."""
    fields = ALL_SOURCES[source_type].get_source_config.fields
    base: dict[str, Any] = {field.name: f"value-of-{field.name}" for field in fields}
    shapes = [base]
    for field in fields:
        if not isinstance(field, SourceFieldSelectConfig):
            continue
        for option in field.options:
            nested = {nested_field.name: f"value-of-{nested_field.name}" for nested_field in option.fields or []}
            shapes.append({**base, field.name: {SELECT_OPTION_KEY: option.value, **nested}})
    return shapes


@pytest.mark.parametrize("source_type", SOURCE_TYPES, ids=str)
def test_split_and_merge_round_trip_every_form_shape(source_type) -> None:
    for job_inputs in _sample_inputs(source_type):
        split = split_job_inputs(source_type, job_inputs)

        assert merge_job_inputs(split) == job_inputs


@pytest.mark.parametrize("source_type", SOURCE_TYPES, ids=str)
def test_reference_options_keep_their_whole_value_in_the_reference_part(source_type) -> None:
    for name, values in declared_reference_options(source_type).items():
        field = next(field for field in ALL_SOURCES[source_type].get_source_config.fields if field.name == name)
        assert isinstance(field, SourceFieldSelectConfig)
        for option in field.options:
            value = {SELECT_OPTION_KEY: option.value, **{n.name: 1 for n in option.fields or []}}
            split = split_job_inputs(source_type, {name: value})
            if option.value in values:
                assert split.references == {name: value}
            else:
                assert split.connection == {name: value}


def test_classification_audit_is_up_to_date() -> None:
    assert CLASSIFICATION_AUDIT_PATH.read_text() == render_classification_audit(), (
        "The source field classification audit is out of date. "
        "Run `python manage.py generate_source_field_classification` and commit the result."
    )
