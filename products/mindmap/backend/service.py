from collections.abc import Iterable
from dataclasses import dataclass
from typing import TypedDict

from django.core.exceptions import ValidationError
from django.db import transaction

from posthog.models.team import Team
from posthog.models.user import User

from products.mindmap.backend.models import MindMapEdge, MindMapPostIt
from products.notebooks.backend.models import Notebook

GRID_X = 220.0
GRID_Y = 160.0


class PositionUpdate(TypedDict):
    short_id: str
    position_x: float
    position_y: float


@dataclass
class MindMapState:
    postits: list[MindMapPostIt]
    edges: list[MindMapEdge]


def list_mindmap(team: Team) -> MindMapState:
    postits = list(MindMapPostIt.objects.filter(team=team, deleted=False).order_by("created_at"))
    edges = list(MindMapEdge.objects.filter(team=team).select_related("source", "target").order_by("created_at"))
    return MindMapState(postits=postits, edges=edges)


def _next_grid_slot(team: Team) -> tuple[float, float]:
    count = MindMapPostIt.objects.filter(team=team, deleted=False).count()
    cols = 6
    row, col = divmod(count, cols)
    return (col * GRID_X, row * GRID_Y)


def _validate_notebook(team: Team, notebook_short_id: str | None) -> None:
    if notebook_short_id is None:
        return
    exists = Notebook.objects.filter(team=team, short_id=notebook_short_id, deleted=False).exists()
    if not exists:
        raise ValidationError(f"Notebook with short_id '{notebook_short_id}' not found in this team")


def _get_postit(team: Team, short_id: str) -> MindMapPostIt:
    try:
        return MindMapPostIt.objects.get(team=team, short_id=short_id, deleted=False)
    except MindMapPostIt.DoesNotExist:
        raise ValidationError(f"Post-it '{short_id}' not found")


def _connect_internal(team: Team, user: User, source: MindMapPostIt, target: MindMapPostIt) -> MindMapEdge:
    if source.pk == target.pk:
        raise ValidationError("Cannot connect a post-it to itself")
    edge, _ = MindMapEdge.objects.get_or_create(team=team, source=source, target=target, defaults={"created_by": user})
    return edge


def create_postit(
    *,
    team: Team,
    user: User,
    title: str,
    body: str | None = None,
    color: str | None = None,
    emoji: str | None = None,
    position_x: float | None = None,
    position_y: float | None = None,
    notebook_short_id: str | None = None,
    parent_short_ids: Iterable[str] | None = None,
    child_short_ids: Iterable[str] | None = None,
) -> MindMapPostIt:
    _validate_notebook(team, notebook_short_id)

    parents = [_get_postit(team, sid) for sid in (parent_short_ids or [])]
    children = [_get_postit(team, sid) for sid in (child_short_ids or [])]

    if position_x is None or position_y is None:
        gx, gy = _next_grid_slot(team)
        position_x = gx if position_x is None else position_x
        position_y = gy if position_y is None else position_y

    with transaction.atomic():
        postit = MindMapPostIt.objects.create(
            team=team,
            title=title,
            body=body or "",
            color=color or MindMapPostIt.Color.YELLOW,
            emoji=emoji or "",
            position_x=position_x,
            position_y=position_y,
            notebook_short_id=notebook_short_id,
            created_by=user,
            last_modified_by=user,
        )
        for parent in parents:
            _connect_internal(team, user, parent, postit)
        for child in children:
            _connect_internal(team, user, postit, child)
    return postit


_SENTINEL = object()


def update_postit(
    *,
    team: Team,
    user: User,
    short_id: str,
    title: str | object = _SENTINEL,
    body: str | object = _SENTINEL,
    color: str | object = _SENTINEL,
    emoji: str | object = _SENTINEL,
    position_x: float | object = _SENTINEL,
    position_y: float | object = _SENTINEL,
    notebook_short_id: str | None | object = _SENTINEL,
) -> MindMapPostIt:
    postit = _get_postit(team, short_id)

    if title is not _SENTINEL:
        postit.title = title  # type: ignore[assignment]
    if body is not _SENTINEL:
        postit.body = body  # type: ignore[assignment]
    if color is not _SENTINEL:
        if color not in MindMapPostIt.Color.values:
            raise ValidationError(f"Invalid color '{color}'")
        postit.color = color  # type: ignore[assignment]
    if emoji is not _SENTINEL:
        postit.emoji = emoji  # type: ignore[assignment]
    if position_x is not _SENTINEL:
        postit.position_x = position_x  # type: ignore[assignment]
    if position_y is not _SENTINEL:
        postit.position_y = position_y  # type: ignore[assignment]
    if notebook_short_id is not _SENTINEL:
        _validate_notebook(team, notebook_short_id)  # type: ignore[arg-type]
        postit.notebook_short_id = notebook_short_id  # type: ignore[assignment]

    postit.last_modified_by = user
    postit.save()
    return postit


def delete_postit(*, team: Team, user: User, short_id: str) -> None:
    postit = _get_postit(team, short_id)
    with transaction.atomic():
        MindMapEdge.objects.filter(team=team, source=postit).delete()
        MindMapEdge.objects.filter(team=team, target=postit).delete()
        postit.deleted = True
        postit.last_modified_by = user
        postit.save(update_fields=["deleted", "last_modified_by", "last_modified_at"])


def bulk_position(*, team: Team, user: User, updates: list[PositionUpdate]) -> int:
    short_ids = [u["short_id"] for u in updates]
    by_id = {p.short_id: p for p in MindMapPostIt.objects.filter(team=team, deleted=False, short_id__in=short_ids)}
    touched: list[MindMapPostIt] = []
    for u in updates:
        postit = by_id.get(u["short_id"])
        if postit is None:
            continue
        postit.position_x = u["position_x"]
        postit.position_y = u["position_y"]
        postit.last_modified_by = user
        touched.append(postit)
    if touched:
        with transaction.atomic():
            for postit in touched:
                postit.save(update_fields=["position_x", "position_y", "last_modified_by", "last_modified_at"])
    return len(touched)


def connect(*, team: Team, user: User, source_short_id: str, target_short_id: str) -> MindMapEdge:
    source = _get_postit(team, source_short_id)
    target = _get_postit(team, target_short_id)
    return _connect_internal(team, user, source, target)


def disconnect(*, team: Team, user: User, source_short_id: str, target_short_id: str) -> None:
    MindMapEdge.objects.filter(
        team=team,
        source__short_id=source_short_id,
        target__short_id=target_short_id,
    ).delete()
