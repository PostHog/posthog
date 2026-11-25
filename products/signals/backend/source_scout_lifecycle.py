import uuid
from typing import TYPE_CHECKING, cast

from django.db import transaction

from rest_framework.request import Request

from posthog.models import Team, User

from products.signals.backend.models import SignalScoutConfig

if TYPE_CHECKING:
    from products.signals.backend.facade.api import ScoutLifecycleRequest


@transaction.atomic
def set_source_scout_enabled(
    *,
    team: Team,
    user: User,
    source_product: str,
    source_id: str,
    config_id: uuid.UUID,
    enabled: bool,
    request: "ScoutLifecycleRequest",
) -> SignalScoutConfig | None:
    request = cast(Request, request)
    from posthog.permissions import get_authenticator_scopes  # noqa: PLC0415

    from products.signals.backend.scout_harness.team_limits import max_enabled_scouts_for_team  # noqa: PLC0415
    from products.signals.backend.scout_harness.views import (  # noqa: PLC0415
        _upsert_scout_config,
        guard_scout_lifecycle_fields,
    )
    from products.signals.backend.trial.service import TrialService  # noqa: PLC0415

    config = (
        SignalScoutConfig.objects.for_team(team.id)
        .select_for_update()
        .filter(id=config_id, source_product=source_product, source_id=source_id)
        .first()
    )
    if config is None:
        return None
    if config.enabled != enabled:
        changes = {"enabled": enabled}
        guard_scout_lifecycle_fields(
            request=request,
            team=team,
            skill_name=config.skill_name,
            config=config,
            requested=changes,
            action="partial_update",
        )
        with TrialService(team).enroll_on_activation(
            user=user, api_scopes=get_authenticator_scopes(request.successful_authenticator), enabled=enabled
        ):
            config, _ = _upsert_scout_config(
                team_id=team.id,
                skill_name=config.skill_name,
                tunables=changes,
                request=request,
                max_enabled_scouts=max_enabled_scouts_for_team(team.id),
                serializer_context={"team": team, "project_id": team.project_id, "request": request},
            )
    return config
