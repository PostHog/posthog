from __future__ import annotations

import json
from uuid import UUID

from django.db.models import Q

from posthog.dataclasses import frozen
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.team.team import Team

from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.artefact_schemas import (
    ReviewerCorrections,
    ReviewerEdit,
    ReviewerProposal,
    ReviewerState,
    SuggestedReviewerEntry,
    SuggestedReviewers,
)
from products.signals.backend.assignment_flags import assignment_side_effects_enabled, assignment_writer_enabled
from products.signals.backend.models import SignalReport, SignalReportArtefact
from products.signals.backend.report_generation.resolve_reviewers import (
    bounded_reviewer_reason,
    get_org_member_github_logins_by_user_uuid,
    resolve_org_github_login_to_users,
)


class ReviewerWriteError(ValueError):
    pass


class StaleReviewerProposal(ReviewerWriteError):
    pass


@frozen
class ReviewerSnapshot:
    state: ReviewerState
    reviewers: tuple[SuggestedReviewerEntry, ...]
    corrections: ReviewerCorrections
    invalid_reviewers: bool = False


@frozen
class ReviewerUpdate:
    protected: bool
    reviewers: SuggestedReviewers
    corrections: ReviewerCorrections | None
    current: SignalReportArtefact | None


@frozen
class EligibleReviewers:
    reviewers: tuple[SuggestedReviewerEntry, ...]
    ineligible_user_uuids: tuple[str, ...]
    unresolved_candidates: tuple[SuggestedReviewerEntry, ...]


def same_reviewer(left: SuggestedReviewerEntry, right: SuggestedReviewerEntry) -> bool:
    if left.user_uuid and right.user_uuid:
        return left.user_uuid == right.user_uuid
    return bool(left.github_login and right.github_login and left.github_login.lower() == right.github_login.lower())


def contains_reviewer(entries: tuple[SuggestedReviewerEntry, ...], reviewer: SuggestedReviewerEntry) -> bool:
    return any(same_reviewer(entry, reviewer) for entry in entries)


def correct_reviewers(
    corrections: ReviewerCorrections,
    added: tuple[SuggestedReviewerEntry, ...],
    removed: tuple[SuggestedReviewerEntry, ...],
) -> ReviewerCorrections:
    return corrections.model_copy(
        update={
            "pinned": tuple(entry for entry in corrections.pinned if not contains_reviewer(removed + added, entry))
            + added,
            "excluded": tuple(entry for entry in corrections.excluded if not contains_reviewer(added + removed, entry))
            + removed,
        }
    )


