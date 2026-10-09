"""Activity-log receivers for the project-wide ReviewHog settings.

Project admins decide which repositories a project reviews and who gets automatic reviews, so every
change needs a visible author. A change to a people list is logged on its owner, the repository or
the project settings, because a reader looks for "who changed this rule", not for list rows.
"""

from typing import Any
from uuid import UUID

from django.db import models

from posthog.models.activity_logging.activity_log import AuditableScope, Change, Detail, changes_between, log_activity
from posthog.models.integration import Integration
from posthog.models.signals import model_activity_signal, mutable_receiver
from posthog.models.team import Team
from posthog.models.user import User

from products.review_hog.backend.models import (
    ReviewInstallationClaim,
    ReviewProjectSettings,
    ReviewRepository,
    ReviewRepositoryPerson,
)

PROJECT_SETTINGS_NAME = "Project settings"


def _organization_id_for_team(team_id: int) -> UUID | None:
    return Team.objects.filter(id=team_id).values_list("organization_id", flat=True).first()


def installation_account_name(installation_id: str) -> str:
    """The GitHub account of an installation, as the core GitHub integration stores it."""
    name = (
        Integration.objects.filter(kind="github", integration_id=installation_id)
        .values_list("config__account__name", flat=True)
        .first()
    )
    return name if isinstance(name, str) and name else installation_id


def _log_model_change(
    instance: models.Model,
    *,
    team_id: int,
    name: str,
    scope: AuditableScope,
    before_update: models.Model | None,
    after_update: models.Model | None,
    activity: str,
    user: User | None,
    was_impersonated: bool,
) -> None:
    log_activity(
        organization_id=_organization_id_for_team(team_id),
        team_id=team_id,
        user=user,
        was_impersonated=was_impersonated,
        item_id=instance.pk,
        scope=scope,
        activity=activity,
        detail=Detail(name=name, changes=changes_between(scope, previous=before_update, current=after_update)),
    )


@mutable_receiver(model_activity_signal, sender=ReviewRepository)
def handle_review_repository_change(
    sender: type[ReviewRepository],
    scope: AuditableScope,
    before_update: ReviewRepository | None,
    after_update: ReviewRepository | None,
    activity: str,
    user: User | None,
    was_impersonated: bool = False,
    **kwargs: Any,
) -> None:
    instance = after_update or before_update
    if instance is None:
        return
    _log_model_change(
        instance,
        team_id=instance.team_id,
        name=instance.full_name,
        scope=scope,
        before_update=before_update,
        after_update=after_update,
        activity=activity,
        user=user,
        was_impersonated=was_impersonated,
    )


@mutable_receiver(model_activity_signal, sender=ReviewProjectSettings)
def handle_review_project_settings_change(
    sender: type[ReviewProjectSettings],
    scope: AuditableScope,
    before_update: ReviewProjectSettings | None,
    after_update: ReviewProjectSettings | None,
    activity: str,
    user: User | None,
    was_impersonated: bool = False,
    **kwargs: Any,
) -> None:
    instance = after_update or before_update
    if instance is None:
        return
    _log_model_change(
        instance,
        team_id=instance.team_id,
        name=PROJECT_SETTINGS_NAME,
        scope=scope,
        before_update=before_update,
        after_update=after_update,
        activity=activity,
        user=user,
        was_impersonated=was_impersonated,
    )


@mutable_receiver(model_activity_signal, sender=ReviewInstallationClaim)
def handle_review_installation_claim_change(
    sender: type[ReviewInstallationClaim],
    scope: AuditableScope,
    before_update: ReviewInstallationClaim | None,
    after_update: ReviewInstallationClaim | None,
    activity: str,
    user: User | None,
    was_impersonated: bool = False,
    **kwargs: Any,
) -> None:
    instance = after_update or before_update
    if instance is None:
        return
    _log_model_change(
        instance,
        team_id=instance.team_id,
        name=installation_account_name(instance.installation_id),
        scope=scope,
        before_update=before_update,
        after_update=after_update,
        activity=activity,
        user=user,
        was_impersonated=was_impersonated,
    )


@mutable_receiver(model_activity_signal, sender=ReviewRepositoryPerson)
def handle_review_repository_person_change(
    sender: type[ReviewRepositoryPerson],
    scope: AuditableScope,
    before_update: ReviewRepositoryPerson | None,
    after_update: ReviewRepositoryPerson | None,
    activity: str,
    user: User | None,
    was_impersonated: bool = False,
    **kwargs: Any,
) -> None:
    # A person row has no editable field, so only an add and a remove are changes.
    if activity not in ("created", "deleted"):
        return
    instance = after_update or before_update
    if instance is None:
        return
    owner_scope: AuditableScope
    owner_name: str | None
    if instance.repository_id is None:
        owner_scope, owner_name = "ReviewProjectSettings", PROJECT_SETTINGS_NAME
        owner_id = ReviewProjectSettings.objects.for_team(instance.team_id).values_list("id", flat=True).first()
    else:
        owner_scope, owner_id = "ReviewRepository", instance.repository_id
        owner_name = (
            ReviewRepository.objects.for_team(instance.team_id)
            .filter(id=instance.repository_id)
            .values_list("full_name", flat=True)
            .first()
        )
    person_email = User.objects.filter(id=instance.user_id).values_list("email", flat=True).first()
    added = activity == "created"
    log_activity(
        organization_id=_organization_id_for_team(instance.team_id),
        team_id=instance.team_id,
        user=user,
        was_impersonated=was_impersonated,
        item_id=owner_id,
        scope=owner_scope,
        activity="updated",
        detail=Detail(
            name=owner_name,
            changes=[
                Change(
                    type=owner_scope,
                    action="created" if added else "deleted",
                    field=f"{instance.kind}_people",
                    before=None if added else person_email,
                    after=person_email if added else None,
                )
            ],
        ),
    )


def log_repository_taken(*, claim: ReviewInstallationClaim, full_name: str, taken_by_team_id: int, user: User) -> None:
    """Tell the project that takes all repositories of an installation that another project took one.

    The taking project logs its own row through the receiver above, so both projects can see the move.
    """
    organization_id = _organization_id_for_team(claim.team_id)
    taker = Team.objects.filter(id=taken_by_team_id).values("name", "organization_id").first() or {}
    # Project names stay inside their organization.
    same_organization = taker.get("organization_id") == organization_id
    taken_by = taker.get("name") if same_organization else "A project in another organization"
    log_activity(
        organization_id=organization_id,
        team_id=claim.team_id,
        user=user,
        was_impersonated=False,
        item_id=claim.id,
        scope="ReviewInstallationClaim",
        activity="updated",
        detail=Detail(
            name=installation_account_name(claim.installation_id),
            changes=[
                Change(
                    type="ReviewInstallationClaim",
                    action="changed",
                    field="repository_taken_by_another_project",
                    before=full_name,
                    after=taken_by,
                )
            ],
        ),
    )
