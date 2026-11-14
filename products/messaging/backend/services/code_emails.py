"""Emails sent from code under a `template_key` that no template owns. Each key has a hidden workflow, which holds the
description and tags people add, while the key's own row holds the link to the file that sends it."""

from collections.abc import Callable, Collection
from typing import Any
from uuid import UUID

from django.db import models

from products.messaging.backend.facade.contracts import (
    CodeEmailSourceOrigin,
    CodeManagedEmail,
    CodeManagedEmailNotFound,
)
from products.messaging.backend.models import MessageTemplate, TransactionalEmailKey
from products.workflows.backend.facade.transactional_emails import (
    CodeEmailWorkflow,
    get_code_email_workflows,
    update_code_email_labels,
)

# Takes candidate workflow ids and returns the ones the reader may view.
ViewableWorkflows = Callable[[Collection[str]], Collection[str]]


def _keys(team_id: int) -> models.QuerySet[TransactionalEmailKey]:
    # A template that takes a key over gets its sends, so the key no longer sends as code.
    template_keys = MessageTemplate.objects.filter(team_id=team_id, deleted=False, key__isnull=False).values("key")
    return TransactionalEmailKey.objects.for_team(team_id, canonical=True).exclude(key__in=template_keys)


def _viewable(keys: list[TransactionalEmailKey], viewable_workflows: ViewableWorkflows) -> list[TransactionalEmailKey]:
    viewable = viewable_workflows([str(key.hog_flow_id) for key in keys]) if keys else ()
    return [key for key in keys if str(key.hog_flow_id) in viewable]


def _code_emails(team_id: int, keys: list[TransactionalEmailKey]) -> list[CodeManagedEmail]:
    workflows = get_code_email_workflows(team_id=team_id, workflow_ids=[key.hog_flow_id for key in keys])
    return [_code_email(key, workflows[key.hog_flow_id]) for key in keys if key.hog_flow_id in workflows]


def _code_email(key: TransactionalEmailKey, workflow: CodeEmailWorkflow) -> CodeManagedEmail:
    return CodeManagedEmail(
        id=key.id,
        key=key.key,
        hog_flow_id=key.hog_flow_id,
        description=workflow.description,
        tags=workflow.tags,
        sensitive=workflow.sensitive,
        source_url=key.source_url,
        source_origin=_source_origin(key),
        created_at=key.created_at,
    )


def _source_origin(key: TransactionalEmailKey) -> CodeEmailSourceOrigin | None:
    if key.source_origin:
        return CodeEmailSourceOrigin(key.source_origin)
    # Keys linked before source_origin existed have a link and no origin, and only a person could set those links.
    return CodeEmailSourceOrigin.MANUAL if key.source_url else None


def list_code_emails(team_id: int, *, viewable_workflows: ViewableWorkflows) -> list[CodeManagedEmail]:
    """The project's code emails whose workflow the reader may view, newest first."""
    return _code_emails(team_id, _viewable(list(_keys(team_id).order_by("-created_at")), viewable_workflows))


def get_code_email(team_id: int, code_email_id: UUID, *, viewable_workflows: ViewableWorkflows) -> CodeManagedEmail:
    emails = _code_emails(team_id, _viewable(list(_keys(team_id).filter(id=code_email_id)[:1]), viewable_workflows))
    if not emails:
        raise CodeManagedEmailNotFound()
    return emails[0]


def update_code_email(
    team_id: int, code_email_id: UUID, fields: dict[str, Any], *, viewable_workflows: ViewableWorkflows
) -> CodeManagedEmail:
    email = get_code_email(team_id, code_email_id, viewable_workflows=viewable_workflows)
    if "description" in fields or "tags" in fields:
        update_code_email_labels(
            team_id=team_id,
            workflow_id=email.hog_flow_id,
            description=fields.get("description"),
            tags=fields.get("tags"),
        )
    if "source_url" in fields:
        _keys(team_id).filter(id=code_email_id).update(
            source_url=fields["source_url"], source_origin=CodeEmailSourceOrigin.MANUAL
        )
    return get_code_email(team_id, code_email_id, viewable_workflows=viewable_workflows)
