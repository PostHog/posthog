import json
import hashlib
from datetime import timedelta
from typing import TYPE_CHECKING

from django.utils import timezone

from rest_framework.exceptions import PermissionDenied, ValidationError

from posthog.exceptions import Conflict
from posthog.models import Team, User
from posthog.models.team.extensions import get_or_create_team_extension
from posthog.models.team.team_marketing_analytics_config import TeamMarketingAnalyticsConfig

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.actions.backend.models.action import Action
from products.marketing_analytics.backend.models.conversion_setup import ConversionGoalPreviewEvidence

if TYPE_CHECKING:
    from products.marketing_analytics.backend.hogql_queries.attribution_base import ConversionGoal


class ConversionGoalEvidenceService:
    def __init__(self, team: Team, user: User) -> None:
        self.team = team
        self.user = user

    def context_hash(self, goal: "ConversionGoal") -> str:
        if goal.kind == "DataWarehouseNode":
            raise ValidationError(
                "Validated application currently supports events and existing actions. Use the warehouse goal editor for this source."
            )
        self.team.refresh_from_db(fields=["timezone", "base_currency", "test_account_filters"])
        config = get_or_create_team_extension(self.team, TeamMarketingAnalyticsConfig)
        source_version = None
        if goal.kind == "ActionsNode":
            source = Action.objects.filter(team_id=self.team.pk, pk=goal.id, deleted=False).first()
            if source is None:
                raise ValidationError(
                    {"goal": "This action is no longer available. Choose a source and preview again."}
                )
            if not UserAccessControl(self.user, team=self.team).check_access_level_for_object(source, "viewer"):
                raise PermissionDenied("You no longer have access to this action.")
            source_version = {"updated_at": source.updated_at.isoformat(), "steps": source.steps_json}
        payload = {
            "goals": config.conversion_goals,
            "attribution_window_days": config.attribution_window_days,
            "attribution_mode": config.attribution_mode,
            "filter_test_accounts": config.filter_test_accounts,
            "test_account_filters": self.team.test_account_filters,
            "timezone": self.team.timezone,
            "base_currency": self.team.base_currency,
            "source_version": source_version,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    def record(self, goal: "ConversionGoal", context_hash: str) -> ConversionGoalPreviewEvidence:
        if self.context_hash(goal) != context_hash:
            raise Conflict("The project or source changed during the preview. Preview again before saving.")
        expired_ids = list(
            ConversionGoalPreviewEvidence.objects.for_team(self.team.pk)
            .filter(expires_at__lte=timezone.now(), applied_goal__isnull=True)
            .order_by("expires_at")
            .values_list("pk", flat=True)[:500]
        )
        ConversionGoalPreviewEvidence.objects.for_team(self.team.pk).filter(
            pk__in=expired_ids, applied_goal__isnull=True
        ).delete()
        return ConversionGoalPreviewEvidence.objects.for_team(self.team.pk).create(
            team_id=self.team.pk,
            requested_by=self.user,
            goal=goal.model_dump(mode="json", exclude_none=True),
            context_hash=context_hash,
            expires_at=timezone.now() + timedelta(minutes=15),
        )

    def validate(self, evidence: ConversionGoalPreviewEvidence, goal: "ConversionGoal") -> None:
        if evidence.goal != goal.model_dump(mode="json", exclude_none=True):
            raise Conflict("This definition differs from the preview. Preview the edited goal before saving.")
        if evidence.expires_at <= timezone.now():
            raise Conflict("This preview has expired. Preview the goal again before saving.")
        if self.context_hash(goal) != evidence.context_hash:
            raise Conflict("The project or source changed after the preview. Preview again before saving.")
