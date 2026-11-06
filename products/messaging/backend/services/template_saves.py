from collections.abc import Callable
from typing import Any
from uuid import UUID

from django.db import transaction

from products.messaging.backend.facade.contracts import TemplateManagedBy, TemplateWriteIntent
from products.messaging.backend.models import MessageTemplate
from products.messaging.backend.services.message_templates import record_content_hash
from products.messaging.backend.services.template_ownership import check_write
from products.messaging.backend.services.transactional_email import check_still_sendable, sync_transactional_workflow

TemplateWrite = Callable[[MessageTemplate], None]
WorkflowEditorCheck = Callable[[UUID], None]


def save_template(
    team_id: int,
    template_id: UUID,
    write: TemplateWrite,
    *,
    intent: TemplateWriteIntent,
    user_id: int | None,
    require_workflow_editor: WorkflowEditorCheck,
) -> MessageTemplate:
    with transaction.atomic():
        template = lock_template(team_id, template_id)
        check_write(template, intent)
        save_locked_template(template, write, user_id=user_id, require_workflow_editor=require_workflow_editor)
    return template


def save_locked_draft(
    team_id: int,
    template_id: UUID,
    draft: dict[str, Any] | None,
    *,
    intent: TemplateWriteIntent,
    require_workflow_editor: WorkflowEditorCheck,
) -> MessageTemplate:
    with transaction.atomic():
        template = lock_template(team_id, template_id)
        check_write(template, intent)
        if template.transactional_hog_flow_id:
            require_workflow_editor(template.transactional_hog_flow_id)
        template.draft_content = draft
        template.save(update_fields=["draft_content", "updated_at"])
    return template


def release_template(
    team_id: int, template_id: UUID, *, require_workflow_editor: WorkflowEditorCheck
) -> MessageTemplate:
    with transaction.atomic():
        template = lock_template(team_id, template_id)
        if template.transactional_hog_flow_id:
            require_workflow_editor(template.transactional_hog_flow_id)
        if template.managed_by == TemplateManagedBy.CODE:
            template.managed_by = TemplateManagedBy.GUI
            template.save(update_fields=["managed_by", "updated_at"])
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
    hog_flow_id = template.transactional_hog_flow_id
    if hog_flow_id:
        require_workflow_editor(hog_flow_id)
    write(template)
    syncs_workflow = hog_flow_id is not None and not template.deleted
    if syncs_workflow:
        check_still_sendable(template)
    record_content_hash(template)
    template.save()
    if syncs_workflow:
        _sync_workflow_and_reread_its_link(template, user_id=user_id)


def _sync_workflow_and_reread_its_link(template: MessageTemplate, *, user_id: int | None) -> None:
    sync_transactional_workflow(template.team_id, template.id, user_id=user_id)
    template.refresh_from_db()
