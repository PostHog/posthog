"""
Domain logic for notebooks.

Owns ORM access and business rules. Returns ORM instances and primitives to the
facade, which maps them to framework-free contracts. Nothing outside the product
should import this module — cross-product callers go through ``facade.api``.
"""

from collections.abc import Iterable
from typing import Any
from uuid import UUID

from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

from asgiref.sync import sync_to_async

from posthog.rbac.user_access_control import UserAccessControl

from .models import Notebook, ResourceNotebook


def _base_queryset(team_id: int, *, include_deleted: bool = False) -> Any:
    qs = Notebook.objects.filter(team_id=team_id)
    if not include_deleted:
        qs = qs.filter(deleted=False)
    return qs


def notebook_exists(team_id: int, short_id: str, *, include_deleted: bool = True) -> bool:
    return _base_queryset(team_id, include_deleted=include_deleted).filter(short_id=short_id).exists()


async def anotebook_exists(team_id: int, short_id: str, *, include_deleted: bool = True) -> bool:
    return await _base_queryset(team_id, include_deleted=include_deleted).filter(short_id=short_id).aexists()


def get_notebook(team_id: int, short_id: str, *, include_deleted: bool = False) -> Notebook | None:
    return _base_queryset(team_id, include_deleted=include_deleted).filter(short_id=short_id).first()


async def aget_notebook(team_id: int, short_id: str, *, include_deleted: bool = False) -> Notebook | None:
    return await _base_queryset(team_id, include_deleted=include_deleted).filter(short_id=short_id).afirst()


async def acan_user_edit_notebook(team_id: int, short_id: str, user_access_control: UserAccessControl) -> bool:
    notebook = await aget_notebook(team_id, short_id, include_deleted=True)
    if notebook is None:
        return False

    def check() -> bool:
        return bool(user_access_control.check_access_level_for_object(notebook, "editor"))

    return await sync_to_async(check)()


async def aupdate_notebook_content(
    team_id: int,
    short_id: str,
    *,
    content: dict[str, Any],
    title: str,
    text_content: str | None,
    last_modified_by_id: int | None,
) -> Notebook | None:
    notebook = await aget_notebook(team_id, short_id, include_deleted=True)
    if notebook is None:
        return None
    await Notebook.objects.filter(pk=notebook.pk).aupdate(
        content=content,
        title=title,
        text_content=text_content,
        version=F("version") + 1,
        last_modified_by_id=last_modified_by_id,
        last_modified_at=timezone.now(),
    )
    await notebook.arefresh_from_db()
    return notebook


async def aupsert_notebook(
    team_id: int,
    short_id: str,
    *,
    created_by_id: int | None,
    last_modified_by_id: int | None,
    title: str,
    content: dict[str, Any],
    text_content: str | None = None,
) -> tuple[Notebook, bool]:
    notebook, created = await Notebook.objects.aget_or_create(
        team_id=team_id,
        short_id=short_id,
        defaults={
            "created_by_id": created_by_id,
            "last_modified_by_id": last_modified_by_id,
            "title": title,
            "content": content,
            "text_content": text_content,
        },
    )
    if not created:
        notebook.content = content
        notebook.title = title
        notebook.version += 1
        notebook.last_modified_by_id = last_modified_by_id
        update_fields = ["content", "title", "version", "last_modified_by", "last_modified_at"]
        if text_content is not None:
            notebook.text_content = text_content
            update_fields.append("text_content")
        await notebook.asave(update_fields=update_fields)
    return notebook, created


def get_notebook_short_ids_by_ids(team_id: int, notebook_ids: list[UUID]) -> dict[UUID, str]:
    """Resolve notebook UUIDs to their linkable short_ids in one query, team-scoped. Callers that
    store a notebook UUID reference (e.g. Pulse opportunities) use this to build notebook URLs."""
    if not notebook_ids:
        return {}
    rows = _base_queryset(team_id, include_deleted=True).filter(id__in=notebook_ids).values_list("id", "short_id")
    return {row[0]: row[1] for row in rows}


def get_notebook_short_ids_for_creator(project_id: int, user_id: int) -> list[str]:
    return list(
        Notebook.objects.filter(created_by_id=user_id, team__project_id=project_id).values_list("short_id", flat=True)
    )


def get_notebook_activity_summary(team_id: int, limit: int) -> tuple[int, list[dict[str, Any]]]:
    qs = Notebook.objects.filter(team_id=team_id, deleted=False)
    total = qs.count()
    recent = list(qs.order_by("-last_modified_at")[:limit].values("short_id", "title", "last_modified_at"))
    return total, recent


def create_notebook(
    team_id: int,
    *,
    title: str | None,
    content: Any,
    text_content: str | None = None,
    created_by_id: int | None = None,
    last_modified_by_id: int | None = None,
    visibility: str = Notebook.Visibility.DEFAULT,
) -> Notebook:
    return Notebook.objects.create(
        team_id=team_id,
        title=title,
        content=content,
        text_content=text_content,
        created_by_id=created_by_id,
        last_modified_by_id=last_modified_by_id,
        visibility=visibility,
    )


