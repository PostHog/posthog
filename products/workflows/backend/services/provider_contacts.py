"""Turns a provider's contacts into people, matched by email, and fills a static cohort with them."""

from collections.abc import Sequence

from posthog.models import Team, User

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.workflows.backend.facade.contracts import PeopleImportInvalid, ProviderContactsResult
from products.workflows.backend.services.people_import import MAX_PEOPLE_IMPORT_ROWS, start_people_import
from products.workflows.backend.services.provider_cohorts import import_cohort


def import_provider_contacts(
    team_id: int,
    user_id: int | None,
    rows: Sequence[dict[str, str]],
    *,
    create_people: bool,
    send_events: bool,
    cohort_name: str,
    cohort_description: str,
    source: str,
) -> ProviderContactsResult:
    """Update the person each contact's email matches, and create a person for the rest when `create_people` is set.

    Each row holds an `email` and the person properties to set. The people go into the cohort with
    `cohort_description`, created on the first import. Without `send_events`, only the cohort fills, and an import of
    the same contacts with `send_events` creates and updates the people. `source` names the list in a note, such as 'the Resend
    segment "VIPs"'.
    """
    if not rows:
        return ProviderContactsResult(status="skipped", notes=("No contacts to import.",))
    team = Team.objects.get(id=team_id)
    user = User.objects.filter(id=user_id).first()
    if user is None:
        return ProviderContactsResult(status="failed", notes=("The person who started this import no longer exists.",))
    access = UserAccessControl(user=user, team=team)
    # The import runs in the background, so the person who started it may have lost access since.
    if not user.is_active or not access.has_project_access:
        return ProviderContactsResult(
            status="failed", notes=("The person who started this import can't access this project anymore.",)
        )
    cohort = import_cohort(team_id, user, access, description=cohort_description, name=cohort_name, source=source)
    if cohort.cohort_id is None:
        return ProviderContactsResult(status="failed", notes=(cohort.problem,))

    contacts = new_people = skipped_new_people = dropped = 0
    try:
        # One import holds a bounded number of rows, so a long list fills the cohort in several imports.
        for start in range(0, len(rows), MAX_PEOPLE_IMPORT_ROWS):
            summary = start_people_import(
                team=team,
                user=user,
                name=cohort.name,
                rows=list(rows[start : start + MAX_PEOPLE_IMPORT_ROWS]),
                cohort_id=cohort.cohort_id,
                create_missing=create_people,
                send_events=send_events,
            )
            contacts += summary.row_count
            new_people += summary.new_people
            skipped_new_people += summary.skipped_new_people
            dropped += summary.dropped_invalid_email + summary.dropped_duplicate_email + summary.dropped_too_large
    except PeopleImportInvalid as error:
        return ProviderContactsResult(
            status="failed", cohort_id=cohort.cohort_id, cohort_name=cohort.name, notes=(str(error),)
        )
    return ProviderContactsResult(
        status="created" if contacts else "skipped",
        cohort_id=cohort.cohort_id,
        cohort_name=cohort.name,
        people=contacts,
        new_people=new_people,
        skipped_new_people=skipped_new_people,
        dropped=dropped,
    )
