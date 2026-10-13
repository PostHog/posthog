"""Which teams' data the inbox-ranking dags may train on.

`Organization.is_ai_training_opted_in` is the organization's consent to train PostHog AI models on
its data. Only `True` is consent: the column is nullable, and every other surface reads null as
opted out, so `False` and `None` both keep a team out.
"""

from posthog.models import Team

from products.signals.backend.models import SignalReport


def training_consent_team_ids() -> frozenset[int]:
    """The teams that hold an inbox report and whose organization allows AI training, as of now.

    Narrowed to teams with a report so the set stays the size of the inbox rather than of the
    region: the embedding assets send it to ClickHouse as an `IN` list. A team with signals and no
    report yet is left out, which fails closed.
    """
    return frozenset(
        Team.objects.filter(
            organization__is_ai_training_opted_in=True,
            id__in=SignalReport.objects.values("team_id"),
        ).values_list("id", flat=True)
    )
