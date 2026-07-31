from __future__ import annotations

from uuid import UUID

from products.managed_warehouse.backend import sink_state
from products.managed_warehouse.backend.facade.contracts import DuckgresSinkStateCreateInput, DuckgresSinkStateRecord

__all__ = [
    "count_sink_states",
    "create_sink_state",
    "get_sink_state",
    "list_sink_states",
    "replace_sink_state",
    "sink_state_exists",
]


def create_sink_state(input: DuckgresSinkStateCreateInput) -> DuckgresSinkStateRecord:
    return sink_state.create_sink_state(input)


def get_sink_state(state_id: UUID) -> DuckgresSinkStateRecord | None:
    return sink_state.get_sink_state_by_id(state_id)


def list_sink_states() -> list[DuckgresSinkStateRecord]:
    return sink_state.list_sink_states_for_test()


def replace_sink_state(record: DuckgresSinkStateRecord) -> None:
    sink_state.replace_sink_state_for_test(record)


def count_sink_states() -> int:
    return sink_state.count_sink_states_for_test()


def sink_state_exists(state_id: UUID) -> bool:
    return sink_state.sink_state_exists_for_test(state_id)
