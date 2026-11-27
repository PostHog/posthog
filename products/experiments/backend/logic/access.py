"""Access checks for a caller that experiments holds as a `UserAccessControl`.

The facades take a `UserAccessControl`. The checks here go through the authorization SDK, for the user and
the team of that instance.
"""

from django.db.models import QuerySet

from posthog.models import Team, User

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.authorization.backend.facade import api as authorization
from products.authorization.backend.facade.contracts import Resource, Subject
from products.authorization.backend.facade.enums import ResourceType
from products.authorization.backend.presentation.querysets import filter_queryset
from products.experiments.backend.models.experiment import Experiment


def visible_experiments(access: UserAccessControl, queryset: QuerySet[Experiment]) -> QuerySet[Experiment]:
    """The experiments of `queryset` that the user of `access` may view, by the rules of its team."""
    with authorization.authorization_session():
        # Outside a request, the filter then reads the rules that `access` loaded instead of loading them again.
        authorization.reuse_current_rules(access)
        return filter_queryset(
            queryset,
            resource=Resource(type=ResourceType.EXPERIMENT, project_id=_team(access).pk),
            subject=_subject(access),
        )


def _team(access: UserAccessControl) -> Team:
    if access.team is None:
        raise ValueError("An experiment access check needs a UserAccessControl scoped to a team.")
    return access.team


def _subject(access: UserAccessControl) -> Subject | None:
    # A synthetic principal has no user id. Only a request builds one, and the SDK reads that request's principal.
    user = access.user
    return Subject(user_id=user.pk) if isinstance(user, User) and user.pk is not None else None
