"""Transactional emails: a template made sendable over the API. Each one is backed by a workflow that runs once
per send, so sends get the workflow's metrics, run history and versions."""

from uuid import UUID

from django.db import transaction

from products.messaging.backend.facade.contracts import MarketingTemplate, SenderUnavailable, TemplateNotSendable
from products.messaging.backend.models import MessageCategory, MessageTemplate
from products.messaging.backend.models.message_category import MessageCategoryType
from products.workflows.backend.facade.api import WorkflowNotFound, get_workflow_summary
from products.workflows.backend.facade.transactional_emails import (
    TransactionalEmailContent,
    TransactionalEmailSenderUnavailable,
    create_transactional_email_workflow,
)


def check_sendable(team_id: int, *, template_type: str, content: dict, message_category_id: UUID | None) -> None:
    """Raise when a template with these fields can't be a transactional email."""
    email = (content or {}).get("email")
    if template_type != "email" or not isinstance(email, dict) or not email.get("subject"):
        raise TemplateNotSendable("The template has no email subject, so it can't be sent.")
    if not (email.get("text") or email.get("html")):
        raise TemplateNotSendable("The template has no email body, so it can't be sent.")
    if message_category_id:
        # A deleted category still classifies the template, and the category field accepts one.
        category = MessageCategory.objects.filter(team_id=team_id, id=message_category_id).first()
        # Transactional sends skip opt-outs, so a marketing template must never go out this way.
        if category and category.category_type == MessageCategoryType.MARKETING:
            raise MarketingTemplate(
                "The template is in a marketing category. Only transactional templates can be sent."
            )


def _content(template: MessageTemplate, from_integration_id: int | None) -> TransactionalEmailContent:
    email = template.content["email"]
    return TransactionalEmailContent(
        message_template_id=template.id,
        name=template.name,
        subject=email["subject"],
        preheader=email.get("preheader") or "",
        html=email.get("html") or "",
        text=email.get("text") or "",
        from_integration_id=from_integration_id,
        message_category_id=template.message_category_id,
    )


def make_transactional(
    team_id: int, template_id: UUID, *, user_id: int | None, from_integration_id: int | None
) -> UUID:
    """Create the template's workflow and link it, and return the workflow's id. A template that is already
    transactional keeps the workflow it has."""
    with transaction.atomic():
        # The row lock keeps two concurrent calls from creating two workflows.
        template = MessageTemplate.objects.select_for_update().get(team_id=team_id, id=template_id, deleted=False)
        if template.transactional_hog_flow_id and _workflow_exists(team_id, template.transactional_hog_flow_id):
            return template.transactional_hog_flow_id
        check_sendable(
            team_id,
            template_type=template.type,
            content=template.content,
            message_category_id=template.message_category_id,
        )
        try:
            hog_flow_id = create_transactional_email_workflow(
                team_id=team_id, user_id=user_id, content=_content(template, from_integration_id)
            )
        except TransactionalEmailSenderUnavailable as e:
            raise SenderUnavailable(
                "No verified email sender. Verify a sending domain or pass from_integration_id."
            ) from e
        template.transactional_hog_flow_id = hog_flow_id
        template.save(update_fields=["transactional_hog_flow_id", "updated_at"])
    return hog_flow_id


def _workflow_exists(team_id: int, hog_flow_id: UUID) -> bool:
    try:
        get_workflow_summary(team_id=team_id, workflow_id=str(hog_flow_id))
    except WorkflowNotFound:
        return False
    return True
