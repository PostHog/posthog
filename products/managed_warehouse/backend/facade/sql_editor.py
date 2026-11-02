from typing import TYPE_CHECKING

from products.managed_warehouse.backend.logic.sql_editor import managed_warehouse_sql_editor_uses_trino
from products.managed_warehouse.backend.logic.sql_editor_credentials import (
    resolve_managed_warehouse_postgres_connection,
)

__all__ = [
    "managed_trino_adapter",
    "managed_warehouse_sql_editor_uses_trino",
    "resolve_managed_warehouse_postgres_connection",
]

if TYPE_CHECKING:
    from posthog.hogql.direct_sql.adapter import DirectSQLAdapter


def managed_trino_adapter() -> "DirectSQLAdapter":
    from products.managed_warehouse.backend.logic.sql_editor_trino import (
        ManagedTrinoAdapter,  # noqa: PLC0415 -- keeps optional query drivers off Django startup
    )

    return ManagedTrinoAdapter()
