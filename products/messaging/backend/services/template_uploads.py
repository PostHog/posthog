"""Upload a template from code by its key: create it on the first upload, publish changed content after that."""

from collections.abc import Callable
from typing import Any

from django.db import IntegrityError, transaction

from products.messaging.backend.facade.contracts import (
    SenderUnavailable,
    TemplateManagedBy,
    TemplateSource,
    TemplateUpload,
    TemplateUploadResult,
)
from products.messaging.backend.models import MessageTemplate
from products.messaging.backend.services.content_hash import HASHED_FIELDS
from products.messaging.backend.services.message_templates import record_content_hash
from products.messaging.backend.services.template_saves import WorkflowEditorCheck, save_locked_template
from products.messaging.backend.services.transactional_email import is_transactional, make_transactional

KEY_CONSTRAINT = "unique_message_template_key_per_team"
SOURCE_PARTS = ("repository", "path", "ref")

WorkflowCreateCheck = Callable[[], None]


def upload_template(
    team_id: int,
    upload: TemplateUpload,
    *,
    user_id: int | None,
    require_workflow_editor: WorkflowEditorCheck,
    require_workflow_create: WorkflowCreateCheck,
) -> tuple[TemplateUploadResult, MessageTemplate]:
    def attempt() -> tuple[TemplateUploadResult, MessageTemplate]:
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
        if KEY_CONSTRAINT not in str(error):
            raise
    # A concurrent first upload created the template after this one looked for it. This one updates it.
    return attempt()


def _upload(
    team_id: int,
    upload: TemplateUpload,
    *,
    user_id: int | None,
    require_workflow_editor: WorkflowEditorCheck,
    require_workflow_create: WorkflowCreateCheck,
) -> tuple[TemplateUploadResult, MessageTemplate]:
    template = locked_template_with_key(team_id, upload.key)
    if template is None:
        require_workflow_create()
        return TemplateUploadResult.CREATED, _create(team_id, upload, user_id=user_id)
    if _is_unchanged(template, upload):
        _save_source(template, upload.source)
        return TemplateUploadResult.UNCHANGED, template
    save_locked_template(
        template,
        lambda locked: _write_upload(locked, upload),
        user_id=user_id,
        require_workflow_editor=require_workflow_editor,
    )
    if not template.transactional_hog_flow_id:
        # An adopted template, or one whose workflow was deleted.
        require_workflow_create()
        _make_transactional(template, user_id=user_id)
    return TemplateUploadResult.UPDATED, template


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
        raise SenderUnavailable(
            "The project has no verified default email sender. Verify a sending domain, set it as the default "
            "sender, and upload again."
        ) from error
    template.refresh_from_db()


def _write_upload(template: MessageTemplate, upload: TemplateUpload) -> None:
    template.name = upload.name
    template.type = "email"
    template.managed_by = TemplateManagedBy.CODE
    template.content = {**(template.content or {}), "templating": "liquid", "email": _email(upload)}
    _write_source(template, upload.source)


def _email(upload: TemplateUpload) -> dict[str, Any]:
    return {
        "subject": upload.subject,
        "preheader": upload.preheader,
        "html": upload.html,
        "text": upload.text,
        "design": upload.design,
    }


def _is_unchanged(template: MessageTemplate, upload: TemplateUpload) -> bool:
    email = (template.content or {}).get("email") or {}
    uploaded = _email(upload)
    return (
        template.name == upload.name
        and all((email.get(field) or "") == uploaded[field] for field in HASHED_FIELDS)
        and template.managed_by == TemplateManagedBy.CODE
        and is_transactional(template)
    )


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
    # Metadata only: the content and the workflow stay as they are.
    changed = _write_source(template, source)
    if changed:
        template.save(update_fields=changed)
