"""The email template library: saved templates a workflow email step can start from."""

from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from django.core.exceptions import ObjectDoesNotExist, ValidationError

from posthog.dataclasses import frozen

from products.messaging.backend.facade.contracts import (
    ContentHashState,
    TemplateChangePrompt,
    TemplateManagedBy,
    TemplateReference,
    TemplateUpload,
    TemplateUploadResult,
    TemplateWriteIntent,
)
from products.messaging.backend.models.message_template import MessageTemplate
from products.messaging.backend.services import (
    message_templates as templates_service,
    template_change_prompt,
    template_keys,
    template_ownership,
    template_saves,
    template_uploads,
)
from products.messaging.backend.services.content_hash import sent_hash_state
from products.messaging.backend.services.lazy_list import LazyList


class MessageTemplateMissing(Exception):
    """The team has no template with that id that is not deleted, or the id is not a UUID."""


class MessageCategoryNotInTeam(Exception):
    """The team has no category with that id."""


@frozen
class MessageTemplateRow:
    id: UUID
    name: str
    description: str
    created_at: datetime
    updated_at: datetime
    content: dict[str, Any]
    created_by_id: int | None
    type: str
    message_category_id: UUID | None
    deleted: bool
    transactional_hog_flow_id: UUID | None
    key: str | None
    managed_by: TemplateManagedBy | None
    source_repository: str | None
    source_path: str | None
    source_ref: str | None
    content_hash: str | None


@frozen
class UploadedTemplate:
    result: TemplateUploadResult
    template: MessageTemplateRow


@frozen
class TemplateToSend:
    template: MessageTemplateRow
    hash_state: ContentHashState


def _to_contract(row: MessageTemplate) -> MessageTemplateRow:
    return MessageTemplateRow(
        id=row.id,
        name=row.name,
        description=row.description,
        created_at=row.created_at,
        updated_at=row.updated_at,
        content=row.content,
        created_by_id=row.created_by_id,
        type=row.type,
        message_category_id=row.message_category_id,
        deleted=row.deleted,
        transactional_hog_flow_id=row.transactional_hog_flow_id,
        key=row.key,
        managed_by=TemplateManagedBy(row.managed_by) if row.managed_by else None,
        source_repository=row.source_repository,
        source_path=row.source_path,
        source_ref=row.source_ref,
        content_hash=row.content_hash,
    )


def list_templates(team_id: int) -> Sequence[MessageTemplateRow]:
    """The team's templates that are not deleted, newest first. Sizing is a COUNT, and a slice reads one page."""
    return LazyList(templates_service.team_templates(team_id), _to_contract)


def get_template(team_id: int, template_id: UUID | str) -> MessageTemplateRow:
    try:
        return _to_contract(templates_service.team_template(team_id, template_id))
    except (MessageTemplate.DoesNotExist, ValidationError, ValueError, TypeError) as e:
        raise MessageTemplateMissing() from e


def find_template_to_send(team_id: int, reference: TemplateReference) -> TemplateToSend:
    """The template a send names, and how the hash the send carries compares with its published content.

    Raises MessageTemplateMissing when the team has no template with that key or id that is not deleted.
    """
    try:
        template = _referenced_template(team_id, reference)
    except (MessageTemplate.DoesNotExist, ValidationError, ValueError, TypeError) as e:
        raise MessageTemplateMissing() from e
    hash_state = sent_hash_state(reference.hash, template.content_hash, template.superseded_content_hashes or [])
    return TemplateToSend(template=_to_contract(template), hash_state=hash_state)


def _referenced_template(team_id: int, reference: TemplateReference) -> MessageTemplate:
    if reference.key is not None:
        return templates_service.team_template_with_key(team_id, reference.key)
    if reference.id is not None:
        return templates_service.team_template(team_id, reference.id)
    raise MessageTemplate.DoesNotExist()


def team_category_id(team_id: int, category_id: Any) -> UUID:
    """The id of the team's category with that pk, deleted or not.

    Raises MessageCategoryNotInTeam when there is none. A value that is not a UUID raises Django's
    ValidationError, and a value of the wrong type raises TypeError or ValueError.
    """
    try:
        return templates_service.category_id_for_team(team_id, category_id)
    except ObjectDoesNotExist as e:
        raise MessageCategoryNotInTeam() from e


def create_template(team_id: int, created_by_id: int | None, fields: dict[str, Any]) -> MessageTemplateRow:
    """Create a template from validated fields. `message_category` holds a category id or None."""
    return _to_contract(templates_service.create_template(team_id, created_by_id, fields))


