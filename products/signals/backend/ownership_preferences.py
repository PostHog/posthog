from __future__ import annotations

from functools import partial
from uuid import UUID

from django.db import transaction
from django.db.models import F

from pydantic import ValidationError

from posthog.exceptions import Conflict
from posthog.models import User

from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.artefact_schemas import SuggestedReviewerEntry, SuggestedReviewers
from products.signals.backend.models import (
    SignalDomainPreference,
    SignalProductDomain,
    SignalReport,
    SignalReportArtefact,
    SignalReportRouting,
    SignalRoutingBatch,
    SignalRoutingBatchChange,
)
from products.signals.backend.ownership import ReviewerRoutingPolicy
from products.signals.backend.ownership_telemetry import capture_routing_change
from products.signals.backend.report_claims import get_active_claim, responsible_user

BATCH_SIZE = 100


def _schedule_batch(*, team_id: int, batch_id: str) -> None:
    # Celery's task registry imports this service through tasks.py.
    from products.signals.backend.tasks import apply_signal_routing_batch

    transaction.on_commit(partial(apply_signal_routing_batch.delay, team_id=team_id, batch_id=batch_id))


class DomainPreferenceService:
    def __init__(self, *, team_id: int, user: User) -> None:
        self.team_id = team_id
        self.user = user

    def preview(self, *, domain_id: UUID | str) -> SignalRoutingBatch:
        domain = SignalProductDomain.objects.for_team(self.team_id).get(id=domain_id, archived=False)
        preference, _ = SignalDomainPreference.objects.for_team(self.team_id).get_or_create(
            team_id=self.team_id, user=self.user, domain=domain, defaults={"excluded": False}
        )
        batch = SignalRoutingBatch.objects.for_team(self.team_id).create(
            team_id=self.team_id,
            preference=preference,
            preference_revision=preference.revision,
            domain_revision=domain.revision,
            previous_excluded=preference.excluded,
            status=SignalRoutingBatch.Status.PREPARING,
        )
        latest_rows = (
            SignalReportArtefact.objects.filter(
                team_id=self.team_id,
                report__routing__domain=domain,
                report__routing__accepted=True,
                type=SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS,
            )
            .exclude(report__status=SignalReport.Status.DELETED)
            .order_by("report_id", "-created_at", "-id")
            .distinct("report_id")
        )
        login = (self.user.get_github_login() or "").lower()
        changes: list[SignalRoutingBatchChange] = []
        try:
            for row in latest_rows.iterator(chunk_size=BATCH_SIZE):
                try:
                    entries = SuggestedReviewers.model_validate_json(row.content).root
                except ValidationError:
                    continue
                entry = next(
                    (
                        entry
                        for entry in entries
                        if entry.user_uuid == str(self.user.uuid)
                        or (not entry.user_uuid and login and (entry.github_login or "").lower() == login)
                    ),
                    None,
                )
                if entry is None:
                    continue
                changes.append(
                    SignalRoutingBatchChange(
                        team_id=self.team_id,
                        batch=batch,
                        report_id=row.report_id,
                        reviewer=entry.model_dump(mode="json"),
                        expected_artefact_id=row.id,
                    )
                )
                if len(changes) == BATCH_SIZE:
                    SignalRoutingBatchChange.objects.for_team(self.team_id).bulk_create(changes)
                    changes.clear()
            if changes:
                SignalRoutingBatchChange.objects.for_team(self.team_id).bulk_create(changes)
        except Exception:
            batch.status = SignalRoutingBatch.Status.FAILED
            batch.error = "preview_failed"
            batch.save(update_fields=["status", "error", "updated_at"])
            raise
        batch.total = SignalRoutingBatchChange.objects.for_team(self.team_id).filter(batch=batch).count()
        batch.status = SignalRoutingBatch.Status.PREVIEW
        batch.save(update_fields=["status", "total", "updated_at"])
        return batch

    def set_excluded(self, *, domain_id: UUID | str, excluded: bool) -> SignalDomainPreference:
        with transaction.atomic():
            domain = SignalProductDomain.objects.for_team(self.team_id).select_for_update().get(id=domain_id)
            preference, _ = SignalDomainPreference.objects.for_team(self.team_id).get_or_create(
                team_id=self.team_id, user=self.user, domain=domain, defaults={"excluded": False}
            )
            if preference.excluded != excluded:
                preference.excluded = excluded
                preference.github_login = (self.user.get_github_login() or "").lower()
                preference.revision += 1
                preference.save(update_fields=["excluded", "github_login", "revision", "updated_at"])
            return preference

    def apply(self, *, batch_id: UUID | str) -> SignalRoutingBatch:
        batch = (
            SignalRoutingBatch.objects.for_team(self.team_id)
            .select_related("preference")
            .get(id=batch_id, preference__user=self.user)
        )
        with transaction.atomic():
            domain = (
                SignalProductDomain.objects.for_team(self.team_id)
                .select_for_update()
                .get(id=batch.preference.domain_id)
            )
            batch = SignalRoutingBatch.objects.for_team(self.team_id).select_for_update().get(id=batch.id)
            if batch.status in (
                SignalRoutingBatch.Status.PENDING,
                SignalRoutingBatch.Status.RUNNING,
                SignalRoutingBatch.Status.COMPLETE,
            ):
                return batch
            preference = SignalDomainPreference.objects.for_team(self.team_id).get(id=batch.preference_id)
            if (
                batch.status != SignalRoutingBatch.Status.PREVIEW
                or preference.revision != batch.preference_revision
                or domain.revision != batch.domain_revision
                or domain.archived
            ):
                raise Conflict("Routing changed since the preview. Preview the reports again.")
            preference.excluded = True
            preference.github_login = (self.user.get_github_login() or "").lower()
            preference.revision += 1
            preference.save(update_fields=["excluded", "github_login", "revision", "updated_at"])
            batch.preference_revision = preference.revision
            batch.status = SignalRoutingBatch.Status.PENDING
            batch.save(update_fields=["preference_revision", "status", "updated_at"])
            _schedule_batch(team_id=self.team_id, batch_id=str(batch.id))
            return batch

    def undo(self, *, batch_id: UUID | str) -> SignalRoutingBatch:
        batch = (
            SignalRoutingBatch.objects.for_team(self.team_id)
            .select_related("preference")
            .get(id=batch_id, preference__user=self.user)
        )
        with transaction.atomic():
            SignalProductDomain.objects.for_team(self.team_id).select_for_update().get(id=batch.preference.domain_id)
            batch = SignalRoutingBatch.objects.for_team(self.team_id).select_for_update().get(id=batch.id)
            if batch.status in (SignalRoutingBatch.Status.UNDOING, SignalRoutingBatch.Status.UNDONE):
                return batch
            preference = SignalDomainPreference.objects.for_team(self.team_id).get(id=batch.preference_id)
            if (
                batch.status
                not in (
                    SignalRoutingBatch.Status.PENDING,
                    SignalRoutingBatch.Status.RUNNING,
                    SignalRoutingBatch.Status.COMPLETE,
                    SignalRoutingBatch.Status.FAILED,
                )
                or preference.revision != batch.preference_revision
            ):
                raise Conflict("Your routing rule changed after this operation. Preview a new change instead.")
            preference.excluded = batch.previous_excluded
            preference.revision += 1
            preference.save(update_fields=["excluded", "revision", "updated_at"])
            batch.preference_revision = preference.revision
            batch.status = SignalRoutingBatch.Status.UNDOING
            batch.undo_requested = True
            batch.save(update_fields=["preference_revision", "status", "undo_requested", "updated_at"])
            batch.changes.filter(status=SignalRoutingBatchChange.Status.PENDING).update(
                status=SignalRoutingBatchChange.Status.CANCELLED, undone=True
            )
            _schedule_batch(team_id=self.team_id, batch_id=str(batch.id))
            return batch

    def retry(self, *, batch_id: UUID | str) -> SignalRoutingBatch:
        batch = (
            SignalRoutingBatch.objects.for_team(self.team_id)
            .select_related("preference")
            .get(id=batch_id, preference__user=self.user)
        )
        if batch.status != SignalRoutingBatch.Status.FAILED or batch.error != "cleanup_failed":
            raise Conflict("This operation cannot be retried. Preview a new change instead.")
        with transaction.atomic():
            SignalProductDomain.objects.for_team(self.team_id).select_for_update().get(id=batch.preference.domain_id)
            batch = SignalRoutingBatch.objects.for_team(self.team_id).select_for_update().get(id=batch.id)
            preference = SignalDomainPreference.objects.for_team(self.team_id).get(id=batch.preference_id)
            if preference.revision != batch.preference_revision:
                raise Conflict("Your routing rule changed. Preview a new change instead.")
            batch.status = (
                SignalRoutingBatch.Status.UNDOING if batch.undo_requested else SignalRoutingBatch.Status.PENDING
            )
            batch.error = ""
            batch.save(update_fields=["status", "error", "updated_at"])
            _schedule_batch(team_id=self.team_id, batch_id=str(batch.id))
            return batch


