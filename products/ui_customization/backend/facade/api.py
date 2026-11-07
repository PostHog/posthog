from posthog.models import Team, User

from ..logic import contexts, customization
from ..models import UserInterfaceFragment
from . import contracts
from .enums import CustomizationContext
from .feature_flags import is_enabled_for as is_enabled_for


def get_customization(*, team: Team, user: User, context: str) -> contracts.Customization:
    return customization.get_customization(team=team, user_id=user.id, context=context)


def set_customization(
    *, team: Team, user: User, context: str, layout: contracts.CustomizationLayout
) -> contracts.Customization:
    return customization.set_customization(team=team, user_id=user.id, context=context, layout=layout)


def reset_customization(*, team: Team, user: User, context: str) -> contracts.Customization:
    return customization.reset_customization(team=team, user_id=user.id, context=context)


def delete_fragments_for_teams(team_ids: list[int]) -> None:
    UserInterfaceFragment.objects.unscoped().filter(team_id__in=team_ids).delete()


def validate_customization_layout(*, context: str, layout: object) -> contracts.CustomizationLayout:
    return contexts.validate_layout(context=context, layout=layout)


def validate_customization_context(context: str) -> CustomizationContext:
    return contexts.resolve_context(context).context
