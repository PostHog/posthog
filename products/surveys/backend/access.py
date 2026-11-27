"""Access checks for a caller that surveys holds as a `UserAccessControl`.

The facade takes a `UserAccessControl`. The filter here goes through the authorization SDK, for the user and
the team of that instance.
"""

from django.db.models import QuerySet

from posthog.models import User

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.authorization.backend.facade.contracts import Resource, Subject
from products.authorization.backend.facade.enums import ResourceType
from products.authorization.backend.presentation.querysets import filter_queryset
from products.surveys.backend.models import Survey


def visible_surveys(
    access_control: UserAccessControl, queryset: QuerySet[Survey], *, include_all_if_admin: bool = False
) -> QuerySet[Survey]:
    """The surveys of `queryset` that the user of `access_control` may view, by the rules of its team."""
    if access_control.team is None:
        raise ValueError("A survey access check needs a UserAccessControl scoped to a team.")
    user = access_control.user
    # A synthetic principal has no user id. Only a request builds one, and the SDK reads that request's principal.
    subject = Subject(user_id=user.pk) if isinstance(user, User) and user.pk is not None else None
    return filter_queryset(
        queryset,
        resource=Resource(type=ResourceType.SURVEY, project_id=access_control.team.pk),
        subject=subject,
        include_all_if_admin=include_all_if_admin,
    )