def save_template_fields(
    team_id: int,
    template_id: UUID,
    fields: dict[str, Any],
    *,
    intent: TemplateWriteIntent,
    user_id: int | None,
    require_workflow_editor: Callable[[UUID], None],
) -> MessageTemplateRow:
    """Set validated fields and save the template with its workflow. `message_category` holds a category id or None.

    Raises TransactionalEmailError when the template could no longer send, and TemplateManagedByCode when the template
    refuses `intent`. `require_workflow_editor` gets the id of the template's workflow, under the row lock, and raises
    to refuse the save.
    """
    return _to_contract(
        template_saves.save_template(
            team_id,
            template_id,
            lambda template: templates_service.apply_fields(template, fields),
            intent=intent,
            user_id=user_id,
            require_workflow_editor=require_workflow_editor,
        )
    )


def save_template_content(
    team_id: int,
    template_id: UUID,
    edit: Callable[[dict[str, Any]], dict[str, Any]],
    *,
    intent: TemplateWriteIntent,
    user_id: int | None,
    require_workflow_editor: Callable[[UUID], None],
) -> MessageTemplateRow:
    """Replace the template's content with `edit(content)` and save it as `save_template_fields` does.

    `edit` gets a copy of the stored content, under the row lock. An exception from it rolls the change back.
    """
    return _to_contract(
        template_saves.save_template(
            team_id,
            template_id,
            lambda template: templates_service.edit_content(template, edit),
            intent=intent,
            user_id=user_id,
            require_workflow_editor=require_workflow_editor,
        )
    )


def check_template_write(template: MessageTemplateRow, intent: TemplateWriteIntent) -> None:
    """Raise TemplateManagedByCode when the template is managed by code and refuses `intent`."""
    template_ownership.check_write(template, intent)


def change_prompt(team_id: int, template: MessageTemplateRow) -> TemplateChangePrompt | None:
    """The starter sentence and the "About this file" block for a template managed by code. None for any other."""
    return template_change_prompt.change_prompt(team_id, template)


def is_release(intent: TemplateWriteIntent) -> bool:
    """Whether `intent` hands a template managed by code back to PostHog."""
    return template_ownership.is_release(intent)


def release_template(
    team_id: int, template_id: UUID, *, require_workflow_editor: Callable[[UUID], None]
) -> MessageTemplateRow:
    """Hand the template back to PostHog, so it takes edits again. It keeps its key, so the next upload claims it."""
    return _to_contract(
        template_saves.release_template(team_id, template_id, require_workflow_editor=require_workflow_editor)
    )


def is_adoption(intent: TemplateWriteIntent) -> bool:
    """Whether `intent` gives a template its key: a PATCH whose only field is `key`."""
    return template_keys.is_adoption(intent)


def check_template_key_write(template: MessageTemplateRow, intent: TemplateWriteIntent) -> None:
    """Raise TemplateKeyRefused when `intent` is not an adoption and sets or changes the template's key."""
    template_keys.check_key_unchanged(template, intent)


def adopt_template(
    team_id: int,
    template_id: UUID,
    key: str,
    *,
    intent: TemplateWriteIntent,
    require_workflow_editor: Callable[[UUID], None],
) -> MessageTemplateRow:
    """Give a template that has no key the key `key`, so the next upload under it takes the template over.

    Raises TemplateKeyRefused when the template already has a key or another template has this one, and
    TemplateManagedByCode when the template refuses `intent`.
    """
    return _to_contract(
        template_keys.adopt_template(
            team_id, template_id, key, intent=intent, require_workflow_editor=require_workflow_editor
        )
    )


def upload_template(
    team_id: int,
    upload: TemplateUpload,
    *,
    user_id: int | None,
    require_workflow_editor: Callable[[UUID], None],
    require_workflow_create: Callable[[], None],
) -> UploadedTemplate:
    """Create the template with the upload's key, or publish the upload as its content.

    The first upload makes the template transactional with the default verified sender, and writes nothing when
    there is none. Raises TransactionalEmailError when the template can't send. `require_workflow_create` runs
    before a new workflow is made, and raises to refuse the upload.
    """
    uploaded = template_uploads.upload_template(
        team_id,
        upload,
        user_id=user_id,
        require_workflow_editor=require_workflow_editor,
        require_workflow_create=require_workflow_create,
    )
    return UploadedTemplate(result=uploaded.result, template=_to_contract(uploaded.template))
