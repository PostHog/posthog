"""A transactional email is a workflow that one authenticated API call runs once: an `api` trigger, one email step
and an exit. The message template it was made from owns the content, so each content change writes a new version
of the workflow through the same write path as the workflows UI, with its revision history."""

from typing import Optional
from uuid import UUID

from django.db import transaction

from posthog.integrations import IntegrationManager, IntegrationNotFound
from posthog.models.integration import SANDBOX_EMAIL_PROVIDER
from posthog.models.scoping import with_team_scope

from products.workflows.backend.facade.contracts import (
    TRANSACTIONAL_EMAIL_ACTION_ID,
    TransactionalEmailContent,
    TransactionalEmailContentInvalid,
    TransactionalEmailSenderUnavailable,
    WorkflowNotFound,
)
from products.workflows.backend.facade.enums import HogFlowOriginProduct
from products.workflows.backend.models import HogFlow, TeamWorkflowsConfig
from products.workflows.backend.services.hog_flow_writes import create_workflow, update_workflow

TRIGGER_ACTION_ID = "trigger_node"
EXIT_ACTION_ID = "exit_node"

# The send endpoint passes the recipient as an event property. Liquid output is never parsed again, so an
# address that contains Liquid markup is sent as typed. `raw` skips the HTML escaping that would turn a
# valid address like o'brien@example.com into a different one.
RECIPIENT_EXPRESSION = "{{ event.properties.to | raw }}"


def transactional_email_actions(content: TransactionalEmailContent, from_integration_id: int) -> list[dict]:
    return [
        {
            "id": TRIGGER_ACTION_ID,
            "name": "Trigger",
            "description": "",
            "type": "trigger",
            "config": {"type": "api"},
        },
        {
            "id": TRANSACTIONAL_EMAIL_ACTION_ID,
            "name": content.name,
            "description": "",
            "type": "function_email",
            # Nothing comes after the email, so a failed send must fail the run.
            "on_error": "abort",
            "config": {
                "template_id": "template-email",
                # Provenance only: the body below is set, so a save never re-reads the template.
                "template_uuid": str(content.message_template_id),
                "message_category_id": str(content.message_category_id) if content.message_category_id else None,
                # Puts the send on the email queue's fast lane and skips marketing opt-outs.
                "message_category_type": "transactional",
                "sensitive": content.sensitive,
                "inputs": {
                    "email": {
                        "templating": "liquid",
                        "value": {
                            "to": {"email": RECIPIENT_EXPRESSION, "name": ""},
                            "from": {
                                "integrationId": from_integration_id,
                                **({"email": content.from_email} if content.from_email else {}),
                                **({"name": content.from_name} if content.from_name else {}),
                            },
                            "replyTo": content.reply_to,
                            "cc": "",
                            "bcc": "",
                            "subject": content.subject,
                            "preheader": content.preheader,
                            "text": content.text,
                            "html": content.html,
                        },
                    }
                },
            },
        },
        {
            "id": EXIT_ACTION_ID,
            "name": "Exit",
            "description": "",
            "type": "exit",
            "config": {"reason": "Default exit"},
        },
    ]


def _content_fields(content: TransactionalEmailContent, from_integration_id: int) -> dict:
    if not content.subject or not (content.html or content.text):
        raise TransactionalEmailContentInvalid()
    actions = transactional_email_actions(content, from_integration_id)
    return {
        "name": content.name,
        "actions": actions,
        "edges": [
            {"from": TRIGGER_ACTION_ID, "to": TRANSACTIONAL_EMAIL_ACTION_ID, "type": "continue"},
            {"from": TRANSACTIONAL_EMAIL_ACTION_ID, "to": EXIT_ACTION_ID, "type": "continue"},
        ],
        # The API serializer derives these two from the actions on every save.
        "trigger": actions[0]["config"],
        "billable_action_types": ["function_email"],
    }


def resolve_transactional_email_sender(team_id: int, requested_id: int | None) -> int:
    """The requested sender, or the project's default when none is requested. Raise when it isn't verified,
    or when it is the sandbox sender, which only workflow email steps and test sends may use."""
    sender_id = requested_id or (
        TeamWorkflowsConfig.objects.filter(team_id=team_id)
        .values_list("default_email_integration_id", flat=True)
        .first()
    )
    sender = None
    if sender_id:
        try:
            sender = IntegrationManager.email.credentials.get(team_id, sender_id)
        except IntegrationNotFound:
            pass
    if sender is None or not sender.config.get("verified") or sender.config.get("provider") == SANDBOX_EMAIL_PROVIDER:
        raise TransactionalEmailSenderUnavailable()
    return sender.id


def _current_sender(flow: HogFlow) -> int | None:
    # The email step is missing when someone edited the workflow directly. The update writes it back.
    email = next((action for action in flow.actions if action.get("id") == TRANSACTIONAL_EMAIL_ACTION_ID), None)
    if email is None:
        return None
    return email["config"]["inputs"]["email"]["value"]["from"].get("integrationId")


# Callers run outside a workflows request, so the revision writes need the team scope set here.
@with_team_scope()
def create_transactional_email_workflow(
    *, team_id: int, user_id: Optional[int], content: TransactionalEmailContent
) -> UUID:
    from_integration_id = resolve_transactional_email_sender(team_id, content.from_integration_id)
    result = create_workflow(
        team_id=team_id,
        user_id=user_id,
        validated_data={
            **_content_fields(content, from_integration_id),
            "status": HogFlow.State.ACTIVE,
            "origin_product": HogFlowOriginProduct.TRANSACTIONAL_EMAILS,
            "exit_condition": "exit_only_at_end",
        },
    )
    return UUID(str(result.current["id"]))


@with_team_scope()
def update_transactional_email_workflow(
    *, team_id: int, user_id: Optional[int], hog_flow_id: UUID, content: TransactionalEmailContent
) -> None:
    with transaction.atomic():
        # The lock keeps the status read here current, so update_workflow can't find it changed.
        flow = (
            HogFlow.objects.select_for_update()
            .only("status", "actions")
            .filter(team_id=team_id, pk=hog_flow_id)
            .first()
        )
        if flow is None:
            raise WorkflowNotFound()
        if content.from_integration_id:
            from_integration_id = resolve_transactional_email_sender(team_id, content.from_integration_id)
        else:
            from_integration_id = _current_sender(flow) or resolve_transactional_email_sender(team_id, None)
        update_workflow(
            team_id=team_id,
            user_id=user_id,
            hog_flow_id=hog_flow_id,
            validated_data=_content_fields(content, from_integration_id),
            route_to_draft=False,
            base_updated_at=None,
            base_live_updated_at=None,
            includes_staged_draft=False,
            validated_status=flow.status,
            keeps_live_sensitivity=False,
        )
