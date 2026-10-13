import pytest
from unittest.mock import patch

from django.utils import timezone

from posthog.models import Organization, OrganizationDomain, OrganizationInvite, OrganizationMembership, Team, User
from posthog.models.integration import Integration
from posthog.models.user_integration import UserIntegration

from products.slack_app.backend.services import invite_request

WORKSPACE = "T_WS"
REQUESTER = "U_STRANGER"


class TestPickApprover:
    @pytest.fixture(autouse=True)
    def setup(self, db):
        self.organization = Organization.objects.create(name="Acme")
        self.team = Team.objects.create(organization=self.organization, name="Production")
        self.installer = User.objects.create(email="installer@example.com", distinct_id="u-installer", first_name="Ivy")
        self.admin = User.objects.create(email="admin@example.com", distinct_id="u-admin", first_name="Ada")
        OrganizationMembership.objects.create(
            organization=self.organization, user=self.installer, level=OrganizationMembership.Level.MEMBER
        )
        OrganizationMembership.objects.create(
            organization=self.organization, user=self.admin, level=OrganizationMembership.Level.ADMIN
        )
        self.integration = Integration.objects.create(
            team=self.team,
            kind="slack",
            integration_id=WORKSPACE,
            config={"authed_user": {"id": "U_INSTALLER"}},
            sensitive_config={"access_token": "xoxb-test"},
            created_by=self.installer,
        )

    def _link(self, user: User, slack_user_id: str) -> None:
        UserIntegration.objects.create(
            user=user,
            kind=UserIntegration.IntegrationKind.SLACK,
            integration_id=slack_user_id,
            config={"slack_team_id": WORKSPACE},
        )

    def _pick(self, requester: str = REQUESTER) -> invite_request.Approver | None:
        self.integration.refresh_from_db()
        return invite_request.pick_approver(self.organization, self.integration, requester_slack_user_id=requester)

    def test_installer_comes_first_through_the_install_record(self):
        approver = self._pick()

        assert approver is not None
        assert (approver.user.id, approver.slack_user_id, approver.path) == (
            self.installer.id,
            "U_INSTALLER",
            "installer",
        )

    def test_requester_is_never_their_own_approver(self):
        self._link(self.admin, "U_ADMIN")

        approver = self._pick(requester="U_INSTALLER")

        assert approver is not None
        assert (approver.user.id, approver.path) == (self.admin.id, "linked_admin")

    def test_member_installer_is_skipped_when_members_may_not_invite(self):
        self.organization.members_can_invite = False
        self.organization.save()
        self._link(self.admin, "U_ADMIN")

        with patch.object(Organization, "is_feature_available", return_value=True):
            approver = self._pick()

        assert approver is not None
        assert approver.path == "linked_admin"

    def test_admin_found_through_the_slack_directory_when_nobody_is_linked(self):
        self.integration.created_by = None
        self.integration.save()

        with patch(
            "products.slack_app.backend.services.invite_request.lookup_slack_user_id_by_email", return_value="U_ADMIN"
        ) as lookup:
            approver = self._pick()

        assert approver is not None
        assert (approver.user.id, approver.slack_user_id, approver.path) == (
            self.admin.id,
            "U_ADMIN",
            "looked_up_admin",
        )
        assert lookup.call_args.args[2] == "admin@example.com"

    def test_nobody_reachable_gives_no_approver(self):
        self.integration.created_by = None
        self.integration.save()

        with patch(
            "products.slack_app.backend.services.invite_request.lookup_slack_user_id_by_email", return_value=None
        ):
            assert self._pick() is None


class TestInviteGates:
    @pytest.fixture(autouse=True)
    def setup(self, db):
        self.organization = Organization.objects.create(name="Acme")
        self.other = Organization.objects.create(name="Other")

    @pytest.mark.parametrize(
        "same_org, verified, jit, expected",
        [
            pytest.param(True, True, True, True, id="verified_with_jit"),
            pytest.param(True, True, False, False, id="verified_without_jit"),
            pytest.param(True, False, True, False, id="unverified"),
            pytest.param(False, True, True, False, id="another_organizations_domain"),
        ],
    )
    def test_signing_in_only_joins_through_a_verified_jit_domain_of_the_organization(
        self, same_org, verified, jit, expected
    ):
        OrganizationDomain.objects.create(
            organization=self.organization if same_org else self.other,
            domain="example.com",
            verified_at=timezone.now() if verified else None,
            jit_provisioning_enabled=jit,
        )

        assert invite_request.jit_signin_available(self.organization, "new.person@example.com") is expected

    def test_a_workspace_connected_to_two_organizations_names_no_organization(self):
        teams = [Team.objects.create(organization=org, name="t") for org in (self.organization, self.other)]
        candidates = [
            Integration.objects.create(team=team, kind="slack", integration_id=WORKSPACE, sensitive_config={})
            for team in teams
        ]

        assert invite_request.single_organization(candidates[:1]) == self.organization
        assert invite_request.single_organization(candidates) is None


class TestCreateInvite:
    @pytest.fixture(autouse=True)
    def setup(self, db):
        self.organization = Organization.objects.create(name="Acme")
        self.approver = User.objects.create(email="admin@example.com", distinct_id="u-admin", first_name="Ada")
        OrganizationMembership.objects.create(
            organization=self.organization, user=self.approver, level=OrganizationMembership.Level.ADMIN
        )
        self.email_available = patch(
            "products.slack_app.backend.services.invite_request.is_email_available", return_value=True
        )
        self.email_available.start()
        yield
        self.email_available.stop()

    def _create(self, email: str):
        with patch("products.slack_app.backend.services.invite_request.send_invite.apply_async") as send:
            result = invite_request.create_invite(
                self.organization, email=email, approver=self.approver, mention_channel="C001"
            )
        return result, send

    def test_sends_a_member_invite_from_the_approver_and_replaces_a_pending_one(self):
        stale = OrganizationInvite.objects.create(organization=self.organization, target_email="New.Person@example.com")

        result, send = self._create("New.Person@example.com")

        assert isinstance(result, OrganizationInvite)
        assert (result.created_by_id, result.level, result.target_email) == (
            self.approver.id,
            OrganizationMembership.Level.MEMBER,
            "new.person@example.com",
        )
        assert not OrganizationInvite.objects.filter(id=stale.id).exists()
        send.assert_called_once_with(kwargs={"invite_id": str(result.id)})

    @pytest.mark.parametrize(
        "email, expected",
        [
            pytest.param("admin@example.com", "existing_member", id="already_a_member"),
            pytest.param("new+slack@example.com", "plus_address", id="plus_addressed"),
        ],
    )
    def test_refuses_what_the_invite_api_refuses(self, email, expected):
        result, send = self._create(email)

        assert result == expected
        send.assert_not_called()
        assert OrganizationInvite.objects.count() == 0
