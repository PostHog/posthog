"""The email template library: saved templates a workflow email step can start from."""

from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from django.core.exceptions import ObjectDoesNotExist, ValidationError

from posthog.dataclasses import frozen

from products.messaging.backend.models.message_template import MessageTemplate
from products.messaging.backend.services import message_templates as templates_service
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
    )


def list_templates(team_id: int) -> Sequence[MessageTemplateRow]:
    """The team's templates that are not deleted, newest first. Sizing is a COUNT, and a slice reads one page."""
    return LazyList(templates_service.team_templates(team_id), _to_contract)


def get_template(team_id: int, template_id: UUID | str) -> MessageTemplateRow:
    try:
        return _to_contract(templates_service.team_template(team_id, template_id))
    except (MessageTemplate.DoesNotExist, ValidationError, ValueError, TypeError) as e:
        raise MessageTemplateMissing() from e


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


def update_template(team_id: int, template_id: UUID, fields: dict[str, Any]) -> MessageTemplateRow:
    """Set the given fields and save the whole row. `message_category` holds a category id or None."""
    return _to_contract(templates_service.update_template(team_id, template_id, fields))


def edit_template_content(
    team_id: int, template_id: UUID, edit: Callable[[dict[str, Any]], dict[str, Any]]
) -> MessageTemplateRow:
    """Lock the template, replace its content with `edit(content)` and save, in one transaction.

    `edit` gets a copy of the stored content. An exception from it rolls the change back.
    """
    return _to_contract(templates_service.edit_content_locked(team_id, template_id, edit))
