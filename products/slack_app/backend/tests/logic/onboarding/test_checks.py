import pytest

from posthog.models import Organization, OrganizationMembership

from products.slack_app.backend.logic.onboarding.checks import is_org_admin


@pytest.mark.django_db
@pytest.mark.parametrize(
    "level, expected",
    [
        (OrganizationMembership.Level.MEMBER, False),
        (OrganizationMembership.Level.ADMIN, True),
        (OrganizationMembership.Level.OWNER, True),
        (None, False),
    ],
)
def test_only_an_admin_of_the_teams_organization_is_an_org_admin(
    level: OrganizationMembership.Level | None, expected: bool, org_team_user
) -> None:
    org, team, user = org_team_user
    if level is None:
        OrganizationMembership.objects.filter(user=user, organization=org).delete()
        other = Organization.objects.create(name="Other Org")
        OrganizationMembership.objects.create(user=user, organization=other, level=OrganizationMembership.Level.ADMIN)
    else:
        OrganizationMembership.objects.filter(user=user, organization=org).update(level=level)

    assert is_org_admin(user.id, team.id) is expected
