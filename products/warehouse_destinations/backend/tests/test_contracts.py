from typing import Any

import pytest

import pyarrow as pa

from products.warehouse_destinations.backend.facade.configs.base import DestinationConfig
from products.warehouse_destinations.backend.facade.configs.postgres import (
    PostgresAuthMethodConfig,
    PostgresDestinationConfig,
)
from products.warehouse_destinations.backend.facade.contracts import (
    DestinationCapabilities,
    DestinationConfigurationError,
    DestinationConnection,
    DestinationError,
    MergeSpec,
    TableTarget,
    TargetRef,
    UnsupportedDestinationError,
)
from products.warehouse_destinations.backend.facade.enums import (
    DestinationType,
    ErrorKind,
    ExistingTablePolicy,
    LogicalType,
    WriteMode,
)
from products.warehouse_destinations.backend.facade.testing import fake_config

FIELDS: list[pa.Field] = [pa.field("id", pa.int64()), pa.field("version", pa.int64()), pa.field("name", pa.string())]
SCHEMA = pa.schema(FIELDS)


def _ref(write_mode: WriteMode = WriteMode.APPEND, **kwargs: Any) -> TargetRef:
    return TargetRef(**{"namespace": ("public",), "table_name": "events", "write_mode": write_mode, **kwargs})


@pytest.mark.parametrize(
    "kwargs",
    [
        {"primary_keys": ("id",)},
        {"primary_keys": ("id", "name"), "version_keys": ("version",)},
        {"primary_keys": ("id",), "version_keys": ("version",), "dedupe_source": True, "ensure_unique_key": True},
    ],
)
def test_merge_spec_accepts_valid_keys(kwargs: dict[str, Any]) -> None:
    spec = MergeSpec(**kwargs)

    assert spec.primary_keys == kwargs["primary_keys"]


@pytest.mark.parametrize(
    "kwargs, match",
    [
        ({"primary_keys": ()}, "at least one primary key"),
        ({"primary_keys": (), "version_keys": ("version",)}, "at least one primary key"),
        ({"primary_keys": ("id",), "version_keys": ("id",)}, r"both primary and version keys: \['id'\]"),
        (
            {"primary_keys": ("id", "name"), "version_keys": ("version", "name")},
            r"both primary and version keys: \['name'\]",
        ),
        ({"primary_keys": ("id", "id")}, "Keys repeat"),
        ({"primary_keys": ("id",), "version_keys": ("version", "version")}, "Keys repeat"),
    ],
)
def test_merge_spec_rejects_invalid_keys(kwargs: dict[str, Any], match: str) -> None:
    with pytest.raises(ValueError, match=match):
        MergeSpec(**kwargs)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"write_mode": WriteMode.APPEND},
        {"write_mode": WriteMode.APPEND, "staging_key": "ignored-for-append"},
        {"write_mode": WriteMode.REPLACE, "staging_key": "run-1"},
        {"write_mode": WriteMode.MERGE, "staging_key": "run-1", "owner_tag": "tag:with:colons"},
        {"write_mode": "append", "namespace": ()},
        {"write_mode": WriteMode.APPEND, "namespace": ("catalog", "schema")},
    ],
)
def test_target_ref_accepts_valid_combinations(kwargs: dict[str, Any]) -> None:
    ref = _ref(**kwargs)

    assert ref.write_mode == WriteMode(kwargs["write_mode"])


@pytest.mark.parametrize(
    "kwargs, match",
    [
        ({"table_name": ""}, "requires a table name"),
        ({"table_name": "   "}, "requires a table name"),
        ({"namespace": ("public", " ")}, "cannot be blank"),
        ({"write_mode": WriteMode.REPLACE}, "replace write requires a staging key"),
        ({"write_mode": WriteMode.REPLACE, "staging_key": ""}, "replace write requires a staging key"),
        ({"write_mode": WriteMode.MERGE}, "merge write requires a staging key"),
        ({"owner_tag": ""}, "owner tag cannot be empty"),
    ],
)
def test_target_ref_rejects_invalid_combinations(kwargs: dict[str, Any], match: str) -> None:
    with pytest.raises(ValueError, match=match):
        _ref(**kwargs)


def test_target_ref_rejects_unknown_write_mode() -> None:
    with pytest.raises(ValueError):
        _ref(write_mode="upsert")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "ref_kwargs, target_kwargs",
    [
        ({}, {}),
        ({"write_mode": WriteMode.MERGE, "staging_key": "run-1"}, {"merge": MergeSpec(primary_keys=("id",))}),
        (
            {"write_mode": WriteMode.MERGE, "staging_key": "run-1"},
            {"merge": MergeSpec(primary_keys=("id", "name"), version_keys=("version",))},
        ),
        ({"owner_tag": "tag"}, {"existing_table": ExistingTablePolicy.REQUIRE_OWNED}),
        ({}, {"column_types": {"name": LogicalType.JSON, "id": "int32"}}),
    ],
)
def test_table_target_accepts_valid_combinations(ref_kwargs: dict[str, Any], target_kwargs: dict[str, Any]) -> None:
    target = TableTarget(ref=_ref(**ref_kwargs), schema=SCHEMA, **target_kwargs)

    assert all(isinstance(value, LogicalType) for value in target.column_types.values())


