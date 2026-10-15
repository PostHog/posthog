from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.models import Organization, OrganizationMembership, User

from products.security.backend.logic.accounts import (
    COUNT_CAP,
    count_active_accounts,
    count_active_org_members,
    email_for_user,
    has_posthog_account,
    resolve_subject,
)


class TestAccounts(BaseTest):
    def _user(self, email: str, org: Organization | None = None, active: bool = True) -> User:
        user = User.objects.create_and_join(org or self.organization, email, "password1234", is_active=active)
        return user

    def test_resolve_email_user_and_orgs(self) -> None:
        user = self._user("farm.bot+1@example.com")
        resolved = resolve_subject("FARM.BOT+1@example.com")
        assert resolved.kind == "user"
        assert resolved.user is not None and resolved.user.uuid == str(user.uuid)
        assert resolved.organization_ids == (str(self.organization.id),)

    @parameterized.expand([("nobody@example.com",), ("12345",), ("' OR 1=1 --",), ("",)])
    def test_resolve_misses(self, query: str) -> None:
        assert resolve_subject(query).kind == "none"

    def test_resolve_uuid_user_then_organization(self) -> None:
        user = self._user("uuid.user@example.com")
        assert resolve_subject(str(user.uuid).upper()).kind == "user"
        org_resolution = resolve_subject(str(self.organization.id))
        assert org_resolution.kind == "organization"
        assert org_resolution.organization_ids == (str(self.organization.id),)

    def test_counts(self) -> None:
        self._user("farm.bot+2@example.com")
        self._user("farmbot@example.com")
        self._user("farm.bot+3@example.com", active=False)
        self._user("x@sub.throwaway.example")
        self._user("d.o.t+x@googlemail.com")
        assert count_active_accounts("email_root", "farm.bot@example.com").count == 1
        assert count_active_accounts("email", "farmbot@example.com").count == 1
        assert count_active_accounts("email_domain", "throwaway.example").count == 1
        assert count_active_accounts("email_root", "dot@gmail.com").count == 1

    def test_counts_are_capped(self) -> None:
        User.objects.bulk_create(
            [
                User(email=f"bulk{i}@capped.example", is_active=True, distinct_id=f"capped-{i}")
                for i in range(COUNT_CAP + 2)
            ]
        )
        result = count_active_accounts("email_domain", "capped.example")
        assert (result.count, result.capped) == (COUNT_CAP, True)

    def test_org_member_count_and_posthog_membership(self) -> None:
        other = Organization.objects.create(name="Bystander")
        self._user("member@bystander.example", org=other)
        exists, members = count_active_org_members(str(other.id))
        assert exists and members.count == 1
        assert count_active_org_members("9999aaaa-9999-4999-8999-99999999aaaa")[0] is False
        assert has_posthog_account(organization_id=str(other.id)) is False

        staff = self._user("staff@eu.posthog.com", org=other)
        assert has_posthog_account(organization_id=str(other.id)) is True
        assert has_posthog_account(user_uuid=str(staff.uuid)) is True
        assert email_for_user(str(staff.uuid)) == "staff@eu.posthog.com"
        assert email_for_user("9999aaaa-9999-4999-8999-99999999aaaa") is None
        assert OrganizationMembership.objects.filter(organization=other).count() == 2
