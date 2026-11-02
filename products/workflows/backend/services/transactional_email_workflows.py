"""A transactional email is a workflow that one authenticated API call runs once: an `api` trigger, one email step
and an exit. The message template it was made from owns the content, so each content change writes a new version
of the workflow through the same write path as the workflows UI, with its revision history."""

from typing import Optional
from uuid import UUID

from django.db import transaction

from posthog.integrations import IntegrationManager, IntegrationNotFound
from posthog.models.scoping import with_team_scope

from products.workflows.backend.facade.contracts import (
    TRANSACTIONAL_EMAIL_ACTION_ID,
    TransactionalEmailContent,
    TransactionalEmailContentInvalid,
    TransactionalEmailSender,
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


def _template_provenance(content: TransactionalEmailContent) -> dict[str, str]:
    return {"template_uuid": str(content.message_template_id)}


def transactional_email_actions(content: TransactionalEmailContent, from_integration_id: int) -> list[dict]:
    return _actions(
        name=content.name,
        step_config={
            **_template_provenance(content),
            "message_category_id": str(content.message_category_id) if content.message_category_id else None,
            "sensitive": content.sensitive,
        },
        sender_integration_id=from_integration_id,
        from_email=content.from_email,
        from_name=content.from_name,
        reply_to=content.reply_to,
        subject=content.subject,
        preheader=content.preheader,
        text=content.text,
        html=content.html,
    )


def code_email_actions(key: str) -> list[dict]:
    return _actions(
        name=key,
        step_config={"message_category_id": None, "sensitive": False},
        sender_integration_id=None,
        from_email="",
        from_name="",
        reply_to="",
        subject="",
        preheader="",
        text="",
        html="",
    )


def _actions(
    *,
    name: str,
    step_config: dict,
    sender_integration_id: int | None,
    from_email: str,
    from_name: str,
    reply_to: str,
    subject: str,
    preheader: str,
    text: str,
    html: str,
) -> list[dict]:
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
            "name": name,
            "description": "",
            "type": "function_email",
            # Nothing comes after the email, so a failed send must fail the run.
            "on_error": "abort",
            "config": {
                "template_id": "template-email",
                **step_config,
                # Puts the send on the email queue's fast lane and skips marketing opt-outs.
                "message_category_type": "transactional",
                "inputs": {
                    "email": {
                        "templating": "liquid",
                        "value": {
                            "to": {"email": RECIPIENT_EXPRESSION, "name": ""},
                            "from": {
                                "integrationId": sender_integration_id,
                                **({"email": from_email} if from_email else {}),
                                **({"name": from_name} if from_name else {}),
                            },
                            "replyTo": reply_to,
                            "cc": "",
                            "bcc": "",
                            "subject": subject,
                            "preheader": preheader,
                            "text": text,
                            "html": html,
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
    return _flow_fields(content.name, transactional_email_actions(content, from_integration_id))


def _flow_fields(name: str, actions: list[dict]) -> dict:
    return {
        "name": name,
        "actions": actions,
        "edges": [
            {"from": TRIGGER_ACTION_ID, "to": TRANSACTIONAL_EMAIL_ACTION_ID, "type": "continue"},
            {"from": TRANSACTIONAL_EMAIL_ACTION_ID, "to": EXIT_ACTION_ID, "type": "continue"},
        ],
        # The API serializer derives these two from the actions on every save.
        "trigger": actions[0]["config"],
        "billable_action_types": ["function_email"],
    }


def _default_sender_id(team_id: int) -> int | None:
    return (
        TeamWorkflowsConfig.objects.filter(team_id=team_id)
        .values_list("default_email_integration_id", flat=True)
        .first()
    )


def resolve_transactional_email_sender(team_id: int, requested_id: int | None) -> int:
    """The requested sender, or the project's default when none is requested. Raise when it isn't verified."""
    sender_id = requested_id or _default_sender_id(team_id)
    sender = None
    if sender_id:
        try:
            sender = IntegrationManager.email.credentials.get(team_id, sender_id)
        except IntegrationNotFound:
            pass
    if sender is None or not sender.config.get("verified"):
        raise TransactionalEmailSenderUnavailable()
    return sender.id


def _sender_on_domain(team_id: int, email: str) -> int:
    address = email.lower()
    domain = address.rpartition("@")[2]
    on_domain: list[int] = []
    for sender in IntegrationManager.email.credentials.list(team_id):
        if not sender.config.get("verified"):
            continue
        own = str(sender.config.get("email") or sender.integration_id or "").lower()
        if own == address:
            return sender.id
        if str(sender.config.get("domain") or own.rpartition("@")[2]).lower() == domain:
            on_domain.append(sender.id)
    if not on_domain:
        raise TransactionalEmailSenderUnavailable()
    default_sender_id = _default_sender_id(team_id)
    if default_sender_id is not None and default_sender_id in on_domain:
        return default_sender_id
    return on_domain[0]


def code_send_sender(*, team_id: int, email: str | None, name: str | None) -> TransactionalEmailSender:
    if email is None:
        return TransactionalEmailSender(
            integration_id=resolve_transactional_email_sender(team_id, None), email=None, name=None
        )
    return TransactionalEmailSender(integration_id=_sender_on_domain(team_id, email), email=email, name=name)


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


@with_team_scope()
def create_code_email_workflow(*, team_id: int, key: str) -> UUID:
    result = create_workflow(
        team_id=team_id,
        user_id=None,
        validated_data={
            **_flow_fields(key, code_email_actions(key)),
            "status": HogFlow.State.ACTIVE,
            "origin_product": HogFlowOriginProduct.TRANSACTIONAL_EMAIL_KEYS,
            "exit_condition": "exit_only_at_end",
        },
    )
    return UUID(str(result.current["id"]))
