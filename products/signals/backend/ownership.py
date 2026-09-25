from __future__ import annotations

from functools import partial
from uuid import UUID

from django.db import transaction
from django.db.models import Q

from pydantic import ValidationError

from posthog.models import Team, User
from posthog.models.activity_logging.activity_log import Change, Detail, log_activity

from products.access_control.backend.facade.api import get_routing_roles
from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.artefact_schemas import SuggestedReviewerEntry, SuggestedReviewers
from products.signals.backend.models import (
    SignalDomainPreference,
    SignalProductDomain,
    SignalReport,
    SignalReportArtefact,
    SignalReportRouting,
    SignalReviewerExclusion,
)
from products.signals.backend.report_generation.resolve_reviewers import (
    resolve_org_github_login_to_users,
    resolve_org_users_by_uuid,
)


class ReviewerRoutingPolicy:
    def __init__(self, *, team_id: int, report_id: str | UUID) -> None:
        self.team_id = team_id
        self.report_id = report_id

    def excluded_users(self) -> set[int]:
        excluded = set(
            SignalReviewerExclusion.objects.for_team(self.team_id)
            .filter(report_id=self.report_id)
            .values_list("user_id", flat=True)
        )
        domain_id = (
            SignalReportRouting.objects.for_team(self.team_id)
            .filter(report_id=self.report_id, accepted=True)
            .values_list("domain_id", flat=True)
            .first()
        )
        if domain_id:
            excluded.update(
                SignalDomainPreference.objects.for_team(self.team_id)
                .filter(domain_id=domain_id, excluded=True)
                .values_list("user_id", flat=True)
            )
        return excluded

    def owner_members(self) -> frozenset[int] | None:
        role_id = (
            SignalReportRouting.objects.for_team(self.team_id)
            .filter(report_id=self.report_id)
            .values_list("owning_role_id", flat=True)
            .first()
        )
        if role_id is None:
            return None
        return next(
            (role.member_user_ids for role in get_routing_roles(team_id=self.team_id) if role.id == role_id),
            frozenset(),
        )

    def allows_user(self, user_id: int) -> bool:
        members = self.owner_members()
        return user_id not in self.excluded_users() and (members is None or user_id in members)

    def excluded_logins(self) -> set[str]:
        logins = set(
            SignalReviewerExclusion.objects.for_team(self.team_id)
            .filter(report_id=self.report_id)
            .exclude(github_login="")
            .values_list("github_login", flat=True)
        )
        domain_id = (
            SignalReportRouting.objects.for_team(self.team_id)
            .filter(report_id=self.report_id, accepted=True)
            .values_list("domain_id", flat=True)
            .first()
        )
        if domain_id:
            logins.update(
                SignalDomainPreference.objects.for_team(self.team_id)
                .filter(domain_id=domain_id, excluded=True)
                .exclude(github_login="")
                .values_list("github_login", flat=True)
            )
        return {login.lower() for login in logins}

    def filter(self, content: SuggestedReviewers, *, automatic: bool = False) -> SuggestedReviewers:
        if not content.root:
            return content
        if automatic:
            routing = SignalReportRouting.objects.for_team(self.team_id).filter(report_id=self.report_id).first()
            if routing is not None and (not routing.accepted or routing.owning_role_id is None):
                return SuggestedReviewers(root=[])
        excluded = self.excluded_users()
        members = self.owner_members()
        if not excluded and members is None:
            return content
        excluded_uuids = {str(value) for value in User.objects.filter(id__in=excluded).values_list("uuid", flat=True)}
        logins = {entry.github_login.lower() for entry in content.root if entry.github_login}
        login_users = resolve_org_github_login_to_users(self.team_id, logins) if logins else {}
        # Keep the verified login at removal time so unlinking an integration cannot bypass a correction.
        removed_logins = self.excluded_logins()
        uuid_users = (
            resolve_org_users_by_uuid(self.team_id, [entry.user_uuid for entry in content.root if entry.user_uuid])
            if members is not None
            else {}
        )
        allowed: list[SuggestedReviewerEntry] = []
        for entry in content.root:
            login = (entry.github_login or "").lower()
            linked_user = login_users.get(login)
            if members is not None:
                candidate = uuid_users.get(entry.user_uuid) if entry.user_uuid else linked_user
                if candidate is None or candidate.id not in members:
                    continue
            if entry.user_uuid in excluded_uuids or (linked_user and linked_user.id in excluded):
                continue
            if not entry.user_uuid and login in removed_logins:
                continue
            allowed.append(entry)
        return SuggestedReviewers(root=allowed)

    def applies_to_report(self) -> bool:
        return (
            SignalReportRouting.objects.for_team(self.team_id).filter(report_id=self.report_id).exists()
            or SignalReviewerExclusion.objects.for_team(self.team_id).filter(report_id=self.report_id).exists()
        )

    def allows_delivery_to_email(self, email: str | None) -> bool:
        if not email:
            return False
        team = Team.objects.get(id=self.team_id)
        users = list(team.all_users_with_access().filter(email__iexact=email).values_list("id", flat=True)[:2])
        return len(users) == 1 and self.allows_user(users[0])

    def lock_domain(self) -> None:
        domain_id = (
            SignalReportRouting.objects.for_team(self.team_id)
            .filter(report_id=self.report_id, accepted=True)
            .values_list("domain_id", flat=True)
            .first()
        )
        if domain_id:
            # Preference writes lock this quiet row too; a rule cannot commit between check and append.
            SignalProductDomain.objects.for_team(self.team_id).select_for_update().get(id=domain_id)

    def record_self_correction(self, *, actor: User, was_suggested: bool, is_suggested: bool) -> None:
        login = (actor.get_github_login() or "").lower()
        exclusions = SignalReviewerExclusion.objects.for_team(self.team_id)
        if was_suggested and not is_suggested:
            exclusions.update_or_create(
                team_id=self.team_id,
                report_id=self.report_id,
                user_id=actor.id,
                defaults={"github_login": login},
            )
        elif is_suggested and not was_suggested:
            exclusions.filter(report_id=self.report_id, user_id=actor.id).delete()

    @staticmethod
    def excluded_reports_for(*, team_id: int, user: User) -> Q:
        report_ids = SignalReviewerExclusion.objects.for_team(team_id).filter(user_id=user.id).values("report_id")
        domain_ids = (
            SignalDomainPreference.objects.for_team(team_id).filter(user_id=user.id, excluded=True).values("domain_id")
        )
        nonmember_roles = [
            role.id for role in get_routing_roles(team_id=team_id) if user.id not in role.member_user_ids
        ]
        return (
            Q(id__in=report_ids)
            | Q(routing__accepted=True, routing__domain_id__in=domain_ids)
            | Q(routing__owning_role_id__in=nonmember_roles)
        )


