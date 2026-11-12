from typing import Any, Literal

from django.db.models import F

from posthog.helpers.full_text_search import build_rank

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.experiments.backend.models.experiment import Experiment

# The weights and threshold core search applies to every entity it unions, so experiments rank the
# same way next to them.
SEARCH_FIELDS: dict[str, Literal["A", "B", "C"]] = {"name": "A", "description": "C"}
SEARCH_RANK_THRESHOLD = 0.05


def search(
    *,
    project_id: int,
    query: str | None,
    access_control: UserAccessControl,
    limit: int,
    offset: int,
    include_deleted: bool,
    include_count: bool,
) -> tuple[list[dict[str, Any]], int]:
    """Rows of the project's experiments that match `query` and the user may view, and their total.

    Without a query the rows come in name order.
    """
    queryset = access_control.filter_queryset_by_access_level(Experiment.objects.filter(team__project_id=project_id))
    if not include_deleted:
        queryset = queryset.filter(deleted=False)
    fields = ["id", "name", "description", "created_by_id"]
    if query:
        queryset = queryset.annotate(rank=build_rank(SEARCH_FIELDS, query, config="simple"))
        queryset = queryset.filter(rank__gt=SEARCH_RANK_THRESHOLD).order_by("-rank")
        fields.append("rank")
    else:
        queryset = queryset.order_by(F("name").asc(nulls_first=True))
    total_count = queryset.count() if include_count else 0
    return list(queryset[offset : offset + limit].values(*fields)), total_count
