"""Workflows another product builds for a person to review: saved as drafts, so they send nothing until published."""

from collections.abc import Collection, Mapping
from typing import Any, Optional
from uuid import UUID

from posthog.models.scoping import with_team_scope

from products.cdp.backend.presentation.hog_functions import generate_template_bytecode
from products.workflows.backend.facade.contracts import DraftWorkflowRefused, OriginWorkflow
from products.workflows.backend.facade.enums import HogFlowOriginProduct
from products.workflows.backend.models import HogFlow
from products.workflows.backend.models.hog_flow.hog_flow import billable_action_types
from products.workflows.backend.services.hog_flow_secrets import TemplateCache, secret_keys_for_action
from products.workflows.backend.services.hog_flow_writes import create_workflow


def workflows_for_origin(*, team_id: int, origin_product: HogFlowOriginProduct) -> list[OriginWorkflow]:
    """The workflows a product made, oldest first."""
    return [
        OriginWorkflow(id=workflow_id, trigger=trigger or {})
        for workflow_id, trigger in HogFlow.objects.filter(team_id=team_id, origin_product=origin_product)
        .order_by("created_at")
        .values_list("id", "trigger")
    ]


# Callers run outside a workflows request, so the revision writes need the team scope set here.
@with_team_scope()
def create_draft_workflow(
    *,
    team_id: int,
    user_id: Optional[int],
    content: Mapping[str, Any],
    origin_product: HogFlowOriginProduct,
    secret_input_keys: Mapping[str, Collection[str]],
) -> UUID:
    """Saves `content` as a draft that `origin_product` owns. `secret_input_keys` names, per step id, the inputs
    the caller holds as secrets.

    This skips the HogFlow serializer, so it does what a person enabling the draft relies on: it derives the
    billable action types and compiles the trigger masking. Raises `DraftWorkflowRefused` for a secret input
    the step's template does not mark secret, because the write path would store it in plain text.
    """
    template_cache: TemplateCache = {}
    actions = content["actions"]
    for action in actions:
        not_storable = set(secret_input_keys.get(action["id"], ())) - secret_keys_for_action(action, template_cache)
        if not_storable:
            raise DraftWorkflowRefused(
                f"Step {action['id']} has secret inputs its template does not keep secret: {', '.join(sorted(not_storable))}"
            )
    masking = content.get("trigger_masking")
    if masking:
        # The HogFlow API compiles masking only when it is saved, and enabling a draft does not save it again.
        masking = {**masking, "bytecode": generate_template_bytecode(masking["hash"], input_collector=set())}
    result = create_workflow(
        team_id=team_id,
        user_id=user_id,
        validated_data={
            **content,
            "trigger_masking": masking,
            "status": HogFlow.State.DRAFT,
            "origin_product": origin_product,
            "billable_action_types": billable_action_types(actions),
        },
    )
    return UUID(str(result.current["id"]))
