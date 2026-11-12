"""A transactional push is a workflow that one authenticated API call runs once: an `api` trigger, one push step
and an exit. The message template it was made from owns the content, so each content change writes a new version
of the workflow through the same write path as the workflows UI, with its revision history."""

from typing import Optional
from uuid import UUID

from django.db import transaction

from posthog.integrations import IntegrationManager
from posthog.models.scoping import with_team_scope

from products.workflows.backend.facade.contracts import (
    TRANSACTIONAL_PUSH_ACTION_ID,
    TransactionalPushChannelUnavailable,
    TransactionalPushContent,
    TransactionalPushContentInvalid,
    WorkflowNotFound,
)
from products.workflows.backend.facade.enums import HogFlowOriginProduct
from products.workflows.backend.models import HogFlow
from products.workflows.backend.services.hog_flow_writes import create_workflow, update_workflow
from products.workflows.backend.services.transactional_email_workflows import EXIT_ACTION_ID, TRIGGER_ACTION_ID

PUSH_CHANNEL_KINDS = ("firebase", "apns")
# The send endpoint passes the recipient as the event's distinct ID.
RECIPIENT_EXPRESSION = "{{ event.distinct_id }}"


def _liquid(value: object) -> dict:
    return {"value": value, "templating": "liquid"}


def transactional_push_actions(content: TransactionalPushContent) -> list[dict]:
    inputs: dict[str, dict] = {
        "distinctId": _liquid(RECIPIENT_EXPRESSION),
        "channels": {"value": list(content.channel_ids)},
        "title": _liquid(content.title),
        "body": _liquid(content.body),
    }
    if content.image:
        inputs["image"] = _liquid(content.image)
    if content.link:
        inputs["link"] = _liquid(content.link)
    if content.data:
        inputs["data"] = _liquid(dict(content.data))
    push_config: dict = {
        "template_id": "template-native-push",
        "template_uuid": str(content.message_template_id),
        "sensitive": content.sensitive,
        # Skips marketing opt-outs and frequency caps.
        "message_category_type": "transactional",
        "inputs": inputs,
    }
    # The workflow editor rejects a null category on a push step, which blocks turning the workflow back on.
    if content.message_category_id:
        push_config["message_category_id"] = str(content.message_category_id)
    return [
        {
            "id": TRIGGER_ACTION_ID,
            "name": "Trigger",
            "description": "",
            "type": "trigger",
            "config": {"type": "api"},
        },
        {
            "id": TRANSACTIONAL_PUSH_ACTION_ID,
            "name": content.name,
            "description": "",
            "type": "function_push",
            # Nothing comes after the push, so a failed send must fail the run.
            "on_error": "abort",
            "config": push_config,
        },
        {
            "id": EXIT_ACTION_ID,
            "name": "Exit",
            "description": "",
            "type": "exit",
            "config": {"reason": "Default exit"},
        },
    ]


def _check_channels(team_id: int, channel_ids: tuple[int, ...]) -> None:
    found = IntegrationManager.kinds(*PUSH_CHANNEL_KINDS).get_many(team_id, list(channel_ids))
    if len(found) != len(set(channel_ids)):
        raise TransactionalPushChannelUnavailable()


def _content_fields(team_id: int, content: TransactionalPushContent) -> dict:
    if not content.title.strip() or not content.body.strip() or not content.channel_ids:
        raise TransactionalPushContentInvalid()
    _check_channels(team_id, content.channel_ids)
    actions = transactional_push_actions(content)
    return {
        "name": content.name,
        "actions": actions,
        "edges": [
            {"from": TRIGGER_ACTION_ID, "to": TRANSACTIONAL_PUSH_ACTION_ID, "type": "continue"},
            {"from": TRANSACTIONAL_PUSH_ACTION_ID, "to": EXIT_ACTION_ID, "type": "continue"},
        ],
        # The API serializer derives these two from the actions on every save.
        "trigger": actions[0]["config"],
        "billable_action_types": ["function_push"],
    }


# Callers run outside a workflows request, so the revision writes need the team scope set here.
@with_team_scope()
def create_transactional_push_workflow(
    *, team_id: int, user_id: Optional[int], content: TransactionalPushContent
) -> UUID:
    result = create_workflow(
        team_id=team_id,
        user_id=user_id,
        validated_data={
            **_content_fields(team_id, content),
            "status": HogFlow.State.ACTIVE,
            "origin_product": HogFlowOriginProduct.TRANSACTIONAL_PUSH,
            "exit_condition": "exit_only_at_end",
        },
    )
    return UUID(str(result.current["id"]))


@with_team_scope()
def update_transactional_push_workflow(
    *, team_id: int, user_id: Optional[int], hog_flow_id: UUID, content: TransactionalPushContent
) -> None:
    fields = _content_fields(team_id, content)
    with transaction.atomic():
        # The lock keeps the status read here current, so update_workflow can't find it changed.
        flow = HogFlow.objects.select_for_update().only("status").filter(team_id=team_id, pk=hog_flow_id).first()
        if flow is None:
            raise WorkflowNotFound()
        update_workflow(
            team_id=team_id,
            user_id=user_id,
            hog_flow_id=hog_flow_id,
            validated_data=fields,
            route_to_draft=False,
            base_updated_at=None,
            base_live_updated_at=None,
            includes_staged_draft=False,
            validated_status=flow.status,
            keeps_live_sensitivity=False,
        )
