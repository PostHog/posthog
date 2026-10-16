from functools import partial
from typing import TYPE_CHECKING

from django.db import transaction
from django.utils import timezone

from products.signals.backend.trial_models import SignalTrialGrant, SignalTrialOperation

if TYPE_CHECKING:
    from products.signals.backend.models import SignalSpend
    from products.signals.backend.spend import SpendSource


def apply_trial_spend(spend: "SignalSpend", previous: dict[str, "SpendSource"]) -> None:
    grant_ids = {
        source["trial_grant_id"]
        for source in [*previous.values(), *spend.trial_sources.values()]
        if source.get("trial_grant_id")
    }
    for grant_id in sorted(grant_ids):
        before = [source for source in previous.values() if source.get("trial_grant_id") == grant_id]
        after = [source for source in spend.trial_sources.values() if source.get("trial_grant_id") == grant_id]
        cost_delta = sum((s["cost_microusd"] or 0) + (s.get("compute_cost_microusd") or 0) for s in after) - sum(
            (s["cost_microusd"] or 0) + (s.get("compute_cost_microusd") or 0) for s in before
        )
        missing_delta = sum(s.get("actual_cost_incomplete", s["accounting_failed"]) for s in after) - sum(
            s.get("actual_cost_incomplete", s["accounting_failed"]) for s in before
        )
        if not cost_delta and not missing_delta:
            continue
        # This balance survives project deletion. The shared spend row remains the receipt;
        # comparing its previous value makes duplicate and late updates idempotent.
        grant = SignalTrialGrant.objects.for_team(spend.team_id).select_for_update().get(id=grant_id)
        grant.settled_microusd += cost_delta
        grant.incomplete_sources += missing_delta
        grant.incomplete_since = (grant.incomplete_since or timezone.now()) if grant.incomplete_sources else None
        if grant.settled_microusd >= grant.allowance_microusd:
            from products.signals.backend.trial_tasks import cancel_trial_grant

            grant.exhausted_at = grant.exhausted_at or timezone.now()
            grant.exhaustion_reason = "cost_limit"
            SignalTrialOperation.objects.for_team(grant.team_id, canonical=True).filter(
                grant=grant, finished_at__isnull=True, cancel_requested_at__isnull=True
            ).exclude(
                stage__in=[SignalTrialOperation.Stage.RESEARCH, SignalTrialOperation.Stage.REPORT_PASS],
                started_at__isnull=False,
            ).update(cancel_requested_at=timezone.now())
            transaction.on_commit(
                partial(cancel_trial_grant.delay, grant.team_id, str(grant.id)),
                robust=True,
            )
        grant.save(
            update_fields=[
                "settled_microusd",
                "incomplete_sources",
                "incomplete_since",
                "exhausted_at",
                "exhaustion_reason",
            ]
        )
