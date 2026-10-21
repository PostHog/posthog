from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

from django.db import transaction
from django.utils import timezone

import structlog
from asgiref.sync import async_to_sync

from posthog.dataclasses import frozen
from posthog.models import Team
from posthog.models.integration import GitHubIntegration

from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.artefact_schemas import PROwnerDecision, PROwnerInput, PROwnerSelection
from products.signals.backend.assignment_service import AssignmentSnapshot, ReportAssignmentService
from products.signals.backend.models import SignalReport, SignalReportArtefact, SignalUserAutonomyConfig
from products.signals.backend.pr_owner_evidence import PROwnerEvidenceReader, report_owner_version
from products.signals.backend.pr_owner_selection import owner_input_version, select_pr_owner, validate_owner_decision

logger = structlog.get_logger(__name__)
FAILURE_RETRY_AFTER = timedelta(minutes=10)


@frozen
class EligiblePROwners:
    logins: frozenset[str]
    opted_in: frozenset[str]


class PROwnerDecisionService:
    def __init__(self, *, team_id: int, report_id: str, github: GitHubIntegration) -> None:
        self.team = Team.objects.get(id=team_id)
        self.report_id = report_id
        self.github = github
        self.log = logger.bind(team_id=team_id, report_id=report_id)

    def inputs(self, *, repository: str, pr_number: int, head_sha: str, base_sha: str) -> PROwnerInput:
        report = SignalReport.objects.get(team_id=self.team.id, id=self.report_id)
        snapshot = ReportAssignmentService.read_for_report(team_id=self.team.id, report_id=self.report_id)
        return PROwnerInput(
            repository=repository,
            pr_number=pr_number,
            head_sha=head_sha,
            base_sha=base_sha,
            report_state=snapshot.state,
            report_version=report_owner_version(report),
        )

    @staticmethod
    def same_scope(left: PROwnerInput, right: PROwnerInput) -> bool:
        excluded = {"paths", "identities", "evidence"}
        return left.model_dump(exclude=excluded) == right.model_dump(exclude=excluded)

    def _saved(self, inputs: PROwnerInput) -> PROwnerSelection | None:
        rows = SignalReportArtefact.objects.filter(
            team_id=self.team.id, report_id=self.report_id, type="pr_owner_selection"
        ).order_by("-created_at", "-id")[:20]
        for row in rows:
            saved = PROwnerSelection.model_validate_json(row.content)
            if not self.same_scope(saved.inputs, inputs):
                continue
            if owner_input_version(saved.inputs) != saved.input_version:
                raise ValueError("Stored owner input version does not match")
            validate_owner_decision(saved.decision, saved.inputs)
            if saved.decision.outcome == "lookup_failed" and row.created_at < timezone.now() - FAILURE_RETRY_AFTER:
                return None
            return saved
        return None

    def prepare(self, inputs: PROwnerInput, snapshot: AssignmentSnapshot) -> PROwnerSelection | None:
        if saved := self._saved(inputs):
            self.log.info("signals.pr_owner.selection_reused", outcome=saved.decision.outcome)
            return saved
        try:
            report = SignalReport.objects.get(team_id=self.team.id, id=self.report_id)
            inputs = PROwnerEvidenceReader(self.github, team=self.team, report=report).collect(inputs, snapshot)
        except Exception as error:
            self.log.warning("signals.pr_owner.lookup_failed", error_type=type(error).__name__)
            decision = PROwnerDecision(outcome="lookup_failed", reason=f"evidence_lookup_failed:{type(error).__name__}")
        else:
            try:
                decision = async_to_sync(select_pr_owner)(inputs, team_id=self.team.id, trace_id=str(uuid4()))
                validate_owner_decision(decision, inputs)
            except ValueError:
                self.log.warning("signals.pr_owner.validation_rejected")
                decision = PROwnerDecision(outcome="lookup_failed", reason="selection_validation_rejected")
            except Exception as error:
                self.log.warning("signals.pr_owner.selection_failed", error_type=type(error).__name__)
                decision = PROwnerDecision(outcome="lookup_failed", reason="selection_lookup_failed")

        selected = PROwnerSelection(input_version=owner_input_version(inputs), inputs=inputs, decision=decision)
        with transaction.atomic():
            SignalReport.objects.select_for_update().get(team_id=self.team.id, id=self.report_id)
            current = self.inputs(
                repository=inputs.repository,
                pr_number=inputs.pr_number,
                head_sha=inputs.head_sha,
                base_sha=inputs.base_sha,
            )
            if not self.same_scope(current, inputs):
                self.log.info("signals.pr_owner.stale")
                return None
            if saved := self._saved(inputs):
                return saved
            SignalReportArtefact.add_log(
                team_id=self.team.id,
                report_id=self.report_id,
                content=selected,
                attribution=ArtefactAttribution.system(),
            )
        self.log.info("signals.pr_owner.selected", outcome=decision.outcome, candidates=len(decision.candidates))
        return selected

    def eligible_logins(self, selected: PROwnerSelection) -> EligiblePROwners:
        wanted = {candidate.login for candidate in selected.decision.candidates}
        identities = [identity for identity in selected.inputs.identities if identity.login in wanted]
        uuids = [str(identity.user_uuid) for identity in identities if identity.user_uuid]
        members = list(self.team.all_users_with_access(user_uuids=uuids).filter(is_active=True)) if uuids else []
        logins = {
            str(member.uuid): login.lower()
            for member in members
            if (login := member.get_github_login(include_team_fallback=False))
        }
        opted_in_ids = set(
            SignalUserAutonomyConfig.objects.filter(
                user_id__in=[member.id for member in members], github_assign_on_pull_request=True
            ).values_list("user_id", flat=True)
        )
        opted_in = {
            logins[str(member.uuid)] for member in members if member.id in opted_in_ids and str(member.uuid) in logins
        }
        eligible: set[str] = set()
        team_logins: dict[str, set[str]] = {}
        for identity in identities:
            if identity.user_uuid:
                if logins.get(str(identity.user_uuid)) == identity.login:
                    eligible.add(identity.login)
                continue
            for slug in identity.teams:
                if slug not in team_logins:
                    result = self.github.list_team_members(selected.inputs.repository.split("/", 1)[0], slug)
                    if not result.get("success"):
                        raise ValueError("Current team membership unavailable")
                    team_logins[slug] = {login.lower() for login in result["logins"]}
                if identity.login in team_logins[slug]:
                    eligible.add(identity.login)
        return EligiblePROwners(logins=frozenset(eligible), opted_in=frozenset(opted_in))
