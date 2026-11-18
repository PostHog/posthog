import uuid
from contextlib import contextmanager
from typing import Any

import pytest
from unittest.mock import MagicMock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql import Table
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.keyset import (
    KeysetResumeState,
    keyset_last_key,
    keyset_state,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres import (
    PostgreSQLColumn,
    resolve_postgres_keyset,
)


def _resolve(columns: list[tuple[str, str]], primary_keys: list[str]) -> Any:
    table = Table(
        name="orders",
        parents=("public",),
        columns=[PostgreSQLColumn(name=name, data_type=data_type, nullable=False) for name, data_type in columns],
    )
    return resolve_postgres_keyset(
        primary_keys=primary_keys,
        arrow_schema=table.to_arrow_schema(),
        used_id_pk_fallback=False,
        has_duplicate_primary_keys=False,
        is_partitioned=False,
        should_use_incremental_field=False,
        is_xmin=False,
        is_duckdb=False,
        full_table=table,
    )


@pytest.mark.parametrize(
    "columns,primary_keys,checkpointable,reason",
    [
        ([("id", "uuid")], ["id"], True, None),
        ([("id", "UUID")], ["id"], True, None),
        ([("tenant", "integer"), ("id", "uuid")], ["tenant", "id"], True, None),
        ([("id", "bigint")], ["id"], True, None),
        ([("id", "text")], ["id"], False, "non_orderable_type:string"),
        ([("tenant", "uuid"), ("slug", "character varying")], ["tenant", "slug"], False, "non_orderable_type:string"),
        ([("id", "uuid"), ("note", "text")], ["id"], True, None),
    ],
)
def test_uuid_key_can_checkpoint_and_text_key_cannot(columns, primary_keys, checkpointable, reason):
    keyset = _resolve(columns, primary_keys)
    assert (keyset.columns, keyset.checkpointable, keyset.reason) == (primary_keys, checkpointable, reason)


def test_uuid_key_returns_from_the_checkpoint_as_text():
    store: dict[str, str] = {}
    redis = MagicMock()
    redis.set.side_effect = lambda key, value, ex=None: store.__setitem__(key, value)
    redis.get.side_effect = store.get

    class _Manager(ResumableSourceManager[KeysetResumeState]):
        @contextmanager
        def _get_redis(self):
            yield redis

    manager = _Manager(MagicMock(team_id=1, job_id="job-1"), KeysetResumeState)
    key = (7, uuid.UUID(int=0xABCDEF << 64))

    manager.save_state(keyset_state(key))
    manager.confirm()
    manager.commit()

    assert keyset_last_key(manager.load_state(), key_length=2) == (7, str(key[1]))
