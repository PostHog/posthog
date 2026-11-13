"""A transactional email is a workflow that one authenticated API call runs once: an `api` trigger, one email step
and an exit. The message template it was made from owns the content, so each content change writes a new version
of the workflow through the same write path as the workflows UI, with its revision history."""

from collections.abc import Collection
from typing import Optional
from uuid import UUID

from django.db import models, transaction
from django.utils import timezone

from posthog.api.tagged_item import current_tag_names, replace_tags_on_object
from posthog.integrations import IntegrationManager, IntegrationNotFound
from posthog.models import TaggedItem
from posthog.models.scoping import with_team_scope
from posthog.models.tag import tagify

from products.workflows.backend.facade.contracts import (
    TRANSACTIONAL_EMAIL_ACTION_ID,
    CodeEmailWorkflow,
    TransactionalEmailContent,
    TransactionalEmailContentInvalid,
    TransactionalEmailSenderRequired,
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
        email={
            "from": {
                "integrationId": from_integration_id,
                **({"email": content.from_email} if content.from_email else {}),
                **({"name": content.from_name} if content.from_name else {}),
            },
            "replyTo": content.reply_to,
            "subject": content.subject,
            "preheader": content.preheader,
            "text": content.text,
            "html": content.html,
        },
    )


def code_email_actions(key: str) -> list[dict]:
    return _actions(
        name=key,
        step_config={"template_key": key, "message_category_id": None, "sensitive": True},
        email={
            "from": {"integrationId": None},
            "replyTo": "",
            "subject": "",
            "preheader": "",
            "text": "",
            "html": "",
        },
    )


def _actions(*, name: str, step_config: dict, email: dict) -> list[dict]:
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
                        "value": {"to": {"email": RECIPIENT_EXPRESSION, "name": ""}, "cc": "", "bcc": "", **email},
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


def _sender_without_address(team_id: int) -> int:
    if _default_sender_id(team_id) is not None:
        return resolve_transactional_email_sender(team_id, None)
    verified = [
        sender.id for sender in IntegrationManager.email.credentials.list(team_id) if sender.config.get("verified")
    ]
    if len(verified) > 1:
        raise TransactionalEmailSenderRequired()
    if not verified:
        raise TransactionalEmailSenderUnavailable()
    return verified[0]


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


def code_send_sender_id(*, team_id: int, email: str | None) -> int:
    return _sender_without_address(team_id) if email is None else _sender_on_domain(team_id, email)


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


def _code_email_flows(team_id: int) -> models.QuerySet[HogFlow]:
    return HogFlow.objects.filter(team_id=team_id, origin_product=HogFlowOriginProduct.TRANSACTIONAL_EMAIL_KEYS)


def _is_sensitive(actions: list[dict]) -> bool:
    email = next((action for action in actions if action.get("id") == TRANSACTIONAL_EMAIL_ACTION_ID), None)
    return bool(email and email.get("config", {}).get("sensitive"))


def get_code_email_workflows(*, team_id: int, workflow_ids: Collection[UUID]) -> dict[UUID, CodeEmailWorkflow]:
    """The labels of each code email workflow that still exists, keyed by its id."""
    flows = (
        _code_email_flows(team_id)
        .filter(id__in=list(workflow_ids))
        .only("id", "description", "actions")
        .prefetch_related(
            models.Prefetch(
                "tagged_items", queryset=TaggedItem.objects.select_related("tag"), to_attr="prefetched_tags"
            )
        )
    )
    return {
        flow.id: CodeEmailWorkflow(
            id=flow.id,
            description=flow.description,
            tags=tuple(sorted(current_tag_names(flow))),
            sensitive=_is_sensitive(flow.actions or []),
        )
        for flow in flows
    }


def update_code_email_labels(
    *, team_id: int, workflow_id: UUID, description: str | None, tags: list[str] | None
) -> None:
    """Change what people see about a code email. The steps stay as they are, so no new version is written."""
    with transaction.atomic():
        flow = _code_email_flows(team_id).select_for_update().only("id", "team_id").filter(id=workflow_id).first()
        if flow is None:
            raise WorkflowNotFound()
        tags_changed = False
        if tags is not None and {tagify(tag) for tag in tags} != current_tag_names(flow):
            replace_tags_on_object(tags, flow)
            tags_changed = True
        if description is None and not tags_changed:
            return
        labels = {} if description is None else {"description": description}
        # An update, not a save, so a label edit never rewrites the steps a send reads. It still moves
        # updated_at, which the workflow API compares to reject a save based on older labels.
        _code_email_flows(team_id).filter(id=workflow_id).update(**labels, updated_at=timezone.now())
