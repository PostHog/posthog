"""
Facade API for notebooks.

This is the ONLY data-capability module other apps are allowed to import. It
accepts ids and primitives, calls domain logic (``logic.py``), and converts ORM
instances into framework-free contracts before returning.

Do NOT implement business logic here (use ``logic.py``), import DRF or HTTP
concerns, or return ORM instances or QuerySets.

Content-tree helpers live in ``facade.content``; collaborative-edit publishing
lives in ``facade.collab``.
"""

from typing import Any

from .. import logic
from ..models import Notebook
from . import contracts


def _to_notebook_data(notebook: Notebook) -> contracts.NotebookData:
    return contracts.NotebookData(
        id=notebook.id,
        short_id=notebook.short_id,
        title=notebook.title,
        content=notebook.content,
        text_content=notebook.text_content,
        deleted=notebook.deleted,
        visibility=notebook.visibility,
        version=notebook.version,
        created_at=notebook.created_at,
        last_modified_at=notebook.last_modified_at,
        created_by_id=notebook.created_by_id,
        last_modified_by_id=notebook.last_modified_by_id,
    )


# --- Reads ---


def notebook_exists(team_id: int, short_id: str, *, include_deleted: bool = True) -> bool:
    return logic.notebook_exists(team_id, short_id, include_deleted=include_deleted)


async def anotebook_exists(team_id: int, short_id: str, *, include_deleted: bool = True) -> bool:
    return await logic.anotebook_exists(team_id, short_id, include_deleted=include_deleted)


def get_notebook(team_id: int, short_id: str, *, include_deleted: bool = False) -> contracts.NotebookData | None:
    notebook = logic.get_notebook(team_id, short_id, include_deleted=include_deleted)
    return _to_notebook_data(notebook) if notebook is not None else None


async def aget_notebook(team_id: int, short_id: str, *, include_deleted: bool = False) -> contracts.NotebookData | None:
    notebook = await logic.aget_notebook(team_id, short_id, include_deleted=include_deleted)
    return _to_notebook_data(notebook) if notebook is not None else None


def get_notebook_short_ids_for_creator(project_id: int, user_id: int) -> list[str]:
    return logic.get_notebook_short_ids_for_creator(project_id, user_id)


def get_notebook_activity_summary(team_id: int, limit: int) -> contracts.NotebookActivitySummary:
    total, recent = logic.get_notebook_activity_summary(team_id, limit)
    return contracts.NotebookActivitySummary(
        total_count=total,
        recent=[
            contracts.NotebookRecent(
                short_id=row["short_id"],
                title=row["title"],
                last_modified_at=row["last_modified_at"],
            )
            for row in recent
        ],
    )


# --- Access control ---


async def acan_user_edit_notebook(team_id: int, user_id: int, short_id: str) -> bool:
    return await logic.acan_user_edit_notebook(team_id, user_id, short_id)


# --- Writes ---


async def aupdate_notebook_content(
    team_id: int,
    short_id: str,
    *,
    content: dict[str, Any],
    title: str,
    text_content: str | None,
    last_modified_by_id: int | None,
) -> contracts.NotebookData | None:
    notebook = await logic.aupdate_notebook_content(
        team_id,
        short_id,
        content=content,
        title=title,
        text_content=text_content,
        last_modified_by_id=last_modified_by_id,
    )
    return _to_notebook_data(notebook) if notebook is not None else None


async def aupsert_notebook(
    team_id: int,
    short_id: str,
    *,
    created_by_id: int | None,
    last_modified_by_id: int | None,
    title: str,
    content: dict[str, Any],
) -> tuple[contracts.NotebookData, bool]:
    notebook, created = await logic.aupsert_notebook(
        team_id,
        short_id,
        created_by_id=created_by_id,
        last_modified_by_id=last_modified_by_id,
        title=title,
        content=content,
    )
    return _to_notebook_data(notebook), created


def create_notebook(
    team_id: int,
    *,
    title: str | None,
    content: Any,
    text_content: str | None = None,
    created_by_id: int | None = None,
    last_modified_by_id: int | None = None,
    visibility: str = Notebook.Visibility.DEFAULT,
) -> contracts.NotebookData:
    notebook = logic.create_notebook(
        team_id,
        title=title,
        content=content,
        text_content=text_content,
        created_by_id=created_by_id,
        last_modified_by_id=last_modified_by_id,
        visibility=visibility,
    )
    return _to_notebook_data(notebook)


# --- Resource links (groups, accounts) ---


def get_group_notebook_short_id(group_id: int) -> str | None:
    return logic.get_group_notebook_short_id(group_id)


def group_has_notebook(group_id: int) -> bool:
    return logic.group_has_notebook(group_id)


def create_group_notebook(team_id: int, group_id: int, *, title: str | None, content: Any) -> contracts.NotebookData:
    return _to_notebook_data(logic.create_group_notebook(team_id, group_id, title=title, content=content))


def create_account_notebook(
    team_id: int,
    account_id: int,
    *,
    title: str | None,
    content: Any,
    text_content: str | None = None,
    created_by_id: int | None = None,
    last_modified_by_id: int | None = None,
) -> contracts.NotebookData:
    notebook = logic.create_account_notebook(
        team_id,
        account_id,
        title=title,
        content=content,
        text_content=text_content,
        created_by_id=created_by_id,
        last_modified_by_id=last_modified_by_id,
    )
    return _to_notebook_data(notebook)


def list_account_internal_notes(account_id: int) -> list[contracts.AccountNote]:
    return [
        contracts.AccountNote(title=link.notebook.title, short_id=link.notebook.short_id)
        for link in logic.list_account_internal_notes(account_id)
    ]
