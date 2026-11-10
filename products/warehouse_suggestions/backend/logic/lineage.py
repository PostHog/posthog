from collections.abc import Collection, Mapping
from uuid import UUID


def recomputing_consumers(
    view_id: UUID, dependents: Mapping[UUID, Collection[UUID]], materialized_ids: Collection[UUID]
) -> frozenset[UUID]:
    consumers: set[UUID] = set()
    visited: set[UUID] = {view_id}
    frontier = [view_id]
    while frontier:
        for dependent_id in dependents.get(frontier.pop(), ()):
            if dependent_id in visited:
                continue
            visited.add(dependent_id)
            if dependent_id in materialized_ids:
                consumers.add(dependent_id)
            else:
                frontier.append(dependent_id)
    return frozenset(consumers)
