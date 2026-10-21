from __future__ import annotations

import json
import hashlib
from typing import Literal
from uuid import UUID, uuid4

from django.db import transaction
from django.db.models import Q, QuerySet

from pydantic import BaseModel, ConfigDict, Field, model_validator

from posthog.dataclasses import frozen
from posthog.models.team.team import Team

from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.artefact_schemas import (
    AssignmentDecision,
    ReviewerControl,
    ReviewerState,
    SuggestedReviewerEntry,
    SuggestedReviewers,
)
from products.signals.backend.assignment_flags import assignment_side_effects_enabled, assignment_writer_enabled
from products.signals.backend.models import SignalReport, SignalReportArtefact, SignalReportAssignmentRevision
from products.signals.backend.report_claims import actor_owns_claim, get_active_claim
from products.signals.backend.report_generation.resolve_reviewers import (
    bounded_reviewer_reason,
    get_org_member_github_logins_by_user_uuid,
    resolve_org_github_login_to_users,
)


class AssignmentWriteError(ValueError):
    pass


class StaleAssignmentProposal(AssignmentWriteError):
    pass


class AssignmentOperationConflict(AssignmentWriteError):
    pass


class AssignmentClaimConflict(AssignmentWriteError):
    pass


class AssignmentProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    operation_id: UUID
    expected_state: ReviewerState
    source: str = Field(min_length=1, max_length=100)
    action: Literal["automatic", "replace", "remove", "cleanup"] = "automatic"
    outcome: Literal["selected", "no_suitable_owner", "lookup_failed"] = "selected"
    reviewers: tuple[SuggestedReviewerEntry, ...] = ()
    retry_reason: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def validate_outcome(self) -> AssignmentProposal:
        if self.outcome == "lookup_failed" and not self.retry_reason:
            raise ValueError("A failed lookup needs a retry reason.")
        if self.outcome != "selected" and self.reviewers:
            raise ValueError("An unsuccessful selection cannot propose reviewers.")
        if self.action != "automatic" and self.outcome != "selected":
            raise ValueError("Only an automatic proposal can report a failed or empty selection.")
        if self.action == "cleanup" and self.reviewers:
            raise ValueError("This operation cannot supply reviewers.")
        return self


@frozen
class AssignmentSnapshot:
    state: ReviewerState
    control: Literal["human", "automatic"]
    reviewers: tuple[SuggestedReviewerEntry, ...]
    human_editor_id: int | None


@frozen
class AssignmentWrite:
    reviewers_artefact: SignalReportArtefact
    changed: bool
    replayed: bool = False
    decision: AssignmentDecision | None = None


@frozen
class EligibleReviewers:
    reviewers: tuple[SuggestedReviewerEntry, ...]
    ineligible_user_uuids: tuple[str, ...]
    unresolved_candidates: tuple[SuggestedReviewerEntry, ...]


