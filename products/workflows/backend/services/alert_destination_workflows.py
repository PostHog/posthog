"""A workflow that sends one alert destination, built by the alerts product from that destination's HogFunctions.

It is created as a draft, so it sends nothing until a person publishes it.
"""

from collections.abc import Collection, Mapping
from typing import Any, Optional
from uuid import UUID

from posthog.models.scoping import with_team_scope

from products.alerts_platform.backend.facade.api import workflow_trigger_refusal
from products.cdp.backend.presentation.hog_functions import generate_template_bytecode
from products.workflows.backend.facade.contracts import AlertWorkflowRefused
from products.workflows.backend.facade.enums import HogFlowOriginProduct
from products.workflows.backend.models import HogFlow
from products.workflows.backend.models.hog_flow.hog_flow import billable_action_types
from products.workflows.backend.services.hog_flow_secrets import TemplateCache, secret_keys_for_action
from products.workflows.backend.services.hog_flow_writes import create_workflow


def alert_workflow_ids(*, team_id: int, configuration_id: UUID) -> list[UUID]:
    """The workflows the alerts product made whose trigger names this alert configuration."""
    return list(
        HogFlow.objects.filter(
            team_id=team_id,
            origin_product=HogFlowOriginProduct.ALERTS,
            trigger__filters__properties__contains=[
                {"key": "alert_configuration_id", "value": [str(configuration_id)]}
            ],
        )
        .order_by("created_at")
        .values_list("id", flat=True)
    )


def _configuration_ids(trigger: Mapping[str, Any]) -> list[UUID]:
    properties = (trigger.get("filters") or {}).get("properties") or []
    return [
        UUID(value)
        for prop in properties
        if prop.get("key") == "alert_configuration_id"
        for value in prop.get("value") or []
    ]


# Callers run outside a workflows request, so the revision writes need the team scope set here.
@with_team_scope()
def create_alert_destination_workflow(
    *,
    team_id: int,
    user_id: Optional[int],
    content: Mapping[str, Any],
    secret_input_keys: Mapping[str, Collection[str]],
) -> UUID:
    """Creates the workflow as a draft. `secret_input_keys` names, per step, the inputs that were secret in the
    HogFunction the step replaces.

    Raises `AlertWorkflowRefused` when the trigger check refuses the alerts the trigger names, which the HogFlow
    API runs on every save. It also raises when a secret input would land in plain text, because the write
    path stores an input encrypted only when the step's template marks it secret.
    """
    refusal = workflow_trigger_refusal(
        team_id=team_id,
        configuration_ids=_configuration_ids(content["trigger"]),
        user_access_control=None,
        token_scopes=None,
    )
    if refusal is not None:
        raise AlertWorkflowRefused(refusal)
    template_cache: TemplateCache = {}
    actions = content["actions"]
    for action in actions:
        not_storable = set(secret_input_keys.get(action["id"], ())) - secret_keys_for_action(action, template_cache)
        if not_storable:
            raise AlertWorkflowRefused(
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
            "origin_product": HogFlowOriginProduct.ALERTS,
            "billable_action_types": billable_action_types(actions),
        },
    )
    return UUID(str(result.current["id"]))
