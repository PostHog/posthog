"""The static cohort an import fills for a provider's list or segment, found again by its description on a rerun."""

from posthog.models import User

from products.access_control.backend.facade.contracts import ObjectAccessRef
from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.cohorts.backend.facade.api import create_empty_static_cohort, find_cohort_ref_by_description
from products.workflows.backend.services.resend_import.translator import SegmentCohort

# Cohort names hold up to 400 characters, and the name gets a suffix such as " (from Resend)".
MAX_SOURCE_NAME_LENGTH = 380


def resend_segment_description(segment_id: str) -> str:
    # The automation and contact imports both find a segment's cohort by this text, so it must not change.
    return f"Imported from Resend segment {segment_id}."


def import_cohort(
    team_id: int, user: User, access: UserAccessControl, *, description: str, name: str, source: str
) -> SegmentCohort:
    """Find the cohort an earlier import made with this description, or create it.

    `name` is the cohort's name, and `source` names what it stands for in a problem, such as 'the Resend segment "VIPs"'.
    Nothing else ties a cohort to its source, and the description stays the same when either one is renamed.
    """
    existing = find_cohort_ref_by_description(team_id=team_id, description=description)
    if existing is None:
        if not access.check_access_level_for_resource("cohort", "editor"):
            return SegmentCohort(problem=f"Creating a cohort for {source} needs edit access to cohorts.")
        created = create_empty_static_cohort(team_id=team_id, name=name, description=description, created_by_id=user.id)
        return SegmentCohort(name=name, cohort_id=created.id)
    if existing.deleted:
        return SegmentCohort(problem=f"The cohort made for {source} was deleted, so it stays deleted.")
    if not existing.is_static:
        return SegmentCohort(problem=f"The cohort made for {source} isn't static anymore.")
    ref = ObjectAccessRef(
        resource="cohort", id=str(existing.id), team_id=existing.team_id, created_by_id=existing.created_by_id
    )
    if not access.check_access_level_for_ref(ref, "editor"):
        return SegmentCohort(problem=f"Adding people to the cohort for {source} needs edit access.")
    return SegmentCohort(name=name, cohort_id=existing.id)
