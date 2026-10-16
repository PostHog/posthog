from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING

from django.db import transaction

from products.signals.backend.trial.models import SignalTrialGrant, SignalTrialOrganization

if TYPE_CHECKING:
    from products.signals.backend.models import SignalScoutConfig


@contextmanager
def scout_capacity(config: "SignalScoutConfig") -> Iterator[None]:
    from products.signals.backend.models import SignalScoutConfig  # noqa: PLC0415 -- model registration cycle

    if not config.enabled:
        yield
        return
    team = config.team
    team_id = team.parent_team_id or team.id
    with transaction.atomic():
        previous = (
            SignalScoutConfig.objects.for_team(team_id, canonical=True).select_for_update().filter(id=config.id).first()
        )
        if previous is not None and previous.enabled:
            yield
            return
        allocation, _ = SignalTrialOrganization.objects.get_or_create(organization_id=team.organization_id)
        SignalTrialOrganization.objects.select_for_update().get(organization_id=allocation.pk)
        grant = SignalTrialGrant.objects.for_team(team_id, canonical=True).filter(exhausted_at__isnull=True).first()
        if grant is not None:
            count = (
                SignalScoutConfig.objects.for_team(team_id, canonical=True)
                .filter(enabled=True)
                .exclude(id=config.id)
                .count()
            )
            if count >= grant.scout_limit:
                if not config._state.adding:
                    from rest_framework.exceptions import (
                        ValidationError,  # noqa: PLC0415 -- only API writes need the error renderer
                    )

                    raise ValidationError(
                        {"enabled": "The free trial allows three enabled scouts. Pause one before enabling another."}
                    )
                config.enabled = False
                config.status = SignalScoutConfig.Status.PAUSED_BY_SYSTEM
                config.pause_reason = SignalScoutConfig.PauseReason.TRIAL_SCOUT_LIMIT
        yield


def trial_scout_limit(team_id: int) -> int | None:
    grant = SignalTrialGrant.objects.for_team(team_id).filter(exhausted_at__isnull=True).first()
    return grant.scout_limit if grant is not None else None
