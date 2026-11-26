from django.db import router, transaction

import structlog
from pydantic import ValidationError

from posthog.models import Team, User

from ..facade.contracts import Customization, CustomizationLayout, UnavailableTargets
from ..models import UserInterfaceFragment
from .contexts import resolve_context

logger = structlog.get_logger(__name__)


def get_customization(*, team: Team, user_id: int, context: str) -> Customization:
    definition = resolve_context(context)
    row = (
        UserInterfaceFragment.objects.for_team(team.parent_team_id or team.id, canonical=True)
        .filter(user_id=user_id, context=definition.context)
        .first()
    )
    if row is not None:
        try:
            return Customization(layout=definition.layout_schema.model_validate(row.content), customized=True)
        except ValidationError:
            # The row stays, so a rolled-back deploy that does not know a newer value gets the layout back on the next one.
            logger.warning("ui_customization_invalid", team_id=row.team_id, user_id=user_id, context=definition.context)
    return Customization(layout=definition.defaults, customized=False)


def set_customization(*, team: Team, user: User, context: str, layout: CustomizationLayout) -> Customization:
    # Imported here so team deletion, which imports this module, does not load three other products' facades.
    from .targets import unavailable_targets  # noqa: PLC0415

    definition = resolve_context(context)
    validated = definition.layout_schema.model_validate(layout)
    if problems := unavailable_targets(team=team, user=user, layout=validated):
        raise UnavailableTargets(problems)
    team_id = team.parent_team_id or team.id
    stored = validated.model_dump(mode="json", exclude_none=True)
    with transaction.atomic(using=router.db_for_write(UserInterfaceFragment)):
        UserInterfaceFragment.objects.for_team(team_id, canonical=True).update_or_create(
            team_id=team_id, user_id=user.id, context=definition.context, defaults={"content": stored}
        )
    return Customization(layout=validated, customized=True)


def reset_customization(*, team: Team, user_id: int, context: str) -> Customization:
    definition = resolve_context(context)
    UserInterfaceFragment.objects.for_team(team.parent_team_id or team.id, canonical=True).filter(
        user_id=user_id, context=definition.context
    ).delete()
    return Customization(layout=definition.defaults, customized=False)
