from __future__ import annotations

from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from rest_framework.exceptions import APIException

from posthog.egress.limiter.policies import Priority
from posthog.event_usage import groups
from posthog.models.integration import GitHubIntegration, Integration
from posthog.models.integration.github_readiness import GitHubReadinessStatus, github_readiness
from posthog.models.user import User
from posthog.ph_client import ph_scoped_capture

from products.replay_vision.backend.facade.api import has_signal_emitting_scanner
from products.signals.backend.models import SignalScoutConfig, SignalSourceConfig, SignalTeamConfig
from products.signals.backend.onboarding_analytics import InboxOnboardingAnalytics


class RepositoryCheckUnavailable(APIException):
    status_code = 503
    default_detail = "Could not verify GitHub access. Please retry activation shortly."
    default_code = "repository_check_unavailable"

    def __init__(self, retry_after: int = 0) -> None:
        super().__init__()
        self.retry_after = retry_after


class InboxOnboardingReconciler:
    def __init__(self, team_id: int, *, priority: Priority = Priority.NORMAL) -> None:
        self.team_id = team_id
        self.priority = priority

    @staticmethod
    def scouts_can_emit(team_id: int) -> bool:
        return SignalSourceConfig.is_source_enabled(
            team_id, SignalSourceConfig.SourceProduct.SIGNALS_SCOUT, SignalSourceConfig.SourceType.CROSS_SOURCE_ISSUE
        )

    def run(self) -> bool:
        """Verify control completion; return whether another check is needed."""
        config = (
            SignalTeamConfig.objects.select_related("team", "team__organization").filter(team_id=self.team_id).first()
        )
        if config is None:
            return False
        state = config.onboarding or {}
        exposed_at = parse_datetime(state.get("exposed_at", ""))
        if (
            state.get("variant") != "control"
            or state.get("completed_at")
            or state.get("draft") is not None
            or exposed_at is None
            or timezone.now() - exposed_at > timedelta(days=7)
        ):
            return False
        sources_enabled = (
            SignalSourceConfig.objects.filter(team_id=self.team_id, enabled=True)
            .exclude(source_product__in=["signals_scout", "session_replay"])
            .exists()
        )
        scout_team_id = config.team.parent_team_id or self.team_id
        scouts_enabled = self.scouts_can_emit(scout_team_id) and (
            SignalScoutConfig.objects.for_team(config.team.parent_team_id or self.team_id)
            .filter(enabled=True, emit=True)
            .exclude(managed_by="background")
            .exclude(auto_pause_exempt_by_role=True)
            .exists()
        )
        if not (sources_enabled or scouts_enabled or has_signal_emitting_scanner(self.team_id)):
            return True
        if not self.has_repository():
            return True
        with transaction.atomic():
            locked = SignalTeamConfig.objects.select_for_update().get(pk=config.pk, team_id=self.team_id)
            state = locked.onboarding or {}
            if state.get("draft") is not None:
                return False
            if not state.get("completed_at"):
                locked.onboarding = {**state, "completed_at": timezone.now().isoformat()}
                locked.save(update_fields=["onboarding", "updated_at"])
                transaction.on_commit(lambda: self._capture(locked), robust=True)
        return False

    def has_repository(self) -> bool:
        temporarily_unavailable = False
        retry_after = 0
        for integration in Integration.objects.filter(team_id=self.team_id, kind="github").order_by("id"):
            readiness = github_readiness(
                GitHubIntegration(integration, source="signals_onboarding", priority=self.priority),
                verify=True,
                refresh_cache=False,
            )
            if readiness.status == GitHubReadinessStatus.READY:
                return True
            temporarily_unavailable |= readiness.status == GitHubReadinessStatus.TEMPORARILY_UNAVAILABLE
            retry_after = max(retry_after, readiness.retry_after)
        if temporarily_unavailable:
            raise RepositoryCheckUnavailable(retry_after=retry_after)
        return False

    def _capture(self, config: SignalTeamConfig) -> None:
        user = User.objects.filter(pk=(config.onboarding or {}).get("exposed_by")).first()
        with ph_scoped_capture() as capture:
            capture(
                distinct_id=str(user.distinct_id if user else config.team.uuid),
                event="self-driving onboarding completed",
                groups=groups(team=config.team),
                properties=InboxOnboardingAnalytics.completion_properties(config, user),
            )
