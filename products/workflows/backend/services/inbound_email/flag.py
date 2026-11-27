from collections.abc import Iterable

import posthoganalytics

from posthog.models.team import Team

INBOUND_EMAIL_FLAG = "workflows-inbound-email"


class InboundEmailFlagUnavailable(Exception):
    pass


def _evaluate(team: Team) -> bool | None:
    return posthoganalytics.feature_enabled(
        INBOUND_EMAIL_FLAG,
        str(team.uuid),
        groups={"organization": str(team.organization_id)},
        group_properties={"organization": {"id": str(team.organization_id)}},
        send_feature_flag_events=False,
    )


def inbound_email_enabled(team: Team) -> bool:
    return bool(_evaluate(team))


def teams_with_inbound_email(team_ids: Iterable[int]) -> set[int]:
    """Raises when the flag can't be evaluated, so the mail stays in intake for a retry instead of being dropped."""
    enabled: set[int] = set()
    for team in Team.objects.only("uuid", "organization_id").filter(pk__in=set(team_ids)):
        result = _evaluate(team)
        if result is None:
            raise InboundEmailFlagUnavailable(team.pk)
        if result:
            enabled.add(team.pk)
    return enabled
