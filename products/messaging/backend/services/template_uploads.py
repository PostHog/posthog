from collections.abc import Callable
from typing import Any

from django.db import IntegrityError, transaction

from posthog.dataclasses import frozen

from products.messaging.backend.facade.contracts import (
    ContentHashState,
    SenderUnavailable,
    TemplateManagedBy,
    TemplateSource,
    TemplateUpload,
    TemplateUploadResult,
    TransactionalEmailPaused,
)
from products.messaging.backend.models import MessageTemplate
from products.messaging.backend.models.message_template import KEY_CONSTRAINT
from products.messaging.backend.services.content_hash import email_content_hash, sent_hash_state
from products.messaging.backend.services.message_templates import record_content_hash
from products.messaging.backend.services.template_saves import WorkflowEditorCheck, save_locked_template
from products.messaging.backend.services.transactional_email import (
    is_transactional,
    known_key,
    make_transactional,
    transactional_email_content,
)
from products.workflows.backend.facade.transactional_emails import (
    code_sends_paused,
    transactional_email_workflow_matches,
)

SOURCE_PARTS = ("repository", "path", "ref")

WorkflowCreateCheck = Callable[[], None]


@frozen
class Uploaded:
    result: TemplateUploadResult
    template: MessageTemplate


def upload_template(
    team_id: int,
    upload: TemplateUpload,
    *,
    user_id: int | None,
    require_workflow_editor: WorkflowEditorCheck,
    require_workflow_create: WorkflowCreateCheck,
) -> Uploaded:
    def attempt() -> Uploaded:
        with transaction.atomic():
            return _upload(
                team_id,
                upload,
                user_id=user_id,
                require_workflow_editor=require_workflow_editor,
                require_workflow_create=require_workflow_create,
            )

    try:
        return attempt()
    except IntegrityError as error:
        if not _another_upload_created_the_key_first(error):
            raise
    return attempt()


def _another_upload_created_the_key_first(error: IntegrityError) -> bool:
    return KEY_CONSTRAINT in str(error)


def _upload(
    team_id: int,
    upload: TemplateUpload,
    *,
    user_id: int | None,
    require_workflow_editor: WorkflowEditorCheck,
    require_workflow_create: WorkflowCreateCheck,
) -> Uploaded:
    template = locked_template_with_key(team_id, upload.key)
    if template is None or template.managed_by is None:
        _require_the_key_workflow_can_be_taken_over(team_id, upload.key, require_workflow_editor)
    if template is None:
        require_workflow_create()
        return Uploaded(result=TemplateUploadResult.CREATED, template=_create(team_id, upload, user_id=user_id))
    if template.transactional_hog_flow_id:
        require_workflow_editor(template.transactional_hog_flow_id)
    if upload.if_not_superseded and _is_superseded(template, upload):
        return Uploaded(result=TemplateUploadResult.SUPERSEDED, template=template)
    if _is_unchanged(template, upload):
        _save_source(template, upload.source)
        return Uploaded(result=TemplateUploadResult.UNCHANGED, template=template)
    save_locked_template(
        template,
        lambda locked: _write_upload(locked, upload),
        user_id=user_id,
        require_workflow_editor=require_workflow_editor,
    )
    adopted_or_lost_its_workflow = not template.transactional_hog_flow_id
    if adopted_or_lost_its_workflow:
        require_workflow_create()
        _make_transactional(template, user_id=user_id)
    return Uploaded(result=TemplateUploadResult.UPDATED, template=template)


def _require_the_key_workflow_can_be_taken_over(
    team_id: int, key: str, require_workflow_editor: WorkflowEditorCheck
) -> None:
    key_workflow = known_key(team_id, key)
    if key_workflow is None:
        return
    require_workflow_editor(key_workflow.hog_flow_id)
    if code_sends_paused(team_id, key_workflow.hog_flow_id):
        raise TransactionalEmailPaused(
            f"Code sends under this key are paused, so an upload can't take them over. Resume their workflow "
            f"`{key_workflow.hog_flow_id}`, then upload again."
        )


def locked_template_with_key(team_id: int, key: str) -> MessageTemplate | None:
    return MessageTemplate.objects.select_for_update().filter(team_id=team_id, key=key, deleted=False).first()


def _create(team_id: int, upload: TemplateUpload, *, user_id: int | None) -> MessageTemplate:
    template = MessageTemplate(team_id=team_id, created_by_id=user_id, key=upload.key)
    _write_upload(template, upload)
    record_content_hash(template)
    template.save(force_insert=True)
    _make_transactional(template, user_id=user_id)
    return template


def _make_transactional(template: MessageTemplate, *, user_id: int | None) -> None:
    try:
        make_transactional(template.team_id, template.id, user_id=user_id, from_integration_id=None)
    except SenderUnavailable as error:
        raise SenderUnavailable(_sender_unavailable_message(template)) from error
    template.refresh_from_db()


def _sender_unavailable_message(template: MessageTemplate) -> str:
    sender = ((template.content or {}).get("email") or {}).get("from")
    if isinstance(sender, dict) and sender.get("integrationId"):
        return (
            "The template's email sender isn't verified. Verify its sending domain, or pick a verified sender for "
            "the template in PostHog, and upload again."
        )
    return (
        "The project has no verified default email sender. Verify a sending domain, set it as the default "
        "sender, and upload again."
    )


def _write_upload(template: MessageTemplate, upload: TemplateUpload) -> None:
    template.name = upload.name
    template.type = "email"
    template.managed_by = TemplateManagedBy.CODE
    content = template.content or {}
    stored_email = content.get("email") or {}
    template.content = {**content, "templating": "liquid", "email": {**stored_email, **_email(upload)}}
    _discard_draft_the_upload_makes_stale(template)
    _write_source(template, upload.source)


def _discard_draft_the_upload_makes_stale(template: MessageTemplate) -> None:
    template.draft_content = None


def _email(upload: TemplateUpload) -> dict[str, Any]:
    return {
        "subject": upload.subject,
        "preheader": upload.preheader,
        "html": upload.html,
        "text": upload.text,
        "design": upload.design,
    }


def _is_unchanged(template: MessageTemplate, upload: TemplateUpload) -> bool:
    stored_email = (template.content or {}).get("email") or {}
    uploaded_hash = email_content_hash(_email(upload))
    return (
        template.name == upload.name
        and email_content_hash(stored_email) == uploaded_hash
        and template.content_hash == uploaded_hash
        and template.managed_by == TemplateManagedBy.CODE
        and is_transactional(template)
        and _workflow_sends_the_template(template)
    )


def _workflow_sends_the_template(template: MessageTemplate) -> bool:
    if template.transactional_hog_flow_id is None:
        return False
    return transactional_email_workflow_matches(
        template.team_id, template.transactional_hog_flow_id, transactional_email_content(template)
    )


def _is_superseded(template: MessageTemplate, upload: TemplateUpload) -> bool:
    uploaded_hash = email_content_hash(_email(upload))
    state = sent_hash_state(uploaded_hash, template.content_hash, template.superseded_content_hashes or [])
    return state == ContentHashState.SUPERSEDED


def _write_source(template: MessageTemplate, source: TemplateSource | None) -> list[str]:
    changed: list[str] = []
    for part in SOURCE_PARTS:
        value = getattr(source, part) if source else None
        field = f"source_{part}"
        if value is not None and getattr(template, field) != value:
            setattr(template, field, value)
            changed.append(field)
    return changed


def _save_source(template: MessageTemplate, source: TemplateSource | None) -> None:
    changed = _write_source(template, source)
    if changed:
        template.save(update_fields=[*changed, "updated_at"])