class RoutingBatchProcessor:
    def __init__(self, *, team_id: int, batch_id: UUID | str) -> None:
        self.team_id = team_id
        self.batch_id = batch_id

    def _process_change(self, change_id: UUID, *, undo: bool) -> None:
        change = SignalRoutingBatchChange.objects.for_team(self.team_id).get(id=change_id, batch_id=self.batch_id)
        batch = SignalRoutingBatch.objects.for_team(self.team_id).select_related("preference").get(id=self.batch_id)
        with transaction.atomic():
            report = SignalReport.objects.select_for_update().get(team_id=self.team_id, id=change.report_id)
            routing_domain = (
                SignalReportRouting.objects.for_team(self.team_id)
                .filter(report=report, accepted=True)
                .values_list("domain_id", flat=True)
                .first()
            )
            domains = {
                domain.id: domain
                for domain in SignalProductDomain.objects.for_team(self.team_id)
                .filter(id__in=[batch.preference.domain_id, routing_domain])
                .order_by("id")
                .select_for_update()
            }
            domain = domains[batch.preference.domain_id]
            batch = SignalRoutingBatch.objects.for_team(self.team_id).select_for_update().get(id=batch.id)
            change = SignalRoutingBatchChange.objects.for_team(self.team_id).select_for_update().get(id=change.id)
            preference = (
                SignalDomainPreference.objects.for_team(self.team_id).select_related("user").get(id=batch.preference_id)
            )
            expected_statuses = (
                (SignalRoutingBatch.Status.UNDOING,)
                if undo
                else (SignalRoutingBatch.Status.PENDING, SignalRoutingBatch.Status.RUNNING)
            )
            expected_change = (
                SignalRoutingBatchChange.Status.REMOVED if undo else SignalRoutingBatchChange.Status.PENDING
            )
            if batch.status not in expected_statuses or change.status != expected_change:
                return
            if preference.revision != batch.preference_revision or preference.excluded != (
                batch.previous_excluded if undo else True
            ):
                batch.status = SignalRoutingBatch.Status.CANCELLED
                batch.save(update_fields=["status", "updated_at"])
                return
            latest = (
                SignalReportArtefact.objects.filter(
                    team_id=self.team_id, report=report, type=SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS
                )
                .order_by("-created_at", "-id")
                .first()
            )
            expected_id = change.removal_artefact_id if undo else change.expected_artefact_id
            status = SignalRoutingBatchChange.Status.CHANGED
            if latest and latest.id == expected_id and report.status != SignalReport.Status.DELETED:
                content = SuggestedReviewers.model_validate_json(latest.content)
                if undo:
                    policy = ReviewerRoutingPolicy(team_id=self.team_id, report_id=report.id)
                    restored = SuggestedReviewerEntry.model_validate(change.reviewer)
                    if policy.filter(SuggestedReviewers(root=[restored])).root:
                        content.root.append(restored)
                        SignalReportArtefact.append_status(
                            team_id=self.team_id,
                            report_id=str(report.id),
                            content=content,
                            attribution=ArtefactAttribution.from_user(preference.user_id),
                            reevaluate_autostart=False,
                        )
                        status = SignalRoutingBatchChange.Status.RESTORED
                else:
                    claim = get_active_claim(team_id=self.team_id, report_id=report.id)
                    claimant = responsible_user(claim) if claim else None
                    if claimant and claimant.id == preference.user_id:
                        status = SignalRoutingBatchChange.Status.CLAIMED
                    elif (
                        domain.revision == batch.domain_revision
                        and SignalReportRouting.objects.for_team(self.team_id)
                        .filter(report=report, domain_id=domain.id, accepted=True)
                        .exists()
                    ):
                        removed = SignalReportArtefact.append_status(
                            team_id=self.team_id,
                            report_id=str(report.id),
                            content=content,
                            attribution=ArtefactAttribution.from_user(preference.user_id),
                            reevaluate_autostart=False,
                        )
                        change.removal_artefact_id = removed.id
                        status = SignalRoutingBatchChange.Status.REMOVED
            change.status = status
            change.undone = undo
            change.save(update_fields=["status", "removal_artefact_id", "undone"])
            counter = (
                "changed"
                if status == SignalRoutingBatchChange.Status.REMOVED
                else "skipped_claims"
                if status == SignalRoutingBatchChange.Status.CLAIMED
                else "skipped_changes"
                if status == SignalRoutingBatchChange.Status.CHANGED
                else None
            )
            if counter:
                SignalRoutingBatch.objects.for_team(self.team_id).filter(id=batch.id).update(
                    **{counter: F(counter) + 1}
                )

    def run(self) -> bool:
        batch = SignalRoutingBatch.objects.for_team(self.team_id).get(id=self.batch_id)
        undo = batch.status == SignalRoutingBatch.Status.UNDOING
        if batch.status not in (
            SignalRoutingBatch.Status.PENDING,
            SignalRoutingBatch.Status.RUNNING,
            SignalRoutingBatch.Status.UNDOING,
        ):
            return False
        change_status = SignalRoutingBatchChange.Status.REMOVED if undo else SignalRoutingBatchChange.Status.PENDING
        changes = SignalRoutingBatchChange.objects.for_team(self.team_id).filter(batch=batch, status=change_status)
        for change_id in list(changes.order_by("id").values_list("id", flat=True)[:BATCH_SIZE]):
            self._process_change(change_id, undo=undo)
        batch.refresh_from_db()
        expected_statuses = (
            (SignalRoutingBatch.Status.UNDOING,)
            if undo
            else (SignalRoutingBatch.Status.PENDING, SignalRoutingBatch.Status.RUNNING)
        )
        if batch.status not in expected_statuses:
            return False
        if changes.exists():
            return True
        completed = (
            SignalRoutingBatch.objects.for_team(self.team_id)
            .filter(id=batch.id, status=batch.status)
            .update(status=SignalRoutingBatch.Status.UNDONE if undo else SignalRoutingBatch.Status.COMPLETE)
        )
        if completed:
            capture_routing_change(
                team_id=self.team_id,
                action="undo" if undo else "cleanup",
                outcome="complete",
                changed=batch.changed,
                skipped=batch.skipped_claims + batch.skipped_changes,
            )
        return False
