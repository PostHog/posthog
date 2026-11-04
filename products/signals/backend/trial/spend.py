from decimal import Decimal
from typing import TYPE_CHECKING

from django.db import transaction
from django.utils import timezone

from posthog.models import Team

from products.signals.backend.trial.models import SignalTrialGrant

if TYPE_CHECKING:
    from products.signals.backend.models import SignalSpend


def save_trial_spend(spend: "SignalSpend") -> None:
    if spend.trial_grant_id is None:
        spend.save()
        return
    previous = type(spend).objects.for_team(spend.team_id).get(id=spend.id)
    canonical_id = Team.objects.filter(id=spend.team_id).values_list("parent_team_id", flat=True).get() or spend.team_id
    grant = (
        SignalTrialGrant.objects.for_team(canonical_id, canonical=True).select_for_update().get(id=spend.trial_grant_id)
    )
    before = previous.spend if previous.trial_grant_id else Decimal(0)
    grant.settled_microusd += int((spend.spend - before) * 10_000)
    grant.incomplete_sources += int(spend.accounting_failed) - int(
        bool(previous.trial_grant_id and previous.accounting_failed)
    )
    grant.incomplete_since = (grant.incomplete_since or timezone.now()) if grant.incomplete_sources else None
    exhausted = grant.settled_microusd >= grant.allowance_microusd and grant.exhaustion_reason != "cost_limit"
    if exhausted:
        grant.exhausted_at = grant.exhausted_at or timezone.now()
        grant.exhaustion_reason = "cost_limit"
    grant.save(
        update_fields=[
            "settled_microusd",
            "incomplete_sources",
            "incomplete_since",
            "exhausted_at",
            "exhaustion_reason",
        ]
    )
    spend.billing_exempt = True
    spend.save()
    if exhausted:
        from products.signals.backend.trial.tasks import cancel_trial_grant  # noqa: PLC0415 -- task imports the facade

        transaction.on_commit(lambda: cancel_trial_grant.delay(grant.team_id, str(grant.id)), robust=True)
