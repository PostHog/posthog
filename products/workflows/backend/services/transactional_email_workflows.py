"""A transactional email is a workflow that one authenticated API call runs once: an `api` trigger, one email step
and an exit. The message template it was made from owns the content, so each content change writes a new version
of the workflow through the same write path as the workflows UI, with its revision history."""

from typing import Optional
from uuid import UUID

from posthog.models.scoping import with_team_scope

from products.workflows.backend.facade.contracts import TransactionalEmailContent
from products.workflows.backend.facade.enums import HogFlowOriginProduct
from products.workflows.backend.models import HogFlow
from products.workflows.backend.services.hog_flow_writes import create_workflow, update_workflow

TRIGGER_ACTION_ID = "trigger_node"
# Engagement tracking and message assets key on this id, so it stays stable across versions.
EMAIL_ACTION_ID = "transactional_email"
EXIT_ACTION_ID = "exit_node"

# The send endpoint passes the recipient as an event property. Liquid output is never parsed again, so an
# address that contains Liquid markup is sent as typed.
RECIPIENT_EXPRESSION = "{{ event.properties.to }}"


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
            "id": EMAIL_ACTION_ID,
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
                "inputs": {
                    "email": {
                        "templating": "liquid",
                        "value": {
                            "to": {"email": RECIPIENT_EXPRESSION, "name": ""},
                            "from": {"integrationId": from_integration_id},
                            "replyTo": "",
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
    actions = transactional_email_actions(content, from_integration_id)
    return {
        "name": content.name,
        "actions": actions,
        "edges": [
            {"from": TRIGGER_ACTION_ID, "to": EMAIL_ACTION_ID, "type": "continue"},
            {"from": EMAIL_ACTION_ID, "to": EXIT_ACTION_ID, "type": "continue"},
        ],
        # The API serializer derives these two from the actions on every save.
        "trigger": actions[0]["config"],
        "billable_action_types": ["function_email"],
    }


def _current_sender(flow: HogFlow) -> int:
    email = next(action for action in flow.actions if action.get("id") == EMAIL_ACTION_ID)
    return email["config"]["inputs"]["email"]["value"]["from"]["integrationId"]


# Callers run outside a workflows request, so the revision writes need the team scope set here.
@with_team_scope()
def create_transactional_email_workflow(
    *, team_id: int, user_id: Optional[int], content: TransactionalEmailContent
) -> UUID:
    if content.from_integration_id is None:
        raise ValueError("A new transactional email needs a sender")
    result = create_workflow(
        team_id=team_id,
        user_id=user_id,
        validated_data={
            **_content_fields(content, content.from_integration_id),
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
    flow = HogFlow.objects.only("status", "actions").get(team_id=team_id, pk=hog_flow_id)
    from_integration_id = content.from_integration_id or _current_sender(flow)
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
    )
