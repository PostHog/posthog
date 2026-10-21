from __future__ import annotations

import json
import hashlib
from typing import Literal
from uuid import UUID, uuid4

from django.db import transaction
from django.db.models import QuerySet

from pydantic import BaseModel, ConfigDict, Field, model_validator

from posthog.dataclasses import frozen
from posthog.models.team.team import Team

from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.artefact_schemas import (
    AssignedPerson,
    AssignmentDecision,
    AssignmentOverrides,
    AssignmentSelection,
    SuggestedReviewerEntry,
    SuggestedReviewers,
)
from products.signals.backend.assignment_flags import (
    assignment_agent_selection_enabled,
    assignment_human_writer_enabled,
    assignment_side_effects_enabled,
)
from products.signals.backend.models import SignalReport, SignalReportArtefact, SignalReportAssignmentRevision
from products.signals.backend.report_claims import actor_owns_claim, get_active_claim
from products.signals.backend.report_generation.resolve_reviewers import (
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
    expected_revision: int = Field(ge=0)
    evidence_revision: str = Field(min_length=1)
    source: str = Field(min_length=1, max_length=100)
    policy_version: str = Field(min_length=1, max_length=100)
    action: Literal["automatic", "replace", "remove", "resume"] = "automatic"
    outcome: Literal["selected", "no_suitable_owner", "lookup_failed"] = "selected"
    selection: AssignmentSelection = Field(default_factory=AssignmentSelection)
    reviewers: tuple[SuggestedReviewerEntry, ...] = ()
    retry_reason: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def validate_outcome(self) -> AssignmentProposal:
        if self.outcome == "lookup_failed" and not self.retry_reason:
            raise ValueError("A failed lookup needs a retry reason.")
        if self.outcome != "selected" and self.selection != AssignmentSelection():
            raise ValueError("An unsuccessful selection cannot propose assignments.")
        if self.action != "automatic" and self.outcome != "selected":
            raise ValueError("A human edit must have a successful outcome.")
        if self.action != "automatic" and self.selection != AssignmentSelection():
            raise ValueError("A reviewer edit cannot also submit an automatic selection.")
        if self.action in {"automatic", "resume"} and self.reviewers:
            raise ValueError("Only a reviewer edit can replace the compatibility list.")
        return self


@frozen
class AssignmentSnapshot:
    revision: int
    evidence_revision: str
    selection: AssignmentSelection
    overrides: AssignmentOverrides
    reviewers: tuple[SuggestedReviewerEntry, ...]


@frozen
class AssignmentWrite:
    decision: AssignmentDecision
    reviewers_artefact: SignalReportArtefact
    replayed: bool


@frozen
class AssignmentEdit:
    selection: AssignmentSelection
    overrides: AssignmentOverrides


@frozen
class EligibleAssignment:
    selection: AssignmentSelection
    ineligible_user_uuids: tuple[str, ...]


def _identity(entry: SuggestedReviewerEntry) -> str:
    return entry.user_uuid or f"github:{(entry.github_login or '').lower()}"


def _same_person(left: SuggestedReviewerEntry, right: SuggestedReviewerEntry) -> bool:
    if left.user_uuid and right.user_uuid:
        return left.user_uuid == right.user_uuid
    return bool(left.github_login and right.github_login and left.github_login.lower() == right.github_login.lower())


def _evidence_revision(report: SignalReport) -> str:
    evidence = list(
        SignalReportArtefact.objects.filter(
            team_id=report.team_id,
            report_id=report.id,
            type__in=["signal_finding", "repo_selection", "code_reference"],
        )
        .order_by("id")
        .values_list("id", "updated_at")
    )
    value = [report.title, report.summary, report.signal_count, report.total_weight, evidence]
    return hashlib.sha256(json.dumps(value, default=str).encode()).hexdigest()


class ReportAssignmentService:
    def __init__(self, *, team: Team, report_id: str) -> None:
        self.team = team
        self.report_id = report_id

    def _revisions(self) -> QuerySet[SignalReportAssignmentRevision]:
        return SignalReportAssignmentRevision.objects.for_team(self.team.id).filter(report_id=self.report_id)

    def _snapshot(self, report: SignalReport) -> AssignmentSnapshot:
        latest = self._revisions().select_related("artefact").order_by("-revision").first()
        decision = AssignmentDecision.model_validate_json(latest.artefact.content) if latest else None
        reviewers = SignalReportArtefact.latest_content(
            team_id=self.team.id, report_id=self.report_id, model=SuggestedReviewers
        )
        return AssignmentSnapshot(
            revision=latest.revision if latest else 0,
            evidence_revision=_evidence_revision(report),
            selection=decision.selection
            if decision
            else AssignmentSelection(suggestions=tuple(reviewers.root) if reviewers else ()),
            overrides=decision.overrides if decision else AssignmentOverrides(),
            reviewers=tuple(reviewers.root) if reviewers else (),
        )

    def read(self) -> AssignmentSnapshot:
        report = SignalReport.objects.get(team_id=self.team.id, id=self.report_id)
        return self._snapshot(report)

    def _human_edit(self, snapshot: AssignmentSnapshot, proposal: AssignmentProposal) -> AssignmentEdit:
        wanted = {_identity(entry) for entry in proposal.reviewers}
        assigned = {_identity(entry) for entry in snapshot.selection.people}
        added = {_identity(entry): entry for entry in snapshot.overrides.additions if _identity(entry) in wanted}
        people: list[AssignedPerson] = []
        suggestions: list[SuggestedReviewerEntry] = []
        for entry in proposal.reviewers:
            identity = _identity(entry)
            was_suggested = any(_same_person(entry, prior) for prior in snapshot.reviewers)
            if entry.user_uuid and (not was_suggested or identity in assigned):
                person = AssignedPerson.model_validate(entry.model_dump())
                people.append(person)
                if not was_suggested:
                    added[identity] = person
            else:
                suggestions.append(entry)
        removed = [
            entry for entry in snapshot.reviewers if not any(_same_person(entry, kept) for kept in proposal.reviewers)
        ]
        removed_uuids = set(snapshot.overrides.removed_user_uuids)
        removed_logins = set(snapshot.overrides.removed_github_logins)
        removed_uuids.update(entry.user_uuid for entry in removed if entry.user_uuid)
        removed_logins.update(
            entry.github_login.lower() for entry in removed if entry.github_login and not entry.user_uuid
        )
        removed_members = resolve_org_github_login_to_users(self.team.id, removed_logins)
        removed_uuids.update(str(member.uuid) for member in removed_members.values())
        removed_logins.difference_update(removed_members)
        removed_uuids.difference_update(entry.user_uuid for entry in proposal.reviewers if entry.user_uuid)
        removed_logins.difference_update(
            entry.github_login.lower() for entry in proposal.reviewers if entry.github_login
        )
        return AssignmentEdit(
            selection=AssignmentSelection(people=tuple(people), suggestions=tuple(suggestions)),
            overrides=AssignmentOverrides(
                additions=tuple(added.values()),
                removed_user_uuids=tuple(sorted(removed_uuids)),
                removed_github_logins=tuple(sorted(removed_logins)),
                unassigned=not proposal.reviewers if proposal.action == "replace" else snapshot.overrides.unassigned,
            ),
        )

    @staticmethod
    def _apply_overrides(selection: AssignmentSelection, overrides: AssignmentOverrides) -> AssignmentSelection:
        if overrides.unassigned:
            return AssignmentSelection()

        def allowed(entry: SuggestedReviewerEntry) -> bool:
            return entry.user_uuid not in overrides.removed_user_uuids and (
                not entry.github_login or entry.github_login.lower() not in overrides.removed_github_logins
            )

        people = {_identity(entry): entry for entry in selection.people if allowed(entry)}
        people.update({_identity(entry): entry for entry in overrides.additions})
        suggestions = tuple(
            entry for entry in selection.suggestions if allowed(entry) and _identity(entry) not in people
        )
        return selection.model_copy(
            update={
                "people": tuple(people.values()),
                "suggestions": suggestions,
                "pr_owner": None if str(selection.pr_owner) in overrides.removed_user_uuids else selection.pr_owner,
                "pr_reviewers": tuple(
                    member for member in selection.pr_reviewers if str(member) not in overrides.removed_user_uuids
                ),
            }
        )

    def _validate_members(self, selection: AssignmentSelection, snapshot: AssignmentSnapshot) -> EligibleAssignment:
        if selection.teams:
            raise AssignmentWriteError(
                "Team assignment needs a verified team provider. Select project members instead."
            )
        wanted = {person.user_uuid for person in selection.people}
        wanted.update(str(member) for member in selection.pr_reviewers)
        if selection.pr_owner:
            wanted.add(str(selection.pr_owner))
        eligible = {str(member.uuid) for member in self.team.all_users_with_access(user_uuids=wanted)}
        ineligible = wanted - eligible
        previous = {person.user_uuid for person in snapshot.selection.people}
        previous.update(str(member) for member in snapshot.selection.pr_reviewers)
        if snapshot.selection.pr_owner:
            previous.add(str(snapshot.selection.pr_owner))
        if ineligible - previous:
            raise AssignmentWriteError("An assignee no longer has project access. Refresh the member list.")
        logins = get_org_member_github_logins_by_user_uuid(
            self.team.id, [person.user_uuid for person in selection.people if person.user_uuid in eligible]
        )
        people: list[AssignedPerson] = []
        for person in selection.people:
            if person.user_uuid in eligible:
                people.append(person.model_copy(update={"github_login": logins.get(person.user_uuid)}))
        return EligibleAssignment(
            selection=selection.model_copy(
                update={
                    "people": tuple(people),
                    "pr_owner": selection.pr_owner if str(selection.pr_owner) in eligible else None,
                    "pr_reviewers": tuple(member for member in selection.pr_reviewers if str(member) in eligible),
                }
            ),
            ineligible_user_uuids=tuple(sorted(ineligible)),
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
        writer_enabled = (
            assignment_agent_selection_enabled(self.team.id)
            if proposal.action == "automatic"
            else assignment_human_writer_enabled(self.team.id)
        )
        side_effects_enabled = (
            assignment_side_effects_enabled(self.team.id)
            if proposal.action == "replace" or reevaluate_autostart
            else False
        )
        with transaction.atomic():
            report = (
                SignalReport.objects.select_for_update()
                .exclude(status=SignalReport.Status.DELETED)
                .get(team_id=self.team.id, id=self.report_id)
            )
            existing = (
                self._revisions()
                .select_related("artefact", "reviewers_artefact")
                .filter(operation_id=proposal.operation_id)
                .first()
            )
            if existing:
                if existing.request_hash != request_hash:
                    raise AssignmentOperationConflict("This operation ID belongs to a different assignment request.")
                return AssignmentWrite(
                    decision=AssignmentDecision.model_validate_json(existing.artefact.content),
                    reviewers_artefact=existing.reviewers_artefact,
                    replayed=True,
                )
            if claim_id:
                assignment = get_active_claim(team_id=self.team.id, report_id=self.report_id)
                if (
                    assignment is None
                    or str(assignment.claim_id) != claim_id
                    or not actor_owns_claim(assignment, actor)
                ):
                    raise AssignmentClaimConflict("Claim is stale or belongs to another actor.")
            snapshot = self._snapshot(report)
            if (
                proposal.expected_revision != snapshot.revision
                or proposal.evidence_revision != snapshot.evidence_revision
            ):
                raise StaleAssignmentProposal(
                    "The report or assignment changed. Read it again before applying this proposal."
                )
            if not writer_enabled:
                raise AssignmentWriteError("Assignment writes are disabled.")
            if proposal.action != "automatic" and actor.kind != "user":
                raise AssignmentWriteError("Only a person can change assignment overrides.")

            overrides = snapshot.overrides
            if proposal.action in {"replace", "remove"}:
                edit = self._human_edit(snapshot, proposal)
                selection = edit.selection
                overrides = edit.overrides
            elif proposal.action == "resume":
                selection, overrides = snapshot.selection, AssignmentOverrides()
            else:
                selection = snapshot.selection if proposal.outcome == "lookup_failed" else proposal.selection
                selection = self._apply_overrides(selection, overrides)
            validated = self._validate_members(selection, snapshot)
            selection = validated.selection
            ineligible = validated.ineligible_user_uuids
            overrides = overrides.model_copy(
                update={
                    "additions": tuple(person for person in overrides.additions if person.user_uuid not in ineligible)
                }
            )
            if proposal.action in {"replace", "remove"}:
                assigned = {person.user_uuid: person for person in selection.people}
                reviewers = tuple(
                    assigned.get(entry.user_uuid, entry) if entry.user_uuid else entry
                    for entry in proposal.reviewers
                    if entry.user_uuid not in ineligible
                )
            else:
                reviewers = (*selection.people, *selection.suggestions)
            decision = AssignmentDecision(
                operation_id=proposal.operation_id,
                revision=snapshot.revision + 1,
                based_on_revision=snapshot.revision,
                evidence_revision=snapshot.evidence_revision,
                source=proposal.source,
                policy_version=proposal.policy_version,
                outcome=proposal.outcome,
                selection=selection,
                overrides=overrides,
                retry_reason=proposal.retry_reason,
                ineligible_user_uuids=ineligible,
                requires_reassessment=bool(ineligible) or proposal.outcome == "lookup_failed",
            )
            artefact = SignalReportArtefact.add_log(
                team_id=self.team.id,
                report_id=self.report_id,
                content=decision,
                attribution=actor,
                claim_id=claim_id,
            )
            compatibility = SignalReportArtefact.append_status(
                team_id=self.team.id,
                report_id=self.report_id,
                content=SuggestedReviewers(root=list(reviewers)),
                attribution=actor,
                claim_id=claim_id,
                reevaluate_autostart=(proposal.action == "replace" or reevaluate_autostart) and side_effects_enabled,
                assignment_writer=True,
            )
            SignalReportAssignmentRevision.objects.for_team(self.team.id).create(
                team_id=self.team.id,
                report=report,
                revision=decision.revision,
                operation_id=proposal.operation_id,
                request_hash=request_hash,
                artefact=artefact,
                reviewers_artefact=compatibility,
            )
            return AssignmentWrite(decision=decision, reviewers_artefact=compatibility, replayed=False)

    def apply_compatibility_reviewers(
        self,
        reviewers: SuggestedReviewers,
        *,
        actor: ArtefactAttribution,
        claim_id: str | None = None,
        source: str = "artefact_api",
    ) -> SignalReportArtefact:
        """Apply an existing reviewer API payload as an automatic assignment proposal."""
        snapshot = self.read()
        selection = AssignmentSelection(
            people=tuple(
                AssignedPerson.model_validate(entry.model_dump())
                for entry in reviewers.root
                if entry.user_uuid is not None
            ),
            suggestions=tuple(entry for entry in reviewers.root if entry.user_uuid is None),
        )
        return self.apply(
            AssignmentProposal(
                operation_id=uuid4(),
                expected_revision=snapshot.revision,
                evidence_revision=snapshot.evidence_revision,
                source=source,
                policy_version="1",
                selection=selection,
            ),
            actor=actor,
            reevaluate_autostart=True,
            claim_id=claim_id,
        ).reviewers_artefact

    def edit_reviewers(
        self,
        reviewers: SuggestedReviewers,
        *,
        actor: ArtefactAttribution,
        removal: bool = False,
    ) -> SignalReportArtefact:
        if actor.kind != "user":
            raise AssignmentWriteError("Only a person can change assignment overrides.")
        human_writer_enabled = assignment_human_writer_enabled(self.team.id)
        if human_writer_enabled:
            snapshot = self.read()
            return self.apply(
                AssignmentProposal(
                    operation_id=uuid4(),
                    expected_revision=snapshot.revision,
                    evidence_revision=snapshot.evidence_revision,
                    source="reviewer_api",
                    policy_version="1",
                    action="remove" if removal else "replace",
                    reviewers=tuple(reviewers.root),
                ),
                actor=actor,
            ).reviewers_artefact

        with transaction.atomic():
            (
                SignalReport.objects.select_for_update()
                .exclude(status=SignalReport.Status.DELETED)
                .get(team_id=self.team.id, id=self.report_id)
            )
            if self._revisions().exists():
                raise AssignmentWriteError("Reviewer edits are paused for this report during assignment testing.")
            return SignalReportArtefact.append_status(
                team_id=self.team.id,
                report_id=self.report_id,
                content=reviewers,
                attribution=actor,
                reevaluate_autostart=not removal,
            )
