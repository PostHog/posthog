from collections.abc import Callable
from datetime import timedelta
from typing import Any, cast

from django.db import transaction
from django.db.models import QuerySet

from posthog.models import Team, User
from posthog.models.activity_logging.activity_log import changes_between
from posthog.models.comment import Comment
from posthog.models.utils import UUIDT

from products.notebooks.backend import markdown_collab
from products.notebooks.backend.activity_logging import log_notebook_activity
from products.notebooks.backend.facade.contracts import (
    MarkdownNotebookMigrationPreview,
    MarkdownNotebookMigrationResult,
    MarkdownNotebookMigrationStats,
)
from products.notebooks.backend.markdown_conversion import (
    NotebookMarkdownConversionOptions,
    build_markdown_notebook_content,
    convert_notebook_content_to_markdown,
    is_markdown_notebook_content,
    notebook_content_has_comment_marks,
)
from products.notebooks.backend.models import Notebook
from products.notebooks.backend.python_analysis import annotate_python_nodes

MAX_NOTEBOOK_MIGRATION_BATCH_SIZE = 500


def get_markdown_notebook_migration_stats(team_id: int | None = None) -> MarkdownNotebookMigrationStats:
    _validate_team_id(team_id)
    queryset = _notebook_scope(team_id)
    total = queryset.count()
    converted = queryset.filter(content__content__0__type=markdown_collab.MARKDOWN_NOTEBOOK_NODE_TYPE).count()
    return MarkdownNotebookMigrationStats(total=total, converted=converted, pending=total - converted, team_id=team_id)


def migrate_notebooks_to_markdown(
    *,
    user: User,
    team_id: int | None = None,
    dry_run: bool = True,
    batch_size: int | None = None,
    max_previews: int = 5,
) -> MarkdownNotebookMigrationResult:
    batch_size = _validate_batch_size(batch_size)
    stats = get_markdown_notebook_migration_stats(team_id)
    converted = 0
    skipped = 0
    errored = 0
    previews: list[MarkdownNotebookMigrationPreview] = []
    errors: list[str] = []

    queryset = _pending_notebook_scope(team_id).select_related("team").order_by("team_id", "id")
    if batch_size is not None:
        queryset = queryset[:batch_size]

    for notebook in queryset.iterator(chunk_size=100):
        if is_markdown_notebook_content(notebook.content):
            skipped += 1
            continue

        try:
            markdown = convert_notebook_content_to_markdown(
                notebook.content,
                NotebookMarkdownConversionOptions(
                    comment_replies_by_mark_id=_build_comment_replies_by_mark_id(notebook),
                    get_mention_label=_build_mention_label_getter(notebook),
                ),
            )
            next_content = build_markdown_notebook_content(markdown)
            if dry_run:
                converted += 1
                if len(previews) < max_previews:
                    previews.append(
                        MarkdownNotebookMigrationPreview(
                            short_id=str(notebook.short_id),
                            title=notebook.title,
                            before_version=notebook.version,
                            markdown_preview=markdown[:500],
                        )
                    )
                continue

            if _convert_notebook(notebook, user=user, content=next_content, text_content=markdown):
                converted += 1
            else:
                skipped += 1
        except Exception as err:
            errored += 1
            errors.append(f"{notebook.short_id}: {err}")

    final_stats = stats if dry_run else get_markdown_notebook_migration_stats(team_id)
    return MarkdownNotebookMigrationResult(
        dry_run=dry_run,
        team_id=team_id,
        batch_size=batch_size,
        total=stats.total,
        already_converted=stats.converted,
        pending_before=stats.pending,
        pending_after=final_stats.pending,
        converted=converted,
        skipped=skipped,
        errored=errored,
        previews=previews,
        errors=errors[:20],
    )


def _validate_team_id(team_id: int | None) -> None:
    if team_id is not None and not Team.objects.filter(id=team_id).exists():
        raise ValueError(f"Team {team_id} does not exist")


def _validate_batch_size(batch_size: int | None) -> int | None:
    if batch_size is None:
        return None
    if batch_size < 1:
        raise ValueError("Batch size must be at least 1")
    if batch_size > MAX_NOTEBOOK_MIGRATION_BATCH_SIZE:
        raise ValueError(f"Batch size must be {MAX_NOTEBOOK_MIGRATION_BATCH_SIZE} or less")
    return batch_size


def _notebook_scope(team_id: int | None) -> QuerySet[Notebook]:
    queryset = Notebook.objects.all()
    return queryset.filter(team_id=team_id) if team_id is not None else queryset


