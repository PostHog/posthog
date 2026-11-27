"""Access checks for surveys through the authorization SDK.

The facade takes a `UserAccessControl`. The filter here checks for the user and the team of that instance.
"""

from django.db.models import Q, QuerySet

from posthog.models import User

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.authorization.backend.facade import api as authorization
from products.authorization.backend.facade.contracts import Resource, Subject
from products.authorization.backend.facade.enums import Action, ResourceType
from products.surveys.backend.models import Survey


def filter_surveys(
    queryset: QuerySet[Survey], *, team_id: int, subject: Subject | None, include_all_if_admin: bool = False
) -> QuerySet[Survey]:
    """The surveys of `queryset` that the subject may view, by the rules of `team_id`. `subject=None` means the
    request's user. `include_all_if_admin` keeps every survey for an org admin."""
    result = authorization.list_objects(
        resource=Resource(type=ResourceType.SURVEY, project_id=team_id),
        action=Action.QUERY if include_all_if_admin else Action.VIEW,
        subject=subject,
        creator_exempt=True,
    )
    if not result.complete:
        return queryset.none()
    # The same conditions that the SDK's QuerySet filter builds from the same answer.
    creator = (
        Q(created_by=result.creator_user_id) if result.creator_exempt and result.creator_user_id is not None else None
    )
    if result.excluded:
        if not result.ids:
            return queryset
        if creator is not None:
            return queryset.exclude(Q(id__in=result.ids) & ~creator)
        return queryset.exclude(id__in=result.ids)
    if creator is not None:
        return queryset.filter(Q(id__in=result.ids) | creator)
    return queryset.filter(id__in=result.ids)


def visible_surveys(
    access_control: UserAccessControl, queryset: QuerySet[Survey], *, include_all_if_admin: bool = False
) -> QuerySet[Survey]:
    """The surveys of `queryset` that the user of `access_control` may view, by the rules of its team."""
    if access_control.team is None:
        raise ValueError("A survey access check needs a UserAccessControl scoped to a team.")
    user = access_control.user
    # A synthetic principal has no user id. Only a request builds one, and the SDK reads that request's principal.
    subject = Subject(user_id=user.pk) if isinstance(user, User) and user.pk is not None else None
    return filter_surveys(
        queryset, team_id=access_control.team.pk, subject=subject, include_all_if_admin=include_all_if_admin
    )
