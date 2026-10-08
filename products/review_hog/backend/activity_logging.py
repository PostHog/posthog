"""Activity-log receivers for the repositories that get automatic reviews.

Any project member can add a repository and change who it reviews, so every change needs a
visible author. A change to a repository's people lists is logged on the repository, because a
reader looks for "who changed this repository", not for list rows.
"""

from typing import Any
from uuid import UUID

from posthog.models.activity_logging.activity_log import AuditableScope, Change, Detail, changes_between, log_activity
from posthog.models.signals import model_activity_signal, mutable_receiver
from posthog.models.team import Team
from posthog.models.user import User

from products.review_hog.backend.models import ReviewRepository, ReviewRepositoryPerson


def _organization_id_for_team(team_id: int) -> UUID | None:
    return Team.objects.filter(id=team_id).values_list("organization_id", flat=True).first()


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
    log_activity(
        organization_id=_organization_id_for_team(instance.team_id),
        team_id=instance.team_id,
        user=user,
        was_impersonated=was_impersonated,
        item_id=instance.id,
        scope=scope,
        activity=activity,
        detail=Detail(
            name=instance.full_name,
            changes=changes_between(scope, previous=before_update, current=after_update),
        ),
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
    repository_name = (
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
        item_id=instance.repository_id,
        scope="ReviewRepository",
        activity="updated",
        detail=Detail(
            name=repository_name,
            changes=[
                Change(
                    type="ReviewRepository",
                    action="created" if added else "deleted",
                    field=f"{instance.kind}_people",
                    before=None if added else person_email,
                    after=person_email if added else None,
                )
            ],
        ),
    )