def _pending_notebook_scope(team_id: int | None) -> QuerySet[Notebook]:
    return _notebook_scope(team_id).exclude(content__content__0__type=markdown_collab.MARKDOWN_NOTEBOOK_NODE_TYPE)


def _convert_notebook(notebook: Notebook, *, user: User, content: dict[str, Any], text_content: str) -> bool:
    with transaction.atomic():
        locked_notebook = Notebook.objects.select_for_update().select_related("team").get(pk=notebook.pk)
        if is_markdown_notebook_content(locked_notebook.content):
            return False

        before_update = Notebook.objects.select_related("created_by", "last_modified_by").get(pk=locked_notebook.pk)
        annotated_content = annotate_python_nodes(content)
        locked_notebook.content = annotated_content
        locked_notebook.text_content = text_content
        locked_notebook.version += 1
        locked_notebook.save(
            update_fields=[
                "content",
                "text_content",
                "version",
            ]
        )

        notify_team_id = locked_notebook.team_id
        notify_notebook_id = str(locked_notebook.short_id)
        notify_version = locked_notebook.version
        transaction.on_commit(
            lambda: markdown_collab.publish_notebook_update(
                notify_team_id,
                notify_notebook_id,
                notify_version,
                diff=None,
            )
        )

    changes = changes_between("Notebook", previous=before_update, current=locked_notebook)
    log_notebook_activity(
        activity="updated",
        notebook=locked_notebook,
        organization_id=cast(UUIDT, locked_notebook.team.organization_id),
        team_id=locked_notebook.team_id,
        user=before_update.last_modified_by or before_update.created_by or user,
        was_impersonated=False,
        changes=changes,
        created_at=before_update.last_modified_at + timedelta(seconds=1),
    )
    return True


def _build_comment_replies_by_mark_id(notebook: Notebook) -> dict[str, list[Any]]:
    if not notebook_content_has_comment_marks(notebook.content):
        return {}

    root_comments = list(
        Comment.objects.filter(team_id=notebook.team_id, scope="Notebook", item_id=notebook.short_id)
        .filter(deleted=False, source_comment_id__isnull=True)
        .select_related("created_by")
        .order_by("created_at")
    )
    root_ids = [comment.id for comment in root_comments]
    replies_by_source_id: dict[Any, list[Comment]] = {comment.id: [] for comment in root_comments}
    if root_ids:
        for reply in (
            Comment.objects.filter(team_id=notebook.team_id, source_comment_id__in=root_ids)
            .filter(deleted=False)
            .select_related("created_by")
            .order_by("created_at")
        ):
            if isinstance(reply.item_context, dict) and reply.item_context.get("is_emoji"):
                continue
            replies_by_source_id.setdefault(reply.source_comment_id, []).append(reply)

    replies_by_mark_id: dict[str, list[Any]] = {}
    for comment in root_comments:
        item_context = comment.item_context
        mark_id = (
            item_context.get("id") if isinstance(item_context, dict) and item_context.get("type") == "mark" else None
        )
        if not isinstance(mark_id, str):
            continue
        thread = sorted([comment, *replies_by_source_id.get(comment.id, [])], key=lambda item: item.created_at)
        replies_by_mark_id[mark_id] = [_comment_to_reply(comment) for comment in thread]
    return replies_by_mark_id


def _comment_to_reply(comment: Comment) -> dict[str, Any]:
    author = None
    if comment.created_by:
        author = comment.created_by.first_name or comment.created_by.email
    return {
        "id": str(comment.id),
        "text": comment.content or "",
        **({"author": author} if author else {}),
        **({"authorId": comment.created_by_id} if comment.created_by_id else {}),
        "at": comment.created_at.isoformat(),
    }


def _build_mention_label_getter(notebook: Notebook) -> Callable[[int], str | None]:
    user_ids = _collect_mention_user_ids(notebook.content)
    if not user_ids:
        return lambda user_id: None

    users = User.objects.filter(
        id__in=user_ids,
        organization_membership__organization_id=notebook.team.organization_id,
    ).only("id", "first_name", "email")
    labels_by_user_id = {
        user.id: f"@{user.first_name or user.email}" for user in users if user.first_name or user.email
    }
    return lambda user_id: labels_by_user_id.get(user_id)


def _collect_mention_user_ids(content: Any) -> set[int]:
    user_ids: set[int] = set()

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("type") == "ph-mention":
                attrs = node.get("attrs")
                user_id = attrs.get("id") if isinstance(attrs, dict) else None
                if isinstance(user_id, int):
                    user_ids.add(user_id)
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for child in node:
                visit(child)

    visit(content)
    return user_ids
