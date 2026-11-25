from rest_framework.exceptions import ValidationError

from posthog.api.utils import ServiceRequest
from posthog.models import Team, User

from products.feature_flags.backend.facade.api import update_flag
from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.feature_flags.backend.ownership import (
    FLAG_OWNER_PRODUCT_TOUR,
    FLAG_OWNER_SURVEY,
    flag_owner_label,
    iter_flag_owner_kinds,
)


def delete_flag(flag: FeatureFlag, *, team: Team, user: User, request: ServiceRequest) -> FeatureFlag:
    """Soft-delete a flag through the gated flag write.

    That write refuses a flag that an early access feature, a running experiment, another flag, or
    a replay setting uses. A flag that a survey or a product tour owns is refused here. The caller
    checks that the user can edit the flag.
    """
    for owner in iter_flag_owner_kinds(flag):
        if owner in (FLAG_OWNER_SURVEY, FLAG_OWNER_PRODUCT_TOUR):
            raise ValidationError(f"Cannot delete a feature flag that belongs to {flag_owner_label(owner)}.")
    # A config version 2 flag requires its version on every write.
    data = {"deleted": True, "version": flag.version or 0}
    return update_flag(flag, data, team=team, user=user, request=request)
