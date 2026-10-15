from collections.abc import Collection

from .facade.contracts import AuthorizationNotebook
from .models import Notebook
from .util import extract_referenced_insight_short_ids, extract_referenced_recording_ids


def authorization_notebooks(team_id: int) -> list[AuthorizationNotebook]:
    return [
        AuthorizationNotebook(
            id=id,
            created_by_id=created_by_id,
            insight_short_ids=frozenset(extract_referenced_insight_short_ids(content)),
            recording_ids=frozenset(extract_referenced_recording_ids(content)),
        )
        for id, created_by_id, content in Notebook.objects.filter(team_id=team_id, deleted=False).values_list(
            "id", "created_by_id", "content"
        )
    ]


def active_authorization_notebook_ids(team_id: int, ids: Collection[str]) -> frozenset[str]:
    return frozenset(
        str(id)
        for id in Notebook.objects.filter(team_id=team_id, deleted=False, id__in=ids).values_list("id", flat=True)
    )
