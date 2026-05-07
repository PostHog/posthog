from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from posthog.models import OrganizationMembership, Team
from posthog.models.organization import Organization

from products.web_analytics.backend.temporal.weekly_digest.activities import _send_digest_for_user, _send_test_digest


def _make_team_digest(team, visitors=10):
    return {
        "team": team,
        "visitors": {"current": visitors, "previous": None, "change": None},
        "pageviews": {"current": 0, "previous": None, "change": None},
        "sessions": {"current": 0, "previous": None, "change": None},
        "bounce_rate": {"current": 0.0, "previous": None, "change": None},
        "avg_session_duration": {"current": "0s", "previous": "0s", "change": None},
        "top_pages": [],
        "top_sources": [],
        "goals": [],
        "dashboard_url": "https://example.com",
    }


class _DigestTestBase(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.is_email_patcher = patch(
            "products.web_analytics.backend.temporal.weekly_digest.activities.is_email_available",
            return_value=True,
        )
        self.is_email_patcher.start()
        self.email_class_patcher = patch(
            "products.web_analytics.backend.temporal.weekly_digest.activities.EmailMessage"
        )
        self.mock_email_class = self.email_class_patcher.start()
        self.mock_message = MagicMock()
        self.mock_email_class.return_value = self.mock_message
        # close_old_connections is needed when running in a thread pool, but it
        # tears down the test transaction's connection when called inline.
        self.close_conn_patcher = patch(
            "products.web_analytics.backend.temporal.weekly_digest.activities.close_old_connections"
        )
        self.close_conn_patcher.start()

    def tearDown(self):
        self.close_conn_patcher.stop()
        self.is_email_patcher.stop()
        self.email_class_patcher.stop()
        super().tearDown()


class TestSendDigestForUser(_DigestTestBase):
    def test_sends_email_with_default_notification_settings(self):
        sent = _send_digest_for_user(
            user=self.user,
            org=self.organization,
            membership=self.organization_membership,
            team_digest_data={self.team.id: _make_team_digest(self.team)},
            date_suffix="2025-15",
        )
        assert sent is True
        self.mock_email_class.assert_called_once()
        kwargs = self.mock_email_class.call_args.kwargs
        assert kwargs["subject"] == f"Web analytics weekly digest for {self.organization.name}"
        assert "_test_" not in kwargs["campaign_key"]
        self.mock_message.add_user_recipient.assert_called_once_with(self.user)
        self.mock_message.send.assert_called_once()

    def test_skips_when_org_level_opt_out_and_not_test(self):
        self.user.partial_notification_settings = {"web_analytics_weekly_digest": False}
        self.user.save()
        sent = _send_digest_for_user(
            user=self.user,
            org=self.organization,
            membership=self.organization_membership,
            team_digest_data={self.team.id: _make_team_digest(self.team)},
            date_suffix="2025-15",
        )
        assert sent is False
        self.mock_email_class.assert_not_called()

    def test_sends_anyway_when_org_level_opt_out_but_test_true(self):
        self.user.partial_notification_settings = {"web_analytics_weekly_digest": False}
        self.user.save()
        sent = _send_digest_for_user(
            user=self.user,
            org=self.organization,
            membership=self.organization_membership,
            team_digest_data={self.team.id: _make_team_digest(self.team)},
            date_suffix="2025-15",
            test=True,
        )
        assert sent is True
        kwargs = self.mock_email_class.call_args.kwargs
        assert "_test_" in kwargs["campaign_key"]

    def test_returns_false_when_team_digest_data_is_empty(self):
        sent = _send_digest_for_user(
            user=self.user,
            org=self.organization,
            membership=self.organization_membership,
            team_digest_data={},
            date_suffix="2025-15",
            test=True,
        )
        assert sent is False
        self.mock_email_class.assert_not_called()

    def test_dry_run_does_not_send(self):
        sent = _send_digest_for_user(
            user=self.user,
            org=self.organization,
            membership=self.organization_membership,
            team_digest_data={self.team.id: _make_team_digest(self.team)},
            date_suffix="2025-15",
            dry_run=True,
        )
        assert sent is True
        self.mock_email_class.assert_not_called()

    def test_test_mode_bypasses_per_team_opt_out(self):
        team_b = Team.objects.create(organization=self.organization, name="Team B")
        self.user.partial_notification_settings = {
            "web_analytics_weekly_digest_project_enabled": {str(self.team.id): True},
        }
        self.user.save()
        sent = _send_digest_for_user(
            user=self.user,
            org=self.organization,
            membership=self.organization_membership,
            team_digest_data={
                self.team.id: _make_team_digest(self.team, visitors=20),
                team_b.id: _make_team_digest(team_b, visitors=50),
            },
            date_suffix="2025-15",
            test=True,
        )
        assert sent is True
        sections = self.mock_email_class.call_args.kwargs["template_context"]["project_sections"]
        assert {s["team"].id for s in sections} == {self.team.id, team_b.id}

    def test_real_mode_filters_per_team_opt_outs(self):
        team_b = Team.objects.create(organization=self.organization, name="Team B")
        self.user.partial_notification_settings = {
            "web_analytics_weekly_digest_project_enabled": {str(self.team.id): True},
        }
        self.user.save()
        sent = _send_digest_for_user(
            user=self.user,
            org=self.organization,
            membership=self.organization_membership,
            team_digest_data={
                self.team.id: _make_team_digest(self.team),
                team_b.id: _make_team_digest(team_b),
            },
            date_suffix="2025-15",
        )
        assert sent is True
        ctx = self.mock_email_class.call_args.kwargs["template_context"]
        assert [s["team"].id for s in ctx["project_sections"]] == [self.team.id]
        assert team_b.name in ctx["disabled_project_names"]

    def test_sections_sorted_by_visitors_descending(self):
        team_b = Team.objects.create(organization=self.organization, name="Team B")
        team_c = Team.objects.create(organization=self.organization, name="Team C")
        sent = _send_digest_for_user(
            user=self.user,
            org=self.organization,
            membership=self.organization_membership,
            team_digest_data={
                self.team.id: _make_team_digest(self.team, visitors=5),
                team_b.id: _make_team_digest(team_b, visitors=100),
                team_c.id: _make_team_digest(team_c, visitors=50),
            },
            date_suffix="2025-15",
            test=True,
        )
        assert sent is True
        sections = self.mock_email_class.call_args.kwargs["template_context"]["project_sections"]
        assert [s["team"].id for s in sections] == [team_b.id, team_c.id, self.team.id]


class TestSendTestDigestSingleTeamMode(_DigestTestBase):
    def setUp(self):
        super().setUp()
        self.build_digest_patcher = patch(
            "products.web_analytics.backend.temporal.weekly_digest.activities.build_team_digest",
            side_effect=lambda team: _make_team_digest(team),
        )
        self.build_digest_patcher.start()

    def tearDown(self):
        self.build_digest_patcher.stop()
        super().tearDown()

    def test_sends_to_user_with_team_access(self):
        _send_test_digest(email=self.user.email, team_id=self.team.id)
        self.mock_email_class.assert_called_once()
        self.mock_message.add_user_recipient.assert_called_once_with(self.user)

    def test_raises_when_team_not_found(self):
        with self.assertRaises(ValueError) as cm:
            _send_test_digest(email=self.user.email, team_id=999_999)
        assert "Team 999999 not found" in str(cm.exception)
        self.mock_email_class.assert_not_called()

    def test_raises_when_email_has_no_user(self):
        with self.assertRaises(ValueError) as cm:
            _send_test_digest(email="nobody@example.com", team_id=self.team.id)
        assert "No active user found with email nobody@example.com" in str(cm.exception)
        self.mock_email_class.assert_not_called()

    def test_raises_when_user_not_in_teams_org(self):
        other_org = Organization.objects.create(name="Other org")
        other_team = Team.objects.create(organization=other_org, name="Other team")
        with self.assertRaises(PermissionError) as cm:
            _send_test_digest(email=self.user.email, team_id=other_team.id)
        assert "is not a member of the organization that owns team" in str(cm.exception)
        self.mock_email_class.assert_not_called()

    def test_raises_when_user_inactive(self):
        self.user.is_active = False
        self.user.save()
        with self.assertRaises(ValueError):
            _send_test_digest(email=self.user.email, team_id=self.team.id)
        self.mock_email_class.assert_not_called()

    def test_email_lookup_is_case_insensitive(self):
        _send_test_digest(email=self.user.email.upper(), team_id=self.team.id)
        self.mock_email_class.assert_called_once()
        self.mock_message.add_user_recipient.assert_called_once_with(self.user)


class TestSendTestDigestFullUserMode(_DigestTestBase):
    def setUp(self):
        super().setUp()
        self.build_digest_patcher = patch(
            "products.web_analytics.backend.temporal.weekly_digest.activities.build_team_digest",
            side_effect=lambda team: _make_team_digest(team),
        )
        self.build_digest_patcher.start()

    def tearDown(self):
        self.build_digest_patcher.stop()
        super().tearDown()

    def test_sends_one_email_per_org(self):
        other_org = Organization.objects.create(name="Other org")
        Team.objects.create(organization=other_org, name="Other team")
        OrganizationMembership.objects.create(
            organization=other_org,
            user=self.user,
            level=OrganizationMembership.Level.MEMBER,
        )

        _send_test_digest(email=self.user.email)

        assert self.mock_email_class.call_count == 2
        org_names = {
            call.kwargs["template_context"]["organization"].name for call in self.mock_email_class.call_args_list
        }
        assert org_names == {self.organization.name, "Other org"}

    def test_includes_all_teams_in_an_org(self):
        Team.objects.create(organization=self.organization, name="Team B")
        _send_test_digest(email=self.user.email)
        self.mock_email_class.assert_called_once()
        sections = self.mock_email_class.call_args.kwargs["template_context"]["project_sections"]
        assert len(sections) == 2

    def test_raises_when_user_has_no_memberships(self):
        self.organization_membership.delete()
        with self.assertRaises(ValueError) as cm:
            _send_test_digest(email=self.user.email)
        assert "has no organization memberships" in str(cm.exception)
        self.mock_email_class.assert_not_called()

    def test_raises_when_email_has_no_user(self):
        with self.assertRaises(ValueError):
            _send_test_digest(email="nobody@example.com")
        self.mock_email_class.assert_not_called()
