"""Transactional emails: a template made sendable over the API. Each one is backed by a workflow that runs once
per send, so sends get the workflow's metrics, run history and versions."""

from typing import Any
from uuid import UUID

from django.db import transaction

import structlog

from posthog.models.team import Team
from posthog.plugins.plugin_server_api import (
    reload_hog_flows_on_workers,
    send_transactional_email as run_transactional_workflow,
)

from products.messaging.backend.facade.contracts import (
    DeliveryUnavailable,
    InvalidRecipient,
    MarketingTemplate,
    QueuedEmail,
    QuotaLimited,
    SenderUnavailable,
    TemplateNotSendable,
    TemplateNotTransactional,
    TransactionalEmailPaused,
)
from products.messaging.backend.models import MessageCategory, MessageTemplate
from products.messaging.backend.models.message_category import MessageCategoryType
from products.workflows.backend.facade.api import WorkflowNotFound, get_workflow_summary
from products.workflows.backend.facade.transactional_emails import (
    TransactionalEmailContent,
    TransactionalEmailContentInvalid,
    TransactionalEmailSenderUnavailable,
    create_transactional_email_workflow,
    update_transactional_email_workflow,
)

logger = structlog.get_logger(__name__)


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


def lock_transactional_workflow_id(team_id: int, template_id: UUID) -> UUID | None:
    """Lock the template row for the rest of the transaction and return its workflow id. Holding the lock
    keeps make_transactional from linking a workflow between this read and the update that follows."""
    return (
        MessageTemplate.objects.select_for_update()
        .filter(team_id=team_id, id=template_id)
        .values_list("transactional_hog_flow_id", flat=True)
        .get()
    )


def check_transactional_update(template_id: UUID, team_id: int, fields: dict[str, Any]) -> None:
    """Raise when an update would leave a transactional template unable to send. `fields` are validated
    serializer fields, where `message_category` holds a category id."""
    template = MessageTemplate.objects.get(team_id=team_id, id=template_id)
    if not template.transactional_hog_flow_id or fields.get("deleted"):
        return
    # A link to a deleted workflow no longer restricts the template. The sync after the update clears it.
    if not _workflow_exists(team_id, template.transactional_hog_flow_id):
        return
    check_sendable(
        team_id,
        template_type=fields.get("type", template.type),
        content=fields.get("content", template.content),
        message_category_id=fields.get("message_category", template.message_category_id),
    )


def _reload_workers(team_id: int, hog_flow_id: UUID) -> None:
    # The edit is already committed, so a failed reload must not fail the request. Workers still pick up the
    # new version when their cache expires.
    try:
        reload_hog_flows_on_workers(team_id=team_id, hog_flow_ids=[str(hog_flow_id)])
    except Exception:
        logger.exception("transactional_email_worker_reload_failed", team_id=team_id, hog_flow_id=str(hog_flow_id))


def sync_transactional_workflow(team_id: int, template_id: UUID, *, user_id: int | None) -> None:
    """Write the template's current content as a new version of its workflow, if it has one."""
    template = MessageTemplate.objects.get(team_id=team_id, id=template_id)
    if not template.transactional_hog_flow_id or template.deleted:
        return
    hog_flow_id = template.transactional_hog_flow_id
    if not _workflow_exists(team_id, hog_flow_id):
        # Someone deleted the workflow. The template stops being transactional and can be made so again.
        MessageTemplate.objects.filter(team_id=team_id, id=template_id).update(transactional_hog_flow_id=None)
        return
    try:
        update_transactional_email_workflow(
            team_id=team_id,
            user_id=user_id,
            hog_flow_id=hog_flow_id,
            content=_content(template, from_integration_id=None),
        )
        # The save already told the workers to reload, but before the caller's transaction committed, so a
        # worker can cache the old version. This reload runs once the new version is visible.
        transaction.on_commit(lambda: _reload_workers(team_id, hog_flow_id))
    except WorkflowNotFound:
        # Deleted between the check above and the update.
        MessageTemplate.objects.filter(team_id=team_id, id=template_id).update(transactional_hog_flow_id=None)
    except TransactionalEmailContentInvalid as e:
        raise TemplateNotSendable("The template needs a subject and a body to send.") from e
    except TransactionalEmailSenderUnavailable as e:
        raise SenderUnavailable("No verified email sender. Verify a sending domain first.") from e


def _transactional_workflow_id(team_id: int, template_id: UUID) -> UUID:
    template = MessageTemplate.objects.get(team_id=team_id, id=template_id, deleted=False)
    if not template.transactional_hog_flow_id:
        raise TemplateNotTransactional("The template isn't transactional. Make it transactional to send it.")
    # A category's type can change after the template was made transactional.
    check_sendable(
        team_id,
        template_type=template.type,
        content=template.content,
        message_category_id=template.message_category_id,
    )
    try:
        workflow = get_workflow_summary(team_id=team_id, workflow_id=str(template.transactional_hog_flow_id))
    except WorkflowNotFound as e:
        raise TransactionalEmailPaused("The template's transactional email no longer exists.") from e
    if workflow.status != "active":
        raise TransactionalEmailPaused("The template's transactional email isn't active.")
    return template.transactional_hog_flow_id


def send_transactional_email(
    team: Team, template_id: UUID, *, to: str, distinct_id: str | None, message_data: dict[str, Any]
) -> QueuedEmail:
    # Defense in depth: the workflow reads the recipient from an event property, which Liquid outputs as typed.
    if "{" in to or "}" in to:
        raise InvalidRecipient("The recipient address can't contain { or }.")

    hog_flow_id = _transactional_workflow_id(team.id, template_id)
    payload = {
        "to": to,
        # The recipient is the person the send is tracked against. Without a distinct_id, the address is one.
        "distinct_id": distinct_id or to,
        "variables": message_data,
    }
    try:
        response = run_transactional_workflow(team.id, str(hog_flow_id), payload)
    except Exception as e:
        logger.exception("transactional_email_queue_failed", team_id=team.id, template_id=str(template_id))
        raise DeliveryUnavailable() from e

    if response.status_code != 202:
        if response.status_code == 429:
            raise QuotaLimited("The project is over its email quota.")
        logger.error(
            "transactional_email_queue_rejected",
            team_id=team.id,
            template_id=str(template_id),
            status_code=response.status_code,
        )
        raise DeliveryUnavailable()

    return QueuedEmail(message_id=str(response.json()["invocation_id"]))
