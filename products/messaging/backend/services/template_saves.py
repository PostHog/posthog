"""The one path that saves a template's content. Sends use the workflow's copy of the content, so the template, its
content hash and the new version of its transactional workflow are written in one transaction, under the template's
row lock. The lock keeps a concurrent make_transactional from linking a workflow in between."""

from collections.abc import Callable
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
    """Apply `write` to the locked template and save it. An exception from `write` or from the workflow sync rolls
    the whole save back, so the template and its workflow never disagree. Raises TemplateManagedByCode when the
    locked template refuses `intent`."""
    with transaction.atomic():
        template = lock_template(team_id, template_id)
        check_write(template, intent)
        save_locked_template(template, write, user_id=user_id, require_workflow_editor=require_workflow_editor)
    return template


def release_template(
    team_id: int, template_id: UUID, *, require_workflow_editor: WorkflowEditorCheck
) -> MessageTemplate:
    """Hand a template managed by code back to PostHog. It keeps its key, so the next upload claims it again. The
    content and the workflow stay as they are."""
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
    """`save_template` for a template the caller locked in its own transaction."""
    hog_flow_id = template.transactional_hog_flow_id
    # The template's own access rules don't cover the workflow it sends through, which can carry its own.
    if hog_flow_id:
        require_workflow_editor(hog_flow_id)
    write(template)
    syncs_workflow = hog_flow_id is not None and not template.deleted
    if syncs_workflow:
        check_still_sendable(template)
    record_content_hash(template)
    template.save()
    if syncs_workflow:
        sync_transactional_workflow(template.team_id, template.id, user_id=user_id)
        # The sync unlinks the template when its workflow was deleted.
        template.refresh_from_db()
