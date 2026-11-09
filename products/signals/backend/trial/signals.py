from django.db import transaction

from posthog.models import Team

from products.signals.backend.daily_limit import check_daily_report_admission
from products.signals.backend.models import SignalSpend
from products.signals.backend.quota import prepare_self_driving_admission
from products.signals.backend.spend import begin_signal_spend, lock_signal_spend
from products.signals.backend.trial.funding import TrialFunding, signal_funding
from products.signals.backend.trial.policy import TrialRefused
from products.signals.backend.trial.reports import context_funding


def admit_signal(*, team: Team, signal_id: str, billing_exempt: bool = False) -> None:
    parent = signal_funding(team.id, signal_id) or context_funding(team)
    if parent is None:
        check_daily_report_admission(team)
    if billing_exempt:
        parent = TrialFunding(funding="operator")
    admission = prepare_self_driving_admission(team, parent=parent)
    with transaction.atomic():
        lock_signal_spend(team_id=team.id, signal_id=signal_id)
        spend = SignalSpend.objects.for_team(team.id).filter(signal_id=signal_id, kind=SignalSpend.Kind.AD_HOC).first()
        if spend is not None:
            if spend.finalization_requested_at is not None or spend.finalized_at is not None:
                raise TrialRefused("operation_finished")
            return
        funding = admission.bind()
        begin_signal_spend(
            team_id=team.id,
            signal_id=signal_id,
            trial_grant_id=str(funding.grant_id) if funding.grant_id else None,
            billing_exempt=funding.funding == "operator",
        )
