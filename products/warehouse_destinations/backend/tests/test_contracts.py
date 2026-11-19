from typing import Any

import pytest

import pyarrow as pa

from products.warehouse_destinations.backend.facade.contracts import DestinationConnection, MergeSpec, TableTarget
from products.warehouse_destinations.backend.facade.enums import WriteMode

FIELDS: list[pa.Field] = [pa.field("id", pa.int64()), pa.field("version", pa.int64()), pa.field("name", pa.string())]
SCHEMA = pa.schema(FIELDS)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"primary_keys": ("id",)},
        {"primary_keys": ("id", "name"), "version_keys": ("version",)},
        {"primary_keys": ("id",), "version_keys": ("version",), "dedupe_source": True},
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
        {"write_mode": WriteMode.MERGE, "staging_key": "run-1", "merge": MergeSpec(primary_keys=("id",))},
        {
            "write_mode": WriteMode.MERGE,
            "staging_key": "run-1",
            "merge": MergeSpec(primary_keys=("id", "name"), version_keys=("version",)),
        },
        {"write_mode": WriteMode.APPEND, "namespace": ()},
    ],
)
def test_table_target_accepts_valid_combinations(kwargs: dict[str, Any]) -> None:
    target = TableTarget(**{"namespace": ("db", "public"), "table_name": "events", "schema": SCHEMA, **kwargs})

    assert target.write_mode == kwargs["write_mode"]


@pytest.mark.parametrize(
    "kwargs, match",
    [
        ({"table_name": "", "write_mode": WriteMode.APPEND}, "requires a table name"),
        ({"table_name": "   ", "write_mode": WriteMode.APPEND}, "requires a table name"),
        ({"write_mode": WriteMode.MERGE, "staging_key": "run-1"}, "MERGE write requires a MergeSpec"),
        (
            {"write_mode": WriteMode.APPEND, "merge": MergeSpec(primary_keys=("id",))},
            "append write cannot have a MergeSpec",
        ),
        (
            {"write_mode": WriteMode.REPLACE, "staging_key": "run-1", "merge": MergeSpec(primary_keys=("id",))},
            "replace write cannot have a MergeSpec",
        ),
        ({"write_mode": WriteMode.REPLACE}, "replace write requires a staging key"),
        ({"write_mode": WriteMode.REPLACE, "staging_key": ""}, "replace write requires a staging key"),
        (
            {"write_mode": WriteMode.MERGE, "merge": MergeSpec(primary_keys=("id",))},
            "merge write requires a staging key",
        ),
        (
            {"write_mode": WriteMode.MERGE, "staging_key": "run-1", "merge": MergeSpec(primary_keys=("missing",))},
            r"Merge keys are not in the schema: \['missing'\]",
        ),
        (
            {
                "write_mode": WriteMode.MERGE,
                "staging_key": "run-1",
                "merge": MergeSpec(primary_keys=("id",), version_keys=("updated_at",)),
            },
            r"Merge keys are not in the schema: \['updated_at'\]",
        ),
    ],
)
def test_table_target_rejects_invalid_combinations(kwargs: dict[str, Any], match: str) -> None:
    with pytest.raises(ValueError, match=match):
        TableTarget(**{"namespace": ("db",), "table_name": "events", "schema": SCHEMA, **kwargs})


@pytest.mark.parametrize("field_name", ["config", "credentials"])
def test_destination_connection_mappings_do_not_follow_caller_mutation(field_name: str) -> None:
    source = {"host": "localhost"}
    kwargs: dict[str, Any] = {field_name: source}
    connection = DestinationConnection(destination_type="Postgres", team_id=1, **kwargs)

    source["host"] = "changed"

    mapping = getattr(connection, field_name)
    assert mapping == {"host": "localhost"}
    with pytest.raises(TypeError):
        mapping["host"] = "changed"


def test_table_target_column_overrides_do_not_follow_caller_mutation() -> None:
    overrides = {"name": "TEXT"}
    target = TableTarget(
        namespace=("db",), table_name="events", schema=SCHEMA, write_mode=WriteMode.APPEND, column_overrides=overrides
    )

    overrides["name"] = "VARCHAR"

    assert target.column_overrides == {"name": "TEXT"}


def test_destination_connection_repr_hides_credentials() -> None:
    connection = DestinationConnection(
        destination_type="Postgres", team_id=1, config={"host": "db.example.com"}, credentials={"password": "hunter2"}
    )

    assert "hunter2" not in repr(connection)
    assert "db.example.com" in repr(connection)