@pytest.mark.parametrize(
    "ref_kwargs, target_kwargs, match",
    [
        ({"write_mode": WriteMode.MERGE, "staging_key": "run-1"}, {}, "MERGE write requires a MergeSpec"),
        ({}, {"merge": MergeSpec(primary_keys=("id",))}, "append write cannot have a MergeSpec"),
        (
            {"write_mode": WriteMode.REPLACE, "staging_key": "run-1"},
            {"merge": MergeSpec(primary_keys=("id",))},
            "replace write cannot have a MergeSpec",
        ),
        (
            {"write_mode": WriteMode.MERGE, "staging_key": "run-1"},
            {"merge": MergeSpec(primary_keys=("missing",))},
            r"Merge keys are not in the schema: \['missing'\]",
        ),
        (
            {"write_mode": WriteMode.MERGE, "staging_key": "run-1"},
            {"merge": MergeSpec(primary_keys=("id",), version_keys=("updated_at",))},
            r"Merge keys are not in the schema: \['updated_at'\]",
        ),
        ({}, {"existing_table": ExistingTablePolicy.REQUIRE_OWNED}, "REQUIRE_OWNED needs an owner tag"),
        ({}, {"column_types": {"absent": LogicalType.TEXT}}, r"not in the schema: \['absent'\]"),
        ({}, {"column_types": {"name": "varchar(5)"}}, "is not a valid LogicalType"),
    ],
)
def test_table_target_rejects_invalid_combinations(
    ref_kwargs: dict[str, Any], target_kwargs: dict[str, Any], match: str
) -> None:
    with pytest.raises(ValueError, match=match):
        TableTarget(ref=_ref(**ref_kwargs), schema=SCHEMA, **target_kwargs)


@pytest.mark.parametrize(
    "kwargs, match",
    [
        ({"write_modes": frozenset()}, "at least one write mode"),
        ({"batch_key_modes": frozenset({WriteMode.APPEND})}, r"not write modes: \['append'\]"),
        ({"namespace_depth": -1}, "cannot be negative"),
    ],
)
def test_capabilities_reject_invalid_combinations(kwargs: dict[str, Any], match: str) -> None:
    valid: dict[str, Any] = {
        "write_modes": frozenset({WriteMode.MERGE}),
        "batch_key_modes": frozenset({WriteMode.MERGE}),
        "namespace_depth": 1,
        "atomic_replace": True,
    }

    with pytest.raises(ValueError, match=match):
        DestinationCapabilities(**{**valid, **kwargs})


def _postgres_config(**auth: Any) -> PostgresDestinationConfig:
    auth = {"selection": "credentials", "host": "db.example.com", "user": "u", "password": "hunter2", **auth}
    return PostgresDestinationConfig(database="db", auth_method=PostgresAuthMethodConfig(**auth))


def test_destination_connection_config_does_not_follow_caller_mutation() -> None:
    config = _postgres_config()
    connection = DestinationConnection(team_id=1, config=config)

    config.database = "changed"
    config.auth_method.host = "changed.example.com"

    assert connection.config == _postgres_config()


def test_table_target_column_types_do_not_follow_caller_mutation() -> None:
    column_types = {"name": LogicalType.TEXT}
    target = TableTarget(ref=_ref(), schema=SCHEMA, column_types=column_types)

    column_types["name"] = LogicalType.JSON

    assert target.column_types == {"name": LogicalType.TEXT}


@pytest.mark.parametrize("destination_type", [DestinationType.POSTGRES, DestinationType.SNOWFLAKE])
def test_destination_connection_takes_its_type_from_the_config_class(destination_type: DestinationType) -> None:
    connection = DestinationConnection(team_id=1, config=fake_config(destination_type))

    assert connection.destination_type is destination_type


@pytest.mark.parametrize(
    "config",
    [
        {"database": "db"},
        None,
        # The base class is not a generated config: it has no destination type.
        DestinationConfig(),
    ],
)
def test_destination_connection_refuses_a_config_that_is_not_generated(config: Any) -> None:
    with pytest.raises(TypeError, match="generated DestinationConfig"):
        DestinationConnection(team_id=1, config=config)


def test_destination_connection_repr_hides_the_password() -> None:
    connection = DestinationConnection(team_id=1, config=_postgres_config())

    assert "hunter2" not in repr(connection)
    assert "db.example.com" in repr(connection)


@pytest.mark.parametrize(
    "build, kind, retryable",
    [
        (lambda: DestinationError("x", kind=ErrorKind.TRANSIENT), ErrorKind.TRANSIENT, True),
        (lambda: DestinationError("x", kind=ErrorKind.TIMEOUT), ErrorKind.TIMEOUT, False),
        (lambda: DestinationError("x", kind=ErrorKind.DATA), ErrorKind.DATA, False),
        (lambda: DestinationError("x", kind=ErrorKind.CONFIGURATION), ErrorKind.CONFIGURATION, False),
        (lambda: DestinationConfigurationError("x"), ErrorKind.CONFIGURATION, False),
        (lambda: UnsupportedDestinationError("x"), ErrorKind.CONFIGURATION, False),
    ],
)
def test_error_kind_decides_retryable(build: Any, kind: ErrorKind, retryable: bool) -> None:
    error = build()

    assert (error.kind, error.retryable) == (kind, retryable)


def test_destination_error_requires_a_kind() -> None:
    with pytest.raises(TypeError, match="requires an error kind"):
        DestinationError("no kind")


def test_destination_error_keeps_the_detail() -> None:
    error = DestinationConfigurationError("internal message", detail="Fix the password.")

    assert (str(error), error.detail) == ("internal message", "Fix the password.")
