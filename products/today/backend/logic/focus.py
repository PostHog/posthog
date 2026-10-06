"""Reading and saving the focus a person set for their briefing."""

from posthog.models import Team, User

from ..facade import contracts
from ..facade.enums import FocusDirection
from ..models import BriefingFocus


def get_focus(*, team: Team, user: User) -> contracts.BriefingFocus:
    row = BriefingFocus.objects.for_team(team.id).filter(user_id=user.id).first()
    return _to_contract(row.topics if row else [])


def set_focus(*, team: Team, user: User, topics: list[contracts.FocusTopic]) -> contracts.BriefingFocus:
    """Replace the person's focus. A topic set twice keeps its last direction."""
    by_topic = {topic.topic: topic.direction for topic in topics}
    stored = [{"topic": topic, "direction": direction.value} for topic, direction in by_topic.items()]
    BriefingFocus.objects.for_team(team.id).update_or_create(
        team_id=team.id, user_id=user.id, defaults={"topics": stored}
    )
    return _to_contract(stored)


def delete_for_teams(team_ids: list[int]) -> None:
    BriefingFocus.objects.unscoped().filter(team_id__in=team_ids).delete()


def _to_contract(stored: list[dict[str, str]]) -> contracts.BriefingFocus:
    return contracts.BriefingFocus(
        topics=[
            contracts.FocusTopic(topic=entry["topic"], direction=FocusDirection(entry["direction"])) for entry in stored
        ]
    )
