"""The one path that saves a template's content. Sends use the workflow's copy of the content, so the template and
the new version of its transactional workflow are written in one transaction, under the template's row lock. The
lock keeps a concurrent make_transactional from linking a workflow in between."""

from collections.abc import Callable
from typing import Any
from uuid import UUID

from django.db import transaction

from products.messaging.backend.models import MessageTemplate
from products.messaging.backend.services.message_templates import templates_of
from products.messaging.backend.services.transactional_email import check_still_sendable, sync_transactional_workflow

TemplateWrite = Callable[[MessageTemplate], None]
WorkflowEditorCheck = Callable[[UUID], None]


def save_template(
    team_id: int,
    template_id: UUID,
    write: TemplateWrite,
    *,
    user_id: int | None,
    require_workflow_editor: WorkflowEditorCheck,
) -> MessageTemplate:
    """Apply `write` to the locked template and save it. An exception from `write` or from the workflow sync rolls
    the whole save back, so the template and its workflow never disagree."""
    with transaction.atomic():
        template = lock_template(team_id, template_id)
        save_locked_template(template, write, user_id=user_id, require_workflow_editor=require_workflow_editor)
    return template


def lock_template(team_id: int, template_id: UUID) -> MessageTemplate:
    return MessageTemplate.objects.select_for_update().get(team_id=team_id, id=template_id, deleted=False)


def save_locked_template(
    template: MessageTemplate,
    write: TemplateWrite,
    *,
    user_id: int | None,
    require_workflow_editor: WorkflowEditorCheck,
) -> None:
    """`save_template` for a template the caller locked in its own transaction."""
    hog_flow_id = template.transactional_hog_flow_id
    # The template's own access rules don't cover the workflow it sends through, which can carry its own.
    if hog_flow_id:
        require_workflow_editor(hog_flow_id)
    write(template)
    syncs_workflow = hog_flow_id is not None and not template.deleted
    if syncs_workflow:
        check_still_sendable(template)
    template.save()
    if syncs_workflow:
        sync_transactional_workflow(template.team_id, template.id, user_id=user_id)
        # The sync unlinks the template when its workflow was deleted.
        template.refresh_from_db()


def rewrite_content(
    template_id: UUID, rewrite: Callable[[Any], tuple[Any, int]], *, team_ids: list[int] | None, dry_run: bool
) -> int:
    """Apply `rewrite` to a template's content, deleted or not, and save it with its workflow. Returns the number of
    occurrences it replaced."""
    if dry_run:
        return rewrite(templates_of(team_ids).get(pk=template_id).content)[1]

    with transaction.atomic():
        # Read the row again under the lock, so a concurrent save is not overwritten with a stale blob.
        template = templates_of(team_ids).select_for_update().get(pk=template_id)
        new_content, occurrences = rewrite(template.content)
        if occurrences:
            save_locked_template(
                template,
                lambda locked: setattr(locked, "content", new_content),
                user_id=None,
                require_workflow_editor=_operators_edit_every_workflow,
            )
    return occurrences


def _operators_edit_every_workflow(_hog_flow_id: UUID) -> None:
    pass
