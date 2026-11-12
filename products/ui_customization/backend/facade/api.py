from posthog.models import Team, User

from ..logic import cleanup, contexts, customization
from . import contracts
from .enums import CustomizationContext
from .feature_flags import is_enabled_for as is_enabled_for


def get_customization(*, team: Team, user: User, context: str) -> contracts.Customization:
    return customization.get_customization(team=team, user_id=user.id, context=context)


def set_customization(
    *, team: Team, user: User, context: str, layout: contracts.CustomizationLayout
) -> contracts.Customization:
    return customization.set_customization(team=team, user=user, context=context, layout=layout)


def reset_customization(*, team: Team, user: User, context: str) -> contracts.Customization:
    return customization.reset_customization(team=team, user_id=user.id, context=context)


def delete_fragments_for_teams(team_ids: list[int]) -> None:
    cleanup.delete_fragments_for_teams(team_ids)


def validate_customization_layout(*, context: str, layout: object) -> contracts.CustomizationLayout:
    return contexts.validate_layout(context=context, layout=layout)


def validate_customization_context(context: str) -> CustomizationContext:
    return contexts.resolve_context(context).context


def describe_customization(context: str) -> contracts.CustomizationDescription:
    return contexts.describe_context(context)
