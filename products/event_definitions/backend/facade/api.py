from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from uuid import UUID

from products.event_definitions.backend.facade.contracts import DefinitionKind
from products.event_definitions.backend.logic import definition_metadata


def copy_definition_metadata(kind: DefinitionKind, definition_ids: Sequence[UUID | str]) -> int:
    return definition_metadata.copy_definition_metadata(kind, definition_ids)


def copy_definition_metadata_on_commit(kind: DefinitionKind, definition_id: UUID | str) -> None:
    definition_metadata.copy_definition_metadata_on_commit(kind, definition_id)


@contextmanager
def batch_definition_metadata_copies() -> Iterator[None]:
    with definition_metadata.batch_definition_metadata_copies():
        yield


def next_enterprise_definition_ids(kind: DefinitionKind, *, after: str | None, limit: int) -> list[str]:
    return definition_metadata.next_enterprise_definition_ids(kind, after=after, limit=limit)