def current_eligible_reviewers(*, team_id: int, report_id: str | UUID) -> SuggestedReviewers:
    latest = (
        SignalReportArtefact.objects.filter(
            team_id=team_id, report_id=report_id, type=SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS
        )
        .order_by("-created_at", "-id")
        .first()
    )
    if latest is None:
        return SuggestedReviewers(root=[])
    try:
        content = SuggestedReviewers.model_validate_json(latest.content)
    except ValidationError:
        return SuggestedReviewers(root=[])
    return ReviewerRoutingPolicy(team_id=team_id, report_id=report_id).filter(content)


def eligible_reviewer_users(*, team_id: int, report_id: str | UUID) -> list[User]:
    entries = current_eligible_reviewers(team_id=team_id, report_id=report_id).root
    uuids = [entry.user_uuid for entry in entries if entry.user_uuid]
    logins = {entry.github_login.lower() for entry in entries if entry.github_login and not entry.user_uuid}
    users = {
        user.id: user
        for user in [
            *(resolve_org_users_by_uuid(team_id, uuids).values() if uuids else []),
            *(resolve_org_github_login_to_users(team_id, logins).values() if logins else []),
        ]
    }
    return list(users.values())


def enforce_current_reviewers(*, team_id: int, report_id: str | UUID, attribution: ArtefactAttribution) -> None:
    with transaction.atomic():
        SignalReport.objects.select_for_update().get(team_id=team_id, id=report_id)
        policy = ReviewerRoutingPolicy(team_id=team_id, report_id=report_id)
        policy.lock_domain()
        latest = (
            SignalReportArtefact.objects.filter(
                team_id=team_id, report_id=report_id, type=SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS
            )
            .order_by("-created_at", "-id")
            .first()
        )
        if latest is None:
            return
        try:
            before = SuggestedReviewers.model_validate_json(latest.content)
        except ValidationError:
            before = None
        after = policy.filter(before) if before is not None else SuggestedReviewers(root=[])
        if before != after:
            SignalReportArtefact.append_status(
                team_id=team_id,
                report_id=str(report_id),
                content=after,
                attribution=attribution,
                reevaluate_autostart=False,
            )


def remove_my_suggestion(
    *, team: Team, report_id: str | UUID, user: User, scoped_team_ids: tuple[int, ...] | None
) -> SignalReportArtefact:
    # Scout note registration imports Celery tasks, which also import this policy.
    from products.signals.backend.reviewer_correction_notes import ReviewerCorrection, forward_reviewer_correction_note

    team_id = team.id
    with transaction.atomic():
        report = SignalReport.objects.select_for_update().get(team_id=team_id, id=report_id)
        before = current_eligible_reviewers(team_id=team_id, report_id=report_id)
        SignalReviewerExclusion.objects.for_team(team_id).update_or_create(
            team_id=team_id,
            report_id=report_id,
            user_id=user.id,
            defaults={"github_login": (user.get_github_login() or "").lower()},
        )
        artefact = SignalReportArtefact.append_status(
            team_id=team_id,
            report_id=str(report_id),
            content=current_eligible_reviewers(team_id=team_id, report_id=report_id),
            attribution=ArtefactAttribution.from_user(user.id),
        )
        after = SuggestedReviewers.model_validate_json(artefact.content)
        if before != after:
            log_activity(
                organization_id=None,
                team_id=team_id,
                user=user,
                was_impersonated=False,
                item_id=str(report_id),
                scope="SignalReport",
                activity="suggested_reviewers_changed",
                detail=Detail(
                    name=report.title,
                    changes=[
                        Change(
                            type="SignalReport",
                            action="changed",
                            field="suggested_reviewers",
                            before=[entry.github_login or entry.user_uuid for entry in before.root],
                            after=[entry.github_login or entry.user_uuid for entry in after.root],
                        )
                    ],
                ),
            )
            login = user.get_github_login()
            transaction.on_commit(
                partial(
                    forward_reviewer_correction_note,
                    team=team,
                    correction=ReviewerCorrection(
                        report_id=str(report_id),
                        added_logins=(),
                        removed_logins=(login.lower(),) if login else (),
                        actor_user_id=user.id,
                        scoped_team_ids=scoped_team_ids,
                    ),
                )
            )
        return artefact