class ReviewerRules:
    def __init__(self, *, team: Team, report_id: str) -> None:
        self.team = team
        self.report_id = report_id
        self.enabled = assignment_writer_enabled(team.id)
        self.effects_enabled = assignment_side_effects_enabled(team.id)

    @staticmethod
    def _read_reviewers(artefact: SignalReportArtefact | None) -> tuple[SuggestedReviewerEntry, ...]:
        if artefact is None:
            return ()
        content = json.loads(artefact.content)
        if isinstance(content, list):
            for entry in content:
                if isinstance(entry, dict):
                    entry["reason"] = bounded_reviewer_reason(entry.get("reason"))
                    if not isinstance(entry.get("relevant_commits"), list):
                        entry["relevant_commits"] = []
                    for commit in entry["relevant_commits"]:
                        if isinstance(commit, dict):
                            commit["reason"] = bounded_reviewer_reason(commit.get("reason")) or ""
        return tuple(SuggestedReviewers.model_validate(content).root)

    @staticmethod
    def _label(entry: SuggestedReviewerEntry) -> str:
        return entry.github_login.lower() if entry.github_login else entry.user_uuid or ""

    @staticmethod
    def _resolve_identities(
        team_id: int, reviewers: tuple[SuggestedReviewerEntry, ...]
    ) -> tuple[SuggestedReviewerEntry, ...]:
        unresolved_logins = {
            entry.github_login.lower() for entry in reviewers if entry.github_login and not entry.user_uuid
        }
        members = resolve_org_github_login_to_users(team_id, unresolved_logins) if unresolved_logins else {}
        return tuple(
            entry.model_copy(update={"user_uuid": str(member.uuid)})
            if entry.github_login and not entry.user_uuid and (member := members.get(entry.github_login.lower()))
            else entry
            for entry in reviewers
        )

    @classmethod
    def _legacy_corrections(cls, *, team_id: int, report_id: str) -> ReviewerCorrections:
        rows = list(
            SignalReportArtefact.objects.filter(
                team_id=team_id, report_id=report_id, type="suggested_reviewers"
            ).order_by("created_at", "id")
        )
        try:
            history = {row.id: cls._read_reviewers(row) for row in rows}
        except ValueError:
            return ReviewerCorrections(needs_review=True)
        unresolved_logins = {
            entry.github_login.lower()
            for reviewers in history.values()
            for entry in reviewers
            if entry.github_login and not entry.user_uuid
        }
        members = resolve_org_github_login_to_users(team_id, unresolved_logins) if unresolved_logins else {}

        def resolve(entries: tuple[SuggestedReviewerEntry, ...]) -> tuple[SuggestedReviewerEntry, ...]:
            return tuple(
                entry.model_copy(update={"user_uuid": str(member.uuid)})
                if entry.github_login and not entry.user_uuid and (member := members.get(entry.github_login.lower()))
                else entry
                for entry in entries
            )

        changes = [
            (log.user_id, change)
            for log in ActivityLog.objects.filter(
                team_id=team_id, scope="SignalReport", item_id=report_id, activity="suggested_reviewers_changed"
            ).order_by("created_at", "id")
            for change in (log.detail or {}).get("changes", [])
            if change.get("field") == "suggested_reviewers"
        ]
        corrections = ReviewerCorrections()
        previous: tuple[SuggestedReviewerEntry, ...] = ()
        for row in rows:
            current = history[row.id]
            if row.actor_kind == "user" or (row.actor_kind is None and row.created_by_id is not None):
                added = tuple(entry for entry in current if not contains_reviewer(previous, entry))
                removed = tuple(entry for entry in previous if not contains_reviewer(current, entry))
                if added or removed:
                    before, after = {cls._label(entry) for entry in previous}, {cls._label(entry) for entry in current}
                    match = next(
                        (
                            i
                            for i, (user_id, change) in enumerate(changes)
                            if user_id == row.created_by_id
                            and set(change.get("before") or []) == before
                            and set(change.get("after") or []) == after
                        ),
                        None,
                    )
                    if match is None:
                        return corrections.model_copy(update={"needs_review": True})
                    changes.pop(match)
                    corrections = correct_reviewers(corrections, resolve(added), resolve(removed))
            previous = current
        return corrections.model_copy(
            update={
                "needs_review": bool(changes)
                or any(not entry.user_uuid for entry in corrections.pinned + corrections.excluded)
            }
        )

    @classmethod
    def read_for_report(cls, *, team_id: int, report_id: str) -> ReviewerSnapshot:
        SignalReport.objects.get(team_id=team_id, id=report_id)
        rows = SignalReportArtefact.objects.filter(team_id=team_id, report_id=report_id)
        reviewers = rows.filter(type="suggested_reviewers").order_by("-created_at", "-id").first()
        corrections = rows.filter(type="reviewer_corrections").order_by("-created_at", "-id").first()
        invalid_reviewers = False
        try:
            entries = cls._read_reviewers(reviewers)
        except ValueError:
            entries = ()
            invalid_reviewers = True
        rules = (
            ReviewerCorrections.model_validate_json(corrections.content)
            if corrections
            else ReviewerCorrections(
                # Until the first protected write recovers old edits, readers must not treat them as absent.
                needs_review=rows.filter(type="suggested_reviewers")
                .filter(Q(actor_kind="user") | Q(actor_kind__isnull=True, created_by__isnull=False))
                .exists()
            )
        )
        if invalid_reviewers:
            rules = rules.model_copy(update={"needs_review": True})
        return ReviewerSnapshot(
            state=ReviewerState(
                reviewers_id=reviewers.id if reviewers else None, corrections_id=corrections.id if corrections else None
            ),
            reviewers=entries,
            corrections=rules,
            invalid_reviewers=invalid_reviewers,
        )

    def read(self) -> ReviewerSnapshot:
        return self.read_for_report(team_id=self.team.id, report_id=self.report_id)

    def _validate_members(self, reviewers: tuple[SuggestedReviewerEntry, ...]) -> EligibleReviewers:
        resolved: list[SuggestedReviewerEntry] = []
        unresolved: list[SuggestedReviewerEntry] = []
        for entry in self._resolve_identities(self.team.id, reviewers):
            if entry.user_uuid:
                try:
                    UUID(entry.user_uuid)
                except ValueError as error:
                    raise ReviewerWriteError("A reviewer must have a valid user UUID.") from error
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

    def prepare(
        self,
        content: SuggestedReviewers,
        *,
        attribution: ArtefactAttribution,
        proposal: ReviewerProposal | None,
        edit: ReviewerEdit | None,
    ) -> ReviewerUpdate:
        """Called by append_status while it holds the report lock."""
        snapshot = self.read()
        if edit is not None and attribution.kind != "user":
            raise ReviewerWriteError("Only a person can change reviewer corrections.")
        repairing = snapshot.invalid_reviewers
        if repairing and (edit is None or edit.action != "replace"):
            raise ReviewerWriteError(
                "Stored reviewer data is invalid. A person must replace the list with current state."
            )
        current = (
            SignalReportArtefact.objects.get(
                team_id=self.team.id, report_id=self.report_id, id=snapshot.state.reviewers_id
            )
            if snapshot.state.reviewers_id
            else None
        )
        enrolled = snapshot.state.corrections_id is not None
        corrections = snapshot.corrections
        protected = self.enabled or enrolled or repairing
        proposed = tuple(content.root)
        members_validated = False
        expected = edit.expected_state if edit else proposal.expected_state if proposal else None
        if protected:
            if edit is None and not self.enabled:
                proposed = snapshot.reviewers
            elif expected != snapshot.state and (edit is None or edit.action in {"replace", "confirm"}):
                raise StaleReviewerProposal("Reviewers or corrections changed. Read the report again before saving.")
            if not enrolled and corrections.needs_review:
                corrections = self._legacy_corrections(team_id=self.team.id, report_id=self.report_id)
        if edit is not None:
            if edit.action == "confirm":
                if not protected:
                    raise ReviewerWriteError("List confirmation is not enabled for this report.")
                corrections = corrections.model_copy(update={"confirmed": True, "needs_review": False})
                proposed = snapshot.reviewers
            else:
                additions = (
                    proposed
                    if edit.action == "add"
                    else tuple(entry for entry in proposed if not contains_reviewer(snapshot.reviewers, entry))
                    if edit.action == "replace"
                    else ()
                )
                removals = (
                    proposed
                    if edit.action == "remove"
                    else tuple(entry for entry in snapshot.reviewers if not contains_reviewer(proposed, entry))
                    if edit.action == "replace"
                    else ()
                )
                if protected:
                    removals = self._resolve_identities(self.team.id, removals)
                checked = self._validate_members(additions)
                if protected and (checked.ineligible_user_uuids or checked.unresolved_candidates):
                    raise ReviewerWriteError("New reviewers must be active members with access to this project.")
                additions = checked.reviewers if protected else additions
                if protected and not repairing:
                    corrections = correct_reviewers(corrections, additions, removals)
                if repairing:
                    proposed = additions
                    members_validated = True
                elif edit.action == "add":
                    proposed = snapshot.reviewers + tuple(
                        entry for entry in additions if not contains_reviewer(snapshot.reviewers, entry)
                    )
                elif edit.action == "remove":
                    proposed = tuple(entry for entry in snapshot.reviewers if not contains_reviewer(removals, entry))
        elif protected and self.enabled:
            if proposal and proposal.outcome != "selected" and proposed:
                raise ReviewerWriteError("An unsuccessful selection cannot supply reviewers.")
            failed = proposal is not None and proposal.outcome == "lookup_failed"
            if corrections.confirmed or corrections.needs_review or failed:
                proposed = snapshot.reviewers
            else:
                validated = self._validate_members(proposed)
                if proposed and not validated.reviewers:
                    proposed = snapshot.reviewers
                else:
                    proposed = tuple(
                        entry for entry in validated.reviewers if not contains_reviewer(corrections.excluded, entry)
                    )
                    extra_pins = tuple(
                        entry
                        for entry in corrections.pinned
                        if not contains_reviewer(validated.reviewers, entry)
                        and entry.user_uuid not in validated.ineligible_user_uuids
                        and not contains_reviewer(validated.unresolved_candidates, entry)
                    )
                    proposed += self._validate_members(extra_pins).reviewers if extra_pins else ()
                    members_validated = True
        elif (
            proposal
            and proposal.source == "research"
            and (corrections.pinned or corrections.excluded or corrections.needs_review)
        ):
            proposed = snapshot.reviewers
        if protected and not members_validated:
            proposed = self._validate_members(proposed).reviewers
        reviewers = SuggestedReviewers(root=list(proposed))
        if current is not None and edit is None and proposal is not None and proposal.source == "research":
            # Research can rephrase its evidence without changing the selection.
            comparison_exclusions = {
                "__all__": {"reason": True, "github_name": True, "relevant_commits": {"__all__": {"reason"}}}
            }
            previous = SuggestedReviewers(root=list(snapshot.reviewers))
            if previous.model_dump(exclude=comparison_exclusions) == reviewers.model_dump(
                exclude=comparison_exclusions
            ):
                reviewers = previous
        return ReviewerUpdate(
            protected=protected,
            reviewers=reviewers,
            corrections=corrections
            if protected and (repairing or not enrolled or corrections != snapshot.corrections)
            else None,
            current=current,
        )
