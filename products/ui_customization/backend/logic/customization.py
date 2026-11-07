from django.db import IntegrityError, router, transaction
from django.utils import timezone

import structlog
from pydantic import ValidationError

from posthog.models import Team

from ..facade.contracts import Customization, CustomizationLayout
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


def set_customization(*, team: Team, user_id: int, context: str, layout: CustomizationLayout) -> Customization:
    definition = resolve_context(context)
    validated = definition.layout_schema.model_validate(layout)
    team_id = team.parent_team_id or team.id
    stored = validated.model_dump(mode="json", exclude_none=True)
    try:
        with transaction.atomic(using=router.db_for_write(UserInterfaceFragment)):
            UserInterfaceFragment.objects.for_team(team_id, canonical=True).update_or_create(
                team_id=team_id, user_id=user_id, context=definition.context, defaults={"content": stored}
            )
    except IntegrityError:
        UserInterfaceFragment.objects.for_team(team_id, canonical=True).filter(
            user_id=user_id, context=definition.context
        ).update(content=stored, updated_at=timezone.now())
    return Customization(layout=validated, customized=True)


def reset_customization(*, team: Team, user_id: int, context: str) -> Customization:
    definition = resolve_context(context)
    UserInterfaceFragment.objects.for_team(team.parent_team_id or team.id, canonical=True).filter(
        user_id=user_id, context=definition.context
    ).delete()
    return Customization(layout=definition.defaults, customized=False)
