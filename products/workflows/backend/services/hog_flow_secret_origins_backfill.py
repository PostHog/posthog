"""Bind every live secret input of a workflow step to the origins its template code can send it to.

The hog function backfill in `products.cdp.backend.services.secret_origins_backfill` does the same for
hog functions, and its rules hold here: an entry that already has `allowed_origins` stays as it is, and
secrets a draft stages stay unbound, so publishing or testing the draft checks them against the live step.
"""

from typing import Optional

from products.cdp.backend.services.secret_origins_backfill import (
    BackfillPlan,
    BackfillReport,
    BackfillSource,
    SecretOutcome,
    bind_unbound_secrets,
    run_backfill,
)
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow
from products.workflows.backend.services.hog_flow_secrets import TemplateCache, function_template_for_action

_PLANNED_FIELDS = ("id", "team_id", "actions", "encrypted_inputs")


def plan_hog_flow_secret_origins(hog_flow: HogFlow, template_cache: TemplateCache) -> BackfillPlan:
    secrets_by_step = hog_flow.encrypted_inputs
    if not secrets_by_step:
        return BackfillPlan(columns=None, outcomes=[], unbound_templates=[])
    # The field hands back the ciphertext string when no configured key decrypts it.
    if not isinstance(secrets_by_step, dict):
        return BackfillPlan(columns=None, outcomes=[SecretOutcome.SKIPPED], unbound_templates=[])

    steps = {
        str(action["id"]): action
        for action in (hog_flow.actions if isinstance(hog_flow.actions, list) else [])
        if isinstance(action, dict) and action.get("id")
    }
    outcomes: list[SecretOutcome] = []
    unbound_templates: list[str] = []
    updated = dict(secrets_by_step)
    for step_id, secrets in secrets_by_step.items():
        count = len(secrets) if isinstance(secrets, dict) else 1
        step = steps.get(step_id)
        if step is None:
            outcomes += [SecretOutcome.NO_STEP] * count
            continue
        template = function_template_for_action(step, template_cache)
        if template is None:
            # The lookup also returns None when the database read fails, and an empty binding written
            # then would refuse every later save that keeps the secret where it goes.
            outcomes += [SecretOutcome.NO_TEMPLATE] * count
            continue
        config = step.get("config") or {}
        plan = bind_unbound_secrets(secrets, template.code or "", config.get("inputs") or {}, config.get("mappings"))
        outcomes += plan.outcomes
        if plan.has_unbound_secret:
            unbound_templates.append(config.get("template_id") or "(none)")
        if plan.encrypted_inputs is not None:
            updated[step_id] = plan.encrypted_inputs
    columns = {"encrypted_inputs": updated} if updated != secrets_by_step else None
    return BackfillPlan(columns=columns, outcomes=outcomes, unbound_templates=unbound_templates)


def backfill_hog_flow_secret_origins(
    *, commit: bool, team_id: Optional[int] = None, batch_size: int = 500
) -> BackfillReport:
    queryset = HogFlow.objects.filter(encrypted_inputs__isnull=False)
    if team_id is not None:
        queryset = queryset.filter(team_id=team_id)
    template_cache: TemplateCache = {}
    source = BackfillSource(
        queryset=queryset,
        planned_fields=_PLANNED_FIELDS,
        plan=lambda hog_flow: plan_hog_flow_secret_origins(hog_flow, template_cache),
    )
    return run_backfill(source, commit=commit, batch_size=batch_size)
