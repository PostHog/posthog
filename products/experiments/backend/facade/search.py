"""Experiment search for the full-text searches outside the experiments product."""

from typing import Any

from posthog.helpers.full_text_search import to_search_results

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.experiments.backend.logic import search as search_logic


def search_experiments(
    *,
    project_id: int,
    query: str | None,
    access_control: UserAccessControl,
    limit: int,
    include_deleted: bool,
    offset: int = 0,
    with_access_levels: bool = False,
    include_count: bool = True,
) -> tuple[list[dict[str, Any]], int]:
    """Ranked full-text search over a project's experiments, in the result shape of core search.

    Leaves out the experiments the user may not view. Without a query the experiments come in name
    order. `with_access_levels` adds `user_access_level`, the user's resolved level for each
    experiment. `include_count=False` skips the count query and reports a total of 0.
    """
    rows, total_count = search_logic.search(
        project_id=project_id,
        query=query,
        access_control=access_control,
        limit=limit,
        offset=offset,
        include_deleted=include_deleted,
        include_count=include_count,
    )
    access_levels = (
        access_control.bulk_object_access_levels("experiment", [(str(row["id"]), row["created_by_id"]) for row in rows])
        if with_access_levels
        else None
    )
    return to_search_results(
        rows, entity_type="experiment", ranked=bool(query), access_levels=access_levels
    ), total_count
