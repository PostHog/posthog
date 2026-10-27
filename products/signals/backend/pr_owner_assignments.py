from __future__ import annotations

from datetime import timedelta
from typing import Literal

from django.utils import timezone

from posthog.dataclasses import frozen
from posthog.models.user import User
from posthog.models.user_integration import UserIntegration

from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.artefact_schemas import PROwnerAssignment, PROwnerIdentity, PROwnerIdentityProof
from products.signals.backend.models import SignalReportArtefact
from products.signals.backend.report_generation.resolve_reviewers import resolve_org_github_login_to_users

IDENTITY_PROOF_TTL = timedelta(days=30)
PROwnerOrigin = Literal["report", "claim", "legacy"]


@frozen
class OwnerIdentity:
    linked_user: bool
    proof: PROwnerIdentityProof | None


class PROwnerAssignmentService:
    def __init__(self, *, team_id: int, report_id: str, repository: str, pr_number: int) -> None:
        self.team_id = team_id
        self.report_id = report_id
        self.repository = repository
        self.pr_number = pr_number

    def latest(self) -> PROwnerAssignment | None:
        rows = SignalReportArtefact.objects.filter(
            team_id=self.team_id,
            report_id=self.report_id,
            type=SignalReportArtefact.ArtefactType.PR_OWNER_ASSIGNMENT,
        ).order_by("-created_at", "-id")[:20]
        for row in rows:
            assignment = PROwnerAssignment.model_validate_json(row.content)
            if assignment.repository == self.repository and assignment.pr_number == self.pr_number:
                return assignment
        return None

    def identities_for(self, logins: list[str]) -> dict[str, OwnerIdentity]:
        members = resolve_org_github_login_to_users(self.team_id, logins)
        return {login: self._identity_for_member(login, members.get(login)) for login in logins}

    def _identity_for_member(self, login: str, member: User | None) -> OwnerIdentity:
        if member is None:
            return OwnerIdentity(linked_user=False, proof=None)

        source = self._identity_source(member, login)
        if source is None:
            return OwnerIdentity(linked_user=True, proof=None)
        source_name, github_user_id = source
        now = timezone.now()
        return OwnerIdentity(
            linked_user=True,
            proof=PROwnerIdentityProof(
                source=source_name,
                user_uuid=member.uuid,
                github_user_id=github_user_id,
                verified_at=now,
                expires_at=now + IDENTITY_PROOF_TTL,
            ),
        )

    @staticmethod
    def _identity_source(
        member: User, login: str
    ) -> tuple[Literal["github_user_integration", "github_oauth"], int] | None:
        integrations = getattr(member, "_prefetched_github_user_integrations", None)
        if integrations is None:
            integrations = member.integrations.filter(kind=UserIntegration.IntegrationKind.GITHUB)
        for integration in integrations:
            github_user = integration.config.get("github_user")
            if not isinstance(github_user, dict) or str(github_user.get("login") or "").lower() != login:
                continue
            try:
                return "github_user_integration", int(github_user["id"])
            except (KeyError, TypeError, ValueError):
                return None

        social_accounts = getattr(member, "_prefetched_github_social_auth", None)
        if social_accounts is None:
            social_accounts = member.social_auth.filter(provider="github")
        for account in social_accounts:
            if str((account.extra_data or {}).get("login") or "").lower() != login:
                continue
            try:
                return "github_oauth", int(account.uid)
            except (TypeError, ValueError):
                return None
        return None

    def record(
        self,
        *,
        identities: dict[str, PROwnerIdentityProof | None],
        origin: PROwnerOrigin,
        replaced_logins: list[str] | None = None,
    ) -> PROwnerAssignment:
        assignment = PROwnerAssignment(
            repository=self.repository,
            pr_number=self.pr_number,
            owners=tuple(PROwnerIdentity(login=login, proof=proof) for login, proof in identities.items()),
            origin=origin,
            assigned_at=timezone.now(),
            replaced_logins=tuple(replaced_logins or ()),
        )
        SignalReportArtefact.add_log(
            team_id=self.team_id,
            report_id=self.report_id,
            content=assignment,
            attribution=ArtefactAttribution.system(),
        )
        return assignment
