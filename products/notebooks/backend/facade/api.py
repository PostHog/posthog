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

from collections.abc import Iterable
from typing import TYPE_CHECKING, Any
from uuid import UUID

from .. import logic, markdown_migration
from ..models import Notebook, ResourceNotebook
from . import contracts

if TYPE_CHECKING:
    from posthog.models import User
    from posthog.rbac.user_access_control import UserAccessControl

MAX_NOTEBOOK_MIGRATION_BATCH_SIZE = markdown_migration.MAX_NOTEBOOK_MIGRATION_BATCH_SIZE


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


def get_markdown_notebook_migration_stats(
    team_id: int | None = None,
) -> contracts.MarkdownNotebookMigrationStats:
    return markdown_migration.get_markdown_notebook_migration_stats(team_id)


# --- Access control ---


async def acan_user_edit_notebook(team_id: int, short_id: str, *, user_access_control: "UserAccessControl") -> bool:
    return await logic.acan_user_edit_notebook(team_id, short_id, user_access_control)


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
    text_content: str | None = None,
) -> tuple[contracts.NotebookData, bool]:
    notebook, created = await logic.aupsert_notebook(
        team_id,
        short_id,
        created_by_id=created_by_id,
        last_modified_by_id=last_modified_by_id,
        title=title,
        content=content,
        text_content=text_content,
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


def migrate_notebooks_to_markdown(
    *,
    user: "User",
    team_id: int | None = None,
    dry_run: bool = True,
    batch_size: int | None = None,
    max_previews: int = 5,
) -> contracts.MarkdownNotebookMigrationResult:
    return markdown_migration.migrate_notebooks_to_markdown(
        user=user,
        team_id=team_id,
        dry_run=dry_run,
        batch_size=batch_size,
        max_previews=max_previews,
    )


# --- Resource links (groups, accounts) ---


def get_group_notebook_short_id(group_id: int) -> str | None:
    return logic.get_group_notebook_short_id(group_id)


def group_has_notebook(group_id: int) -> bool:
    return logic.group_has_notebook(group_id)


def create_group_notebook(team_id: int, group_id: int, *, title: str | None, content: Any) -> contracts.NotebookData:
    return _to_notebook_data(logic.create_group_notebook(team_id, group_id, title=title, content=content))


def create_account_notebook(
    team_id: int,
    account_id: str | UUID,
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


def list_account_internal_notes(account_id: str | UUID) -> list[contracts.AccountNote]:
    return [
        contracts.AccountNote(title=link.notebook.title, short_id=link.notebook.short_id)
        for link in logic.list_account_internal_notes(account_id)
    ]


def _to_notebook_user(user) -> contracts.NotebookUserInfo | None:
    if user is None:
        return None
    return contracts.NotebookUserInfo(
        id=user.id,
        uuid=user.uuid,
        distinct_id=user.distinct_id,
        first_name=user.first_name,
        last_name=user.last_name,
        email=user.email,
        is_email_verified=user.is_email_verified,
        hedgehog_config=user.hedgehog_config,
        role_at_organization=user.role_at_organization,
    )


def _to_account_notebook(notebook: Notebook) -> contracts.AccountNotebook:
    return contracts.AccountNotebook(
        id=notebook.id,
        short_id=notebook.short_id,
        title=notebook.title,
        content=notebook.content,
        text_content=notebook.text_content,
        created_at=notebook.created_at,
        last_modified_at=notebook.last_modified_at,
        created_by=_to_notebook_user(notebook.created_by),
        last_modified_by=_to_notebook_user(notebook.last_modified_by),
    )


def list_account_notebooks(
    account_id: str | UUID, *, search: str | None = None, order: str | None = None
) -> list[contracts.AccountNotebook]:
    return [
        _to_account_notebook(notebook)
        for notebook in logic.list_account_notebooks(account_id, search=search, order=order)
    ]


def get_account_notebook(account_id: str | UUID, short_id: str) -> contracts.AccountNotebook | None:
    notebook = logic.get_account_notebook(account_id, short_id)
    return _to_account_notebook(notebook) if notebook is not None else None


def delete_account_notebook(account_id: str | UUID, short_id: str) -> bool:
    return logic.delete_account_notebook(account_id, short_id)


def _to_team_account_note(link: ResourceNotebook) -> contracts.TeamAccountNote:
    # The account FK is nullable on the model; the team-notes queryset filters
    # `account__isnull=False`, so narrow for the type checker.
    assert link.account is not None
    return contracts.TeamAccountNote(
        short_id=link.notebook.short_id,
        title=link.notebook.title,
        created_at=link.notebook.created_at,
        last_modified_at=link.notebook.last_modified_at,
        account_id=link.account.id,
        account_name=link.account.name,
        created_by=_to_notebook_user(link.notebook.created_by),
    )


def list_team_account_notes(
    team_id: int,
    *,
    account_ids: Iterable[UUID | str] | None = None,
    account_id: UUID | str | None = None,
    created_by_ids: Iterable[int] | None = None,
    search: str | None = None,
    offset: int = 0,
    limit: int = 100,
) -> tuple[list[contracts.TeamAccountNote], int]:
    links, count = logic.list_team_account_notes(
        team_id,
        account_ids=account_ids,
        account_id=account_id,
        created_by_ids=created_by_ids,
        search=search,
        offset=offset,
        limit=limit,
    )
    return [_to_team_account_note(link) for link in links], count
