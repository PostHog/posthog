from datetime import timedelta

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.utils import timezone

from parameterized import parameterized
from temporalio.exceptions import ApplicationError

from posthog.clickhouse.client.execute import KillSwitchLevel
from posthog.models import OrganizationMembership, Team, User
from posthog.models.organization import Organization

from products.web_analytics.backend.temporal.weekly_digest.activities import (
    _get_org_batch_page,
    _is_user_targeted_for_digest,
    _run_wa_digest_batch,
    _send_digest_for_user,
    _send_test_digest,
)
from products.web_analytics.backend.temporal.weekly_digest.types import (
    WA_DIGEST_EMAIL_UNAVAILABLE_TYPE,
    DigestBatchInput,
    DigestBatchResult,
    DigestOutcome,
    OrgBatchPageInput,
    OrgDigestCounts,
    WAWeeklyDigestInput,
)


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
        outcome = _send_digest_for_user(
            user=self.user,
            org=self.organization,
            membership=self.organization_membership,
            team_digest_data={self.team.id: _make_team_digest(self.team)},
            date_suffix="2025-15",
        )
        assert outcome == DigestOutcome.SENT
        self.mock_email_class.assert_called_once()
        kwargs = self.mock_email_class.call_args.kwargs
        assert kwargs["subject"] == f"Web analytics weekly digest for {self.organization.name}"
        assert "_test_" not in kwargs["campaign_key"]
        self.mock_message.add_user_recipient.assert_called_once_with(self.user)
        self.mock_message.send.assert_called_once()

    def test_skips_when_org_level_opt_out_and_not_test(self):
        self.user.partial_notification_settings = {"web_analytics_weekly_digest": False}
        self.user.save()
        outcome = _send_digest_for_user(
            user=self.user,
            org=self.organization,
            membership=self.organization_membership,
            team_digest_data={self.team.id: _make_team_digest(self.team)},
            date_suffix="2025-15",
        )
        assert outcome == DigestOutcome.SKIPPED_OPTOUT
        self.mock_email_class.assert_not_called()

    def test_sends_anyway_when_org_level_opt_out_but_test_true(self):
        self.user.partial_notification_settings = {"web_analytics_weekly_digest": False}
        self.user.save()
        outcome = _send_digest_for_user(
            user=self.user,
            org=self.organization,
            membership=self.organization_membership,
            team_digest_data={self.team.id: _make_team_digest(self.team)},
            date_suffix="2025-15",
            test=True,
        )
        assert outcome == DigestOutcome.SENT
        kwargs = self.mock_email_class.call_args.kwargs
        assert "_test_" in kwargs["campaign_key"]

    def test_returns_no_data_when_team_digest_data_is_empty(self):
        outcome = _send_digest_for_user(
            user=self.user,
            org=self.organization,
            membership=self.organization_membership,
            team_digest_data={},
            date_suffix="2025-15",
            test=True,
        )
        assert outcome == DigestOutcome.SKIPPED_NO_DATA
        self.mock_email_class.assert_not_called()

    def test_dry_run_does_not_send(self):
        outcome = _send_digest_for_user(
            user=self.user,
            org=self.organization,
            membership=self.organization_membership,
            team_digest_data={self.team.id: _make_team_digest(self.team)},
            date_suffix="2025-15",
            dry_run=True,
        )
        assert outcome == DigestOutcome.DRY_RUN
        self.mock_email_class.assert_not_called()

    def test_returns_failed_when_email_send_raises(self):
        self.mock_message.send.side_effect = RuntimeError("smtp blew up")
        outcome = _send_digest_for_user(
            user=self.user,
            org=self.organization,
            membership=self.organization_membership,
            team_digest_data={self.team.id: _make_team_digest(self.team)},
            date_suffix="2025-15",
        )
        assert outcome == DigestOutcome.FAILED

    def test_propagates_send_error_when_test_mode(self):
        self.mock_message.send.side_effect = RuntimeError("smtp blew up")
        with self.assertRaises(RuntimeError) as cm:
            _send_digest_for_user(
                user=self.user,
                org=self.organization,
                membership=self.organization_membership,
                team_digest_data={self.team.id: _make_team_digest(self.team)},
                date_suffix="2025-15",
                test=True,
            )
        assert "smtp blew up" in str(cm.exception)

    def test_test_mode_bypasses_per_team_opt_out(self):
        team_b = Team.objects.create(organization=self.organization, name="Team B")
        self.user.partial_notification_settings = {
            "web_analytics_weekly_digest_project_enabled": {str(self.team.id): True},
        }
        self.user.save()
        outcome = _send_digest_for_user(
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
        assert outcome == DigestOutcome.SENT
        sections = self.mock_email_class.call_args.kwargs["template_context"]["project_sections"]
        assert {s["team"].id for s in sections} == {self.team.id, team_b.id}

    def test_real_mode_filters_per_team_opt_outs(self):
        team_b = Team.objects.create(organization=self.organization, name="Team B")
        self.user.partial_notification_settings = {
            "web_analytics_weekly_digest_project_enabled": {str(self.team.id): True},
        }
        self.user.save()
        outcome = _send_digest_for_user(
            user=self.user,
            org=self.organization,
            membership=self.organization_membership,
            team_digest_data={
                self.team.id: _make_team_digest(self.team),
                team_b.id: _make_team_digest(team_b),
            },
            date_suffix="2025-15",
        )
        assert outcome == DigestOutcome.SENT
        ctx = self.mock_email_class.call_args.kwargs["template_context"]
        assert [s["team"].id for s in ctx["project_sections"]] == [self.team.id]
        assert team_b.name in ctx["disabled_project_names"]

    def test_sections_sorted_by_visitors_descending(self):
        team_b = Team.objects.create(organization=self.organization, name="Team B")
        team_c = Team.objects.create(organization=self.organization, name="Team C")
        outcome = _send_digest_for_user(
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
        assert outcome == DigestOutcome.SENT
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


class TestGetOrgBatchPage(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.kill_switch_patcher = patch(
            "products.web_analytics.backend.temporal.weekly_digest.activities.get_kill_switch_level",
        )
        self.mock_kill_switch = self.kill_switch_patcher.start()
        self.mock_kill_switch.return_value = KillSwitchLevel.OFF
        self.email_available_patcher = patch(
            "products.web_analytics.backend.temporal.weekly_digest.activities.is_email_available",
            return_value=True,
        )
        self.mock_email_available = self.email_available_patcher.start()
        self.close_conn_patcher = patch(
            "products.web_analytics.backend.temporal.weekly_digest.activities.close_old_connections"
        )
        self.close_conn_patcher.start()

    def tearDown(self):
        self.close_conn_patcher.stop()
        self.email_available_patcher.stop()
        self.kill_switch_patcher.stop()
        super().tearDown()

    def test_returns_empty_list_when_kill_switch_active(self):
        self.mock_kill_switch.return_value = KillSwitchLevel.LIGHT
        page = _get_org_batch_page(OrgBatchPageInput(workflow_input=WAWeeklyDigestInput()))
        assert page.batches == []
        assert page.cursor is None

    def test_raises_when_email_unavailable(self):
        self.mock_email_available.return_value = False
        with self.assertRaises(ApplicationError) as ctx:
            _get_org_batch_page(OrgBatchPageInput(workflow_input=WAWeeklyDigestInput()))
        assert ctx.exception.type == WA_DIGEST_EMAIL_UNAVAILABLE_TYPE
        assert ctx.exception.non_retryable is True

    def test_kill_switch_short_circuits_before_email_check(self):
        self.mock_kill_switch.return_value = KillSwitchLevel.LIGHT
        self.mock_email_available.return_value = False
        page = _get_org_batch_page(OrgBatchPageInput(workflow_input=WAWeeklyDigestInput()))
        assert page.batches == []
        assert page.cursor is None

    def test_keyset_pagination_returns_first_middle_and_final_pages(self):
        for i in range(4):
            Organization.objects.create(name=f"Org {i}")
        # Expected ids come from the database rather than just the orgs created above:
        # committed strays from earlier suites can survive in CI's shared --reuse-db
        # database, and pagination pages over whatever exists.
        expected_ids = sorted(str(oid) for oid in Organization.objects.values_list("id", flat=True))

        first_page = _get_org_batch_page(
            OrgBatchPageInput(
                workflow_input=WAWeeklyDigestInput(active_since_days=None, batch_size=2),
                page_size=2,
            )
        )
        assert [oid for batch in first_page.batches for oid in batch] == expected_ids[:2]
        assert first_page.cursor == expected_ids[1]

        final_ids: list[str] = []
        cursor: str | None = first_page.cursor
        while cursor is not None:
            page = _get_org_batch_page(
                OrgBatchPageInput(
                    workflow_input=WAWeeklyDigestInput(active_since_days=None, batch_size=2),
                    cursor=cursor,
                    page_size=2,
                )
            )
            final_ids.extend(oid for batch in page.batches for oid in batch)
            cursor = page.cursor

        assert expected_ids[:2] + final_ids == expected_ids

    def test_active_since_filter_excludes_orgs_with_only_dormant_members(self):
        self.user.last_login = timezone.now()
        self.user.save()

        dormant_org = Organization.objects.create(name="Dormant org")
        dormant_user = User.objects.create_user(email="dormant@example.com", password="x", first_name="Dormant")
        dormant_user.last_login = timezone.now() - timedelta(days=200)
        dormant_user.save()
        OrganizationMembership.objects.create(
            organization=dormant_org,
            user=dormant_user,
            level=OrganizationMembership.Level.MEMBER,
        )

        page = _get_org_batch_page(OrgBatchPageInput(workflow_input=WAWeeklyDigestInput(active_since_days=30)))
        all_org_ids = {oid for batch in page.batches for oid in batch}
        assert str(self.organization.id) in all_org_ids
        assert str(dormant_org.id) not in all_org_ids

    def test_admin_org_ids_override_pages_by_index_and_bypasses_filters(self):
        override = ["1111", "2222", "3333"]
        first_page = _get_org_batch_page(
            OrgBatchPageInput(
                workflow_input=WAWeeklyDigestInput(org_ids=override, batch_size=2, active_since_days=1),
                page_size=2,
            )
        )
        assert [oid for batch in first_page.batches for oid in batch] == ["1111", "2222"]
        assert first_page.cursor == "2"

        second_page = _get_org_batch_page(
            OrgBatchPageInput(
                workflow_input=WAWeeklyDigestInput(org_ids=override, batch_size=2, active_since_days=1),
                cursor=first_page.cursor,
                page_size=2,
            )
        )
        assert [oid for batch in second_page.batches for oid in batch] == ["3333"]
        assert second_page.cursor is None


class TestRunWaDigestBatch(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.close_conn_patcher = patch(
            "products.web_analytics.backend.temporal.weekly_digest.activities.close_old_connections"
        )
        self.close_conn_patcher.start()

    def tearDown(self):
        self.close_conn_patcher.stop()
        super().tearDown()

    def test_aggregates_per_org_results(self):
        results_by_org = {
            "1": OrgDigestCounts(
                sent=2,
                skipped_optout=1,
                team_count=3,
                build_duration=0.4,
                send_duration=0.2,
            ),
            "2": OrgDigestCounts(
                skipped_no_data=5,
                failed=1,
                team_count=1,
                build_duration=0.1,
                send_duration=0.05,
            ),
            "3": OrgDigestCounts(skipped_reason="no_teams"),
        }

        with patch(
            "products.web_analytics.backend.temporal.weekly_digest.activities._build_and_send_for_org",
            side_effect=lambda org_id, dry_run: results_by_org[org_id],
        ):
            totals = _run_wa_digest_batch(DigestBatchInput(org_ids=["1", "2", "3"]))

        assert totals.batch_size == 3
        assert totals.orgs_processed == 2
        assert totals.orgs_skipped == 1
        assert totals.orgs_failed == 0
        assert totals.emails_sent == 2
        assert totals.emails_skipped_optout == 1
        assert totals.emails_skipped_no_data == 5
        assert totals.emails_failed == 1

    def test_isolates_per_org_failures(self):
        def fake_build_and_send(org_id, dry_run):
            if org_id == "2":
                raise RuntimeError("clickhouse exploded for org 2")
            return OrgDigestCounts(sent=1, team_count=1)

        with patch(
            "products.web_analytics.backend.temporal.weekly_digest.activities._build_and_send_for_org",
            side_effect=fake_build_and_send,
        ):
            totals = _run_wa_digest_batch(DigestBatchInput(org_ids=["1", "2", "3"]))

        assert totals.orgs_processed == 2
        assert totals.orgs_failed == 1
        assert totals.emails_sent == 2

    def test_failure_rate_excludes_skipped_orgs(self):
        with patch(
            "products.web_analytics.backend.temporal.weekly_digest.activities._build_and_send_for_org",
            side_effect=lambda org_id, dry_run: OrgDigestCounts(skipped_reason="no_teams"),
        ):
            totals = _run_wa_digest_batch(DigestBatchInput(org_ids=["1", "2", "3"]))

        assert totals.orgs_skipped == 3
        assert totals.orgs_failed == 0
        assert totals.failure_rate == 0.0

    @parameterized.expand(
        [
            ("all_skipped", {"batch_size": 100, "orgs_skipped": 100}, 0.0),
            ("all_failed", {"batch_size": 10, "orgs_failed": 10}, 1.0),
            ("mixed_skip_and_fail", {"batch_size": 100, "orgs_skipped": 90, "orgs_failed": 10}, 1.0),
            (
                "mixed_processed_and_failed",
                {"batch_size": 10, "orgs_processed": 8, "orgs_failed": 2},
                0.2,
            ),
            (
                "skipped_does_not_dilute",
                {"batch_size": 100, "orgs_processed": 1, "orgs_skipped": 98, "orgs_failed": 1},
                0.5,
            ),
            ("empty", {}, 0.0),
        ]
    )
    def test_failure_rate_denominator_excludes_skipped(self, _name, fields, expected):
        result = DigestBatchResult(**fields)
        assert result.failure_rate == expected

    def test_aggregates_email_attribution_via_real_build_and_send(self):
        opted_out = User.objects.create_user(email="opted-out@example.com", password="x", first_name="Out")
        opted_out.partial_notification_settings = {"web_analytics_weekly_digest": False}
        opted_out.save()
        OrganizationMembership.objects.create(
            organization=self.organization,
            user=opted_out,
            level=OrganizationMembership.Level.MEMBER,
        )

        with (
            patch(
                "products.web_analytics.backend.temporal.weekly_digest.activities.posthoganalytics.feature_enabled",
                return_value=True,
            ),
            patch(
                "products.web_analytics.backend.temporal.weekly_digest.activities.build_team_digest",
                side_effect=lambda team: _make_team_digest(team),
            ),
            patch("products.web_analytics.backend.temporal.weekly_digest.activities.EmailMessage") as mock_email_class,
        ):
            mock_email_class.return_value = MagicMock()
            totals = _run_wa_digest_batch(DigestBatchInput(org_ids=[str(self.organization.id)]))

        assert totals.orgs_processed == 1
        assert totals.emails_sent == 1
        assert totals.emails_skipped_optout == 1


class TestIsUserTargetedForDigest(APIBaseTest):
    def test_returns_true_when_flag_evaluates_true(self):
        with patch(
            "products.web_analytics.backend.temporal.weekly_digest.activities.posthoganalytics.feature_enabled",
            return_value=True,
        ) as mock_flag:
            assert _is_user_targeted_for_digest(self.user, str(self.organization.id)) is True

        kwargs = mock_flag.call_args.kwargs
        assert kwargs["only_evaluate_locally"] is False
        assert kwargs["groups"] == {"organization": str(self.organization.id)}
        assert kwargs["distinct_id"] == str(self.user.distinct_id)

    def test_returns_false_when_flag_evaluates_false(self):
        with patch(
            "products.web_analytics.backend.temporal.weekly_digest.activities.posthoganalytics.feature_enabled",
            return_value=False,
        ):
            assert _is_user_targeted_for_digest(self.user, str(self.organization.id)) is False

    def test_fails_closed_on_flag_service_error(self):
        with patch(
            "products.web_analytics.backend.temporal.weekly_digest.activities.posthoganalytics.feature_enabled",
            side_effect=RuntimeError("decide endpoint timeout"),
        ):
            assert _is_user_targeted_for_digest(self.user, str(self.organization.id)) is False

    def test_returns_false_when_flag_evaluator_returns_none(self):
        with patch(
            "products.web_analytics.backend.temporal.weekly_digest.activities.posthoganalytics.feature_enabled",
            return_value=None,
        ):
            assert _is_user_targeted_for_digest(self.user, str(self.organization.id)) is False