class ReportAssignmentService:
    def __init__(self, *, team: Team, report_id: str) -> None:
        self.team = team
        self.report_id = report_id
        # Resolve remote controls before callers acquire the report lock.
        self.enabled = assignment_writer_enabled(team.id)
        self.effects_enabled = assignment_side_effects_enabled(team.id)

    def _artefacts(self) -> QuerySet[SignalReportArtefact]:
        return SignalReportArtefact.objects.filter(team_id=self.team.id, report_id=self.report_id)

    def _revisions(self) -> QuerySet[SignalReportAssignmentRevision]:
        return SignalReportAssignmentRevision.objects.for_team(self.team.id).filter(report_id=self.report_id)

    def has_applied(self, operation_id: UUID) -> bool:
        return self._revisions().filter(operation_id=operation_id).exists()

    def latest_decision(self) -> AssignmentDecision | None:
        revision = self._revisions().select_related("artefact").order_by("-revision").first()
        return AssignmentDecision.model_validate_json(revision.artefact.content) if revision else None

    @staticmethod
    def _read_reviewers(artefact: SignalReportArtefact | None) -> tuple[SuggestedReviewerEntry, ...]:
        if artefact is None:
            return ()
        content = json.loads(artefact.content)
        if isinstance(content, list):
            for entry in content:
                if isinstance(entry, dict):
                    entry["reason"] = bounded_reviewer_reason(entry.get("reason"))
                    for commit in entry.get("relevant_commits") or []:
                        if isinstance(commit, dict):
                            commit["reason"] = bounded_reviewer_reason(commit.get("reason")) or ""
        return tuple(SuggestedReviewers.model_validate(content).root)

    def read(self) -> AssignmentSnapshot:
        return self.read_for_report(team_id=self.team.id, report_id=self.report_id)

    @classmethod
    def read_for_report(cls, *, team_id: int, report_id: str) -> AssignmentSnapshot:
        SignalReport.objects.get(team_id=team_id, id=report_id)
        rows = SignalReportArtefact.objects.filter(team_id=team_id, report_id=report_id)
        reviewers = rows.filter(type="suggested_reviewers").order_by("-created_at", "-id").first()
        control = rows.filter(type="reviewer_control").order_by("-created_at", "-id").first()
        human = (
            rows.filter(type__in=["suggested_reviewers", "reviewer_control"])
            .filter(Q(actor_kind="user") | Q(actor_kind__isnull=True, created_by__isnull=False))
            .order_by("-created_at", "-id")
            .first()
        )
        mode: Literal["human", "automatic"] = (
            "human" if human else ReviewerControl.model_validate_json(control.content).mode if control else "automatic"
        )
        return AssignmentSnapshot(
            state=ReviewerState(
                reviewers_id=reviewers.id if reviewers else None, control_id=control.id if control else None
            ),
            control=mode,
            reviewers=cls._read_reviewers(reviewers),
            human_editor_id=human.created_by_id if human else None,
        )

    def _validate_members(self, reviewers: tuple[SuggestedReviewerEntry, ...]) -> EligibleReviewers:
        unresolved_logins = {
            entry.github_login.lower() for entry in reviewers if entry.github_login and not entry.user_uuid
        }
        members = resolve_org_github_login_to_users(self.team.id, unresolved_logins) if unresolved_logins else {}
        resolved: list[SuggestedReviewerEntry] = []
        unresolved: list[SuggestedReviewerEntry] = []
        for entry in reviewers:
            if entry.user_uuid:
                try:
                    UUID(entry.user_uuid)
                except ValueError as error:
                    raise AssignmentWriteError("A reviewer must have a valid user UUID.") from error
            member = members.get(entry.github_login.lower()) if entry.github_login and not entry.user_uuid else None
            if member:
                entry = entry.model_copy(update={"user_uuid": str(member.uuid)})
            if entry.user_uuid:
                resolved.append(entry)
            else:
                unresolved.append(entry)
        wanted = {entry.user_uuid for entry in resolved if entry.user_uuid}
        eligible = {str(user.uuid) for user in self.team.all_users_with_access(user_uuids=wanted)} if wanted else set()
        logins = get_org_member_github_logins_by_user_uuid(self.team.id, sorted(eligible)) if eligible else {}
        accepted = {
            entry.user_uuid: entry.model_copy(update={"github_login": logins.get(entry.user_uuid)})
            for entry in resolved
            if entry.user_uuid in eligible
        }
        return EligibleReviewers(
            reviewers=tuple(accepted.values()),
            ineligible_user_uuids=tuple(sorted(wanted - eligible)),
            unresolved_candidates=tuple(unresolved),
        )

    def apply(
        self,
        proposal: AssignmentProposal,
        *,
        actor: ArtefactAttribution,
        reevaluate_autostart: bool = False,
        claim_id: str | None = None,
    ) -> AssignmentWrite:
        request_hash = hashlib.sha256(
            (proposal.model_dump_json() + repr(actor) + (claim_id or "")).encode()
        ).hexdigest()
        with transaction.atomic():
            SignalReport.objects.select_for_update().exclude(status=SignalReport.Status.DELETED).get(
                team_id=self.team.id, id=self.report_id
            )
            existing = (
                self._revisions()
                .select_related("artefact", "reviewers_artefact")
                .filter(operation_id=proposal.operation_id)
                .first()
            )
            if existing:
                if existing.request_hash != request_hash:
                    raise AssignmentOperationConflict("This operation ID belongs to a different reviewer request.")
                return AssignmentWrite(
                    reviewers_artefact=existing.reviewers_artefact,
                    decision=AssignmentDecision.model_validate_json(existing.artefact.content),
                    changed=False,
                    replayed=True,
                )
            if claim_id:
                claim = get_active_claim(team_id=self.team.id, report_id=self.report_id)
                if claim is None or str(claim.claim_id) != claim_id or not actor_owns_claim(claim, actor):
                    raise AssignmentClaimConflict("Claim is stale or belongs to another actor.")
            snapshot = self.read()
            if proposal.expected_state != snapshot.state:
                raise StaleAssignmentProposal(
                    "Reviewers or their control changed. Read the report again before selecting reviewers."
                )
            if proposal.action in {"replace", "remove"} and actor.kind != "user":
                raise AssignmentWriteError("Only a person can change reviewer control.")
            if not self.enabled and (snapshot.state.control_id is None or proposal.action == "automatic"):
                raise AssignmentWriteError("Automatic reviewer writes are paused.")

            control = snapshot.control
            proposed = proposal.reviewers
            if proposal.action in {"replace", "remove"}:
                control = "human"
            elif proposal.action == "cleanup" or snapshot.control == "human" or proposal.outcome == "lookup_failed":
                proposed = snapshot.reviewers
            if proposal.action in {"replace", "remove"}:
                old_uuids = {entry.user_uuid for entry in snapshot.reviewers if entry.user_uuid}
                old_logins = {entry.github_login.lower() for entry in snapshot.reviewers if entry.github_login}
                additions = tuple(
                    entry
                    for entry in proposed
                    if entry.user_uuid not in old_uuids
                    and (not entry.github_login or entry.github_login.lower() not in old_logins)
                )
                checked_additions = self._validate_members(additions)
                if checked_additions.ineligible_user_uuids or checked_additions.unresolved_candidates:
                    raise AssignmentWriteError("New reviewers must be active members with access to this project.")
            validated = self._validate_members(proposed)
            current = (
                self._artefacts().filter(id=snapshot.state.reviewers_id).first()
                if snapshot.state.reviewers_id
                else None
            )
            changed = validated.reviewers != snapshot.reviewers
            if changed or current is None:
                current = SignalReportArtefact.append_status(
                    team_id=self.team.id,
                    report_id=self.report_id,
                    content=SuggestedReviewers(root=list(validated.reviewers)),
                    attribution=actor,
                    claim_id=claim_id,
                    reevaluate_autostart=False,
                    assignment_writer=True,
                )
            if control != snapshot.control or snapshot.state.control_id is None:
                SignalReportArtefact.append_status(
                    team_id=self.team.id,
                    report_id=self.report_id,
                    content=ReviewerControl(mode=control),
                    attribution=actor,
                    claim_id=claim_id,
                    assignment_writer=True,
                )
            latest_revision = self._revisions().order_by("-revision").values_list("revision", flat=True).first() or 0
            decision = AssignmentDecision(
                operation_id=proposal.operation_id,
                revision=latest_revision + 1,
                source=proposal.source,
                outcome=proposal.outcome,
                control=control,
                expected_state=proposal.expected_state,
                retry_reason=proposal.retry_reason,
                ineligible_user_uuids=validated.ineligible_user_uuids,
                unresolved_candidates=validated.unresolved_candidates,
            )
            artefact = SignalReportArtefact.add_log(
                team_id=self.team.id,
                report_id=self.report_id,
                content=decision,
                attribution=actor,
                claim_id=claim_id,
            )
            self._revisions().create(
                team_id=self.team.id,
                report_id=self.report_id,
                revision=decision.revision,
                operation_id=proposal.operation_id,
                request_hash=request_hash,
                artefact=artefact,
                reviewers_artefact=current,
            )
            if (
                changed
                and reevaluate_autostart
                and self.effects_enabled
                and proposal.action not in {"remove", "cleanup"}
            ):
                SignalReportArtefact._schedule_autostart_reevaluation(team_id=self.team.id, report_id=self.report_id)
            return AssignmentWrite(reviewers_artefact=current, changed=changed, decision=decision)

    def apply_compatibility_reviewers(
        self,
        reviewers: SuggestedReviewers,
        *,
        actor: ArtefactAttribution,
        expected_state: ReviewerState | None = None,
        operation_id: UUID | None = None,
        outcome: Literal["selected", "no_suitable_owner", "lookup_failed"] = "selected",
        retry_reason: str | None = None,
        claim_id: str | None = None,
        source: str = "artefact_api",
        reevaluate_autostart: bool = True,
    ) -> AssignmentWrite:
        with transaction.atomic():
            SignalReport.objects.select_for_update().exclude(status=SignalReport.Status.DELETED).get(
                team_id=self.team.id, id=self.report_id
            )
            if claim_id:
                claim = get_active_claim(team_id=self.team.id, report_id=self.report_id)
                if claim is None or str(claim.claim_id) != claim_id or not actor_owns_claim(claim, actor):
                    raise AssignmentClaimConflict("Claim is stale or belongs to another actor.")
            snapshot = self.read()
            if not self.enabled and snapshot.state.control_id is None:
                if source == "research" and snapshot.state.reviewers_id is not None:
                    exclusions = {
                        "__all__": {"reason": True, "github_name": True, "relevant_commits": {"__all__": {"reason"}}}
                    }
                    current = SuggestedReviewers(root=list(snapshot.reviewers))
                    if snapshot.control == "human" or current.model_dump(exclude=exclusions) == reviewers.model_dump(
                        exclude=exclusions
                    ):
                        return AssignmentWrite(
                            reviewers_artefact=self._artefacts().get(id=snapshot.state.reviewers_id), changed=False
                        )
                artefact = SignalReportArtefact.append_status(
                    team_id=self.team.id,
                    report_id=self.report_id,
                    content=reviewers,
                    attribution=actor,
                    claim_id=claim_id,
                    reevaluate_autostart=reevaluate_autostart,
                    assignment_writer=True,
                )
                return AssignmentWrite(reviewers_artefact=artefact, changed=True)
            if not self.enabled:
                if snapshot.state.reviewers_id is None:
                    raise AssignmentWriteError("Reviewer control has no saved list.")
                return AssignmentWrite(
                    reviewers_artefact=self._artefacts().get(id=snapshot.state.reviewers_id),
                    changed=False,
                )
            if expected_state is None or operation_id is None:
                raise StaleAssignmentProposal(
                    "Read reviewer_state before selecting reviewers and supply it with a stable operation_id."
                )
            if outcome == "selected" and not reviewers.root:
                outcome = "no_suitable_owner"
            return self.apply(
                AssignmentProposal(
                    operation_id=operation_id,
                    expected_state=expected_state,
                    source=source,
                    reviewers=tuple(reviewers.root),
                    outcome=outcome,
                    retry_reason=retry_reason,
                ),
                actor=actor,
                claim_id=claim_id,
                reevaluate_autostart=reevaluate_autostart,
            )

    def edit_reviewers(
        self,
        reviewers: SuggestedReviewers,
        *,
        actor: ArtefactAttribution,
        removal: bool = False,
    ) -> SignalReportArtefact:
        if actor.kind != "user":
            raise AssignmentWriteError("Only a person can change reviewer control.")
        with transaction.atomic():
            SignalReport.objects.select_for_update().exclude(status=SignalReport.Status.DELETED).get(
                team_id=self.team.id, id=self.report_id
            )
            snapshot = self.read()
            if not self.enabled and snapshot.state.control_id is None:
                return SignalReportArtefact.append_status(
                    team_id=self.team.id,
                    report_id=self.report_id,
                    content=reviewers,
                    attribution=actor,
                    reevaluate_autostart=not removal,
                    assignment_writer=True,
                )
            return self.apply(
                AssignmentProposal(
                    operation_id=uuid4(),
                    expected_state=snapshot.state,
                    source="reviewer_api",
                    action="remove" if removal else "replace",
                    reviewers=tuple(reviewers.root),
                ),
                actor=actor,
                reevaluate_autostart=not removal,
            ).reviewers_artefact
