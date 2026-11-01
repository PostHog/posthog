from collections.abc import Callable
from typing import Any
from uuid import UUID

from django.db import transaction

from products.messaging.backend.models import MessageTemplate
from products.messaging.backend.services.message_templates import apply_fields, replace_changed_tags, templates_of
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
    with transaction.atomic():
        template = MessageTemplate.objects.select_for_update().get(team_id=team_id, id=template_id, deleted=False)
        if template.transactional_hog_flow_id:
            require_workflow_editor(template.transactional_hog_flow_id)
        write(template)
        save_locked_template(template, user_id=user_id)
    return template


def save_fields(
    team_id: int,
    template_id: UUID,
    fields: dict[str, Any],
    *,
    user_id: int | None,
    require_workflow_editor: WorkflowEditorCheck,
) -> MessageTemplate:
    fields = dict(fields)
    tags = fields.pop("tags", None)
    with transaction.atomic():
        template = save_template(
            team_id,
            template_id,
            lambda locked: apply_fields(locked, fields),
            user_id=user_id,
            require_workflow_editor=require_workflow_editor,
        )
        replace_changed_tags(template, tags)
    return template


def save_locked_template(template: MessageTemplate, *, user_id: int | None) -> None:
    syncs_workflow = template.transactional_hog_flow_id is not None and not template.deleted
    if syncs_workflow:
        check_still_sendable(template)
    template.save()
    if syncs_workflow:
        sync_transactional_workflow(template.team_id, template.id, user_id=user_id)
        template.refresh_from_db()


def rewrite_content(
    template_id: UUID, rewrite: Callable[[Any], tuple[Any, int]], *, team_ids: list[int] | None, dry_run: bool
) -> int:
    with transaction.atomic():
        templates = templates_of(team_ids)
        template = templates.get(pk=template_id) if dry_run else templates.select_for_update().get(pk=template_id)
        new_content, content_occurrences = rewrite(template.content)
        new_draft, draft_occurrences = rewrite(template.draft_content)
        template.draft_content = new_draft
        if dry_run:
            return content_occurrences + draft_occurrences
        if content_occurrences:
            template.content = new_content
            save_locked_template(template, user_id=None)
        elif draft_occurrences:
            template.save(update_fields=["draft_content", "updated_at"])
    return content_occurrences + draft_occurrences