def get_group_notebook_short_id(group_id: int) -> str | None:
    link = ResourceNotebook.objects.filter(group=group_id).select_related("notebook").first()
    return link.notebook.short_id if link else None


def group_has_notebook(group_id: int) -> bool:
    return ResourceNotebook.objects.filter(group=group_id).exists()


def create_group_notebook(team_id: int, group_id: int, *, title: str | None, content: Any) -> Notebook:
    with transaction.atomic():
        notebook = Notebook.objects.create(
            team_id=team_id,
            title=title,
            content=content,
            visibility=Notebook.Visibility.INTERNAL,
        )
        ResourceNotebook.objects.create(notebook=notebook, group=group_id)
    return notebook


def create_account_notebook(
    team_id: int,
    account_id: str | UUID,
    *,
    title: str | None,
    content: Any,
    text_content: str | None = None,
    created_by_id: int | None = None,
    last_modified_by_id: int | None = None,
) -> Notebook:
    with transaction.atomic():
        notebook = Notebook.objects.create(
            team_id=team_id,
            title=title,
            content=content,
            text_content=text_content,
            created_by_id=created_by_id,
            last_modified_by_id=last_modified_by_id,
            visibility=Notebook.Visibility.INTERNAL,
        )
        ResourceNotebook.objects.create(notebook=notebook, account_id=account_id)
    return notebook


def list_account_internal_notes(account_id: str | UUID) -> list[ResourceNotebook]:
    return list(
        ResourceNotebook.objects.filter(
            account_id=account_id,
            notebook__deleted=False,
            notebook__visibility=Notebook.Visibility.INTERNAL,
        )
        .select_related("notebook")
        .order_by("-notebook__last_modified_at")
    )


def _account_notebook_queryset(account_id: str | UUID) -> Any:
    return Notebook.objects.filter(
        deleted=False,
        visibility=Notebook.Visibility.INTERNAL,
        resources__account_id=account_id,
    ).select_related("created_by", "last_modified_by")


# Author sorting fans out to the user's name columns so the order matches what the UI shows.
_ACCOUNT_NOTEBOOK_ORDERING: dict[str, tuple[str, ...]] = {
    "created_at": ("created_at",),
    "-created_at": ("-created_at",),
    "created_by": ("created_by__first_name", "created_by__last_name"),
    "-created_by": ("-created_by__first_name", "-created_by__last_name"),
}
_DEFAULT_ACCOUNT_NOTEBOOK_ORDERING = ("-created_at",)


def list_account_notebooks(
    account_id: str | UUID, *, search: str | None = None, order: str | None = None
) -> list[Notebook]:
    queryset = _account_notebook_queryset(account_id)
    if search:
        # Mirror the main notebooks list: full-text over title and content (some notebooks
        # have no text_content until their next save, so title is matched too).
        queryset = queryset.filter(Q(title__search=search) | Q(text_content__search=search))
    ordering = _ACCOUNT_NOTEBOOK_ORDERING.get(order or "", _DEFAULT_ACCOUNT_NOTEBOOK_ORDERING)
    return list(queryset.order_by(*ordering))


def get_account_notebook(account_id: str | UUID, short_id: str) -> Notebook | None:
    return _account_notebook_queryset(account_id).filter(short_id=short_id).first()


def delete_account_notebook(account_id: str | UUID, short_id: str) -> bool:
    notebook = _account_notebook_queryset(account_id).filter(short_id=short_id).first()
    if notebook is None:
        return False
    notebook.delete()
    return True


def list_team_account_notes(
    team_id: int,
    *,
    account_ids: Iterable[UUID | str] | None = None,
    account_id: UUID | str | None = None,
    created_by_ids: Iterable[int] | None = None,
    search: str | None = None,
    offset: int = 0,
    limit: int = 100,
) -> tuple[list[ResourceNotebook], int]:
    """Team-wide account notes: internal notebooks linked to any account, newest-modified first.

    ``account_ids`` restricts to the given accounts (callers pass the caller-accessible set —
    a lazy ``values_list`` queryset compiles to a SQL subquery). ``account_id`` narrows to a
    single account, ``created_by_ids`` to notes authored by the given users. ``search`` is
    full-text over notebook title/content plus substring over the linked account's name.
    Returns ``(page, total_count)``.
    """
    queryset = ResourceNotebook.objects.filter(
        account__isnull=False,
        notebook__team_id=team_id,
        notebook__deleted=False,
        notebook__visibility=Notebook.Visibility.INTERNAL,
    ).select_related("notebook", "notebook__created_by", "account")
    if account_ids is not None:
        queryset = queryset.filter(account_id__in=account_ids)
    if account_id is not None:
        queryset = queryset.filter(account_id=account_id)
    if created_by_ids is not None:
        queryset = queryset.filter(notebook__created_by_id__in=created_by_ids)
    if search:
        queryset = queryset.filter(
            Q(notebook__title__search=search)
            | Q(notebook__text_content__search=search)
            | Q(account__name__icontains=search)
        )
    queryset = queryset.order_by("-notebook__last_modified_at")
    return list(queryset[offset : offset + limit]), queryset.count()
