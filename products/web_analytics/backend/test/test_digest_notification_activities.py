import uuid

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.clickhouse.client.execute import KillSwitchLevel
from posthog.models import OrganizationMembership, Team, User
from posthog.models.organization import Organization

from products.notifications.backend.facade.api import NotificationType, TargetType
from products.web_analytics.backend.temporal.digest_notification.activities import (
    _build_and_send_for_org,
    _expose_and_notify_user,
    _get_org_batch_page,
    _run_wa_digest_notification_batch,
    _send_test_digest_notification,
)
from products.web_analytics.backend.temporal.digest_notification.types import (
    DigestBatchInput,
    NotificationDigestOutcome,
    OrgBatchPageInput,
    OrgDigestNotificationCounts,
    WADigestNotificationInput,
)

ACTIVITIES = "products.web_analytics.backend.temporal.digest_notification.activities"


def _make_team_digest(team, visitors=10, pageviews=100):
    return {
        "team": team,
        "visitors": {
            "current": visitors,
            "previous": 5,
            "change": {"percent": 50, "direction": "Up", "color": "#2f7d4f"},
        },
        "pageviews": {"current": pageviews, "previous": 50, "change": None},
        "sessions": {"current": 0, "previous": None, "change": None},
        "bounce_rate": {"current": 0.0, "previous": None, "change": None},
        "avg_session_duration": {"current": "0s", "previous": "0s", "change": None},
        "top_pages": [{"path": "/pricing", "visitors": visitors, "change": None}],
        "top_sources": [{"name": "google.com", "visitors": visitors, "change": None}],
        "goals": [],
        "dashboard_url": "https://example.com/project/1/web",
    }


def _make_notification_event():
    event = MagicMock()
    event.id = uuid.uuid4()
    return event


class _DigestNotificationTestBase(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.close_conn_patcher = patch(f"{ACTIVITIES}.close_old_connections")
        self.close_conn_patcher.start()

        self.feature_enabled_patcher = patch(f"{ACTIVITIES}.posthoganalytics.feature_enabled", return_value=True)
        self.mock_feature_enabled = self.feature_enabled_patcher.start()

        self.get_flag_patcher = patch(f"{ACTIVITIES}.posthoganalytics.get_feature_flag", return_value="test")
        self.mock_get_flag = self.get_flag_patcher.start()

        self.create_notification_patcher = patch(
            f"{ACTIVITIES}.create_notification", return_value=_make_notification_event()
        )
        self.mock_create_notification = self.create_notification_patcher.start()

        self.build_digest_patcher = patch(
            f"{ACTIVITIES}.build_team_digest",
            side_effect=lambda team: _make_team_digest(team),
        )
        self.mock_build_digest = self.build_digest_patcher.start()

        self.capture_patcher = patch(f"{ACTIVITIES}.ph_scoped_capture")
        self.mock_ph_scoped_capture = self.capture_patcher.start()
        self.mock_capture = MagicMock()
        self.mock_ph_scoped_capture.return_value.__enter__.return_value = self.mock_capture

    def tearDown(self):
        self.capture_patcher.stop()
        self.build_digest_patcher.stop()
        self.create_notification_patcher.stop()
        self.get_flag_patcher.stop()
        self.feature_enabled_patcher.stop()
        self.close_conn_patcher.stop()
        super().tearDown()


class TestBuildAndSendForOrg(_DigestNotificationTestBase):
    def test_test_arm_sends_notification_for_busiest_team(self):
        counts = _build_and_send_for_org(str(self.organization.id), flag_key="my-flag")

        assert counts.skipped_reason is None
        assert counts.sent == 1
        assert counts.control == 0

        self.mock_create_notification.assert_called_once()
        data = self.mock_create_notification.call_args.args[0]
        assert data.notification_type == NotificationType.WEB_ANALYTICS_DIGEST
        assert data.target_type == TargetType.USER
        assert data.target_id == str(self.user.id)
        assert data.team_id == self.team.id
        assert data.resource_type == "web_analytics"
        assert "utm_source=web_analytics_digest" in data.source_url

    def test_test_arm_records_exposure_and_captures_sent_event(self):
        _build_and_send_for_org(str(self.organization.id), flag_key="my-flag")

        self.mock_get_flag.assert_called_once()
        flag_kwargs = self.mock_get_flag.call_args.kwargs
        assert flag_kwargs["send_feature_flag_events"] is True
        assert flag_kwargs["groups"] == {"organization": str(self.organization.id)}

        self.mock_capture.assert_called_once()
        capture_kwargs = self.mock_capture.call_args.kwargs
        assert capture_kwargs["event"] == "web_analytics_digest_notification_sent"
        assert capture_kwargs["distinct_id"] == str(self.user.distinct_id)
        assert capture_kwargs["properties"]["variant"] == "test"
        assert capture_kwargs["properties"]["team_id"] == self.team.id

    def test_control_arm_records_exposure_but_sends_no_notification(self):
        self.mock_get_flag.return_value = "control"

        counts = _build_and_send_for_org(str(self.organization.id), flag_key="my-flag")

        assert counts.control == 1
        assert counts.sent == 0
        self.mock_get_flag.assert_called_once()
        assert self.mock_get_flag.call_args.kwargs["send_feature_flag_events"] is True
        self.mock_create_notification.assert_not_called()

    def test_org_without_realtime_notifications_is_skipped(self):
        self.mock_feature_enabled.return_value = False

        counts = _build_and_send_for_org(str(self.organization.id), flag_key="my-flag")

        assert counts.skipped_reason == "notifications_not_enabled"
        self.mock_get_flag.assert_not_called()
        self.mock_create_notification.assert_not_called()

    def test_org_with_no_wa_data_is_skipped(self):
        self.mock_build_digest.side_effect = lambda team: _make_team_digest(team, visitors=0)

        counts = _build_and_send_for_org(str(self.organization.id), flag_key="my-flag")

        assert counts.skipped_reason == "no_wa_data"
        self.mock_create_notification.assert_not_called()

    def test_busiest_team_is_selected_when_user_has_multiple(self):
        team_b = Team.objects.create(organization=self.organization, name="Team B")

        def digest_by_team(team):
            visitors = 500 if team.id == team_b.id else 10
            return _make_team_digest(team, visitors=visitors)

        self.mock_build_digest.side_effect = digest_by_team

        counts = _build_and_send_for_org(str(self.organization.id), flag_key="my-flag")

        assert counts.sent == 1
        data = self.mock_create_notification.call_args.args[0]
        assert data.team_id == team_b.id

    def test_per_user_failure_is_isolated_and_counted(self):
        second_user = User.objects.create_user(email="second@example.com", password="x", first_name="Second")
        OrganizationMembership.objects.create(
            organization=self.organization, user=second_user, level=OrganizationMembership.Level.MEMBER
        )

        self.mock_create_notification.side_effect = [
            RuntimeError("notification backend exploded"),
            _make_notification_event(),
        ]

        counts = _build_and_send_for_org(str(self.organization.id), flag_key="my-flag")

        assert counts.failed == 1
        assert counts.sent == 1
        assert self.mock_create_notification.call_count == 2

    def test_deactivated_users_are_excluded_from_fan_out(self):
        deactivated_user = User.objects.create_user(
            email="deactivated@example.com", password="x", first_name="Gone", is_active=False
        )
        OrganizationMembership.objects.create(
            organization=self.organization, user=deactivated_user, level=OrganizationMembership.Level.MEMBER
        )

        counts = _build_and_send_for_org(str(self.organization.id), flag_key="my-flag")

        assert counts.sent == 1
        self.mock_create_notification.assert_called_once()
        self.mock_get_flag.assert_called_once()

    def test_capture_failure_does_not_change_sent_outcome(self):
        self.mock_ph_scoped_capture.side_effect = RuntimeError("capture pipeline down")

        counts = _build_and_send_for_org(str(self.organization.id), flag_key="my-flag")

        assert counts.sent == 1
        assert counts.failed == 0
        self.mock_create_notification.assert_called_once()

    def test_dry_run_records_exposure_but_does_not_send(self):
        counts = _build_and_send_for_org(str(self.organization.id), flag_key="my-flag", dry_run=True)

        assert counts.sent == 1
        self.mock_get_flag.assert_called_once()
        self.mock_create_notification.assert_not_called()
        self.mock_capture.assert_not_called()

    @parameterized.expand(
        [
            ("variant_none", None),
            ("variant_control", "control"),
        ]
    )
    def test_non_test_variants_do_not_send(self, _name, variant):
        self.mock_get_flag.return_value = variant

        counts = _build_and_send_for_org(str(self.organization.id), flag_key="my-flag")

        assert counts.sent == 0
        self.mock_create_notification.assert_not_called()

    def test_create_notification_returning_none_yields_skipped_no_data(self):
        self.mock_create_notification.return_value = None

        counts = _build_and_send_for_org(str(self.organization.id), flag_key="my-flag")

        assert counts.sent == 0
        assert counts.skipped_no_data == 1
        self.mock_capture.assert_not_called()

    def test_org_not_found_returns_skipped_reason(self):
        counts = _build_and_send_for_org(str(uuid.uuid4()), flag_key="my-flag")

        assert counts.skipped_reason == "org_not_found"
        self.mock_create_notification.assert_not_called()

    def test_org_gate_failing_flag_eval_treats_org_as_disabled(self):
        self.mock_feature_enabled.side_effect = RuntimeError("flag service down")

        counts = _build_and_send_for_org(str(self.organization.id), flag_key="my-flag")

        assert counts.skipped_reason == "notifications_not_enabled"
        self.mock_create_notification.assert_not_called()


class TestExposeAndNotifyUser(_DigestNotificationTestBase):
    def test_user_without_accessible_data_is_not_exposed(self):
        outcome = _expose_and_notify_user(
            user=self.user,
            org=self.organization,
            membership=self.organization_membership,
            team_digest_data={},
            flag_key="my-flag",
            dry_run=False,
        )

        assert outcome == NotificationDigestOutcome.SKIPPED_NO_DATA
        self.mock_get_flag.assert_not_called()
        self.mock_create_notification.assert_not_called()

    def test_test_arm_user_with_data_is_exposed_and_sent(self):
        outcome = _expose_and_notify_user(
            user=self.user,
            org=self.organization,
            membership=self.organization_membership,
            team_digest_data={self.team.id: _make_team_digest(self.team)},
            flag_key="my-flag",
            dry_run=False,
        )

        assert outcome == NotificationDigestOutcome.SENT
        self.mock_get_flag.assert_called_once()
        self.mock_create_notification.assert_called_once()

    def test_control_arm_user_is_exposed_but_not_sent(self):
        self.mock_get_flag.return_value = "control"

        outcome = _expose_and_notify_user(
            user=self.user,
            org=self.organization,
            membership=self.organization_membership,
            team_digest_data={self.team.id: _make_team_digest(self.team)},
            flag_key="my-flag",
            dry_run=False,
        )

        assert outcome == NotificationDigestOutcome.CONTROL
        self.mock_get_flag.assert_called_once()
        self.mock_create_notification.assert_not_called()


class TestRunWaDigestNotificationBatch(_DigestNotificationTestBase):
    def test_aggregates_per_org_results(self):
        results_by_org = {
            "1": OrgDigestNotificationCounts(sent=3, control=2, build_duration=0.4, send_duration=0.2),
            "2": OrgDigestNotificationCounts(skipped_no_data=4, failed=1, build_duration=0.1),
            "3": OrgDigestNotificationCounts(skipped_reason="no_teams"),
        }

        with patch(
            f"{ACTIVITIES}._build_and_send_for_org",
            side_effect=lambda org_id, flag_key, dry_run: results_by_org[org_id],
        ):
            totals = _run_wa_digest_notification_batch(DigestBatchInput(org_ids=["1", "2", "3"]))

        assert totals.batch_size == 3
        assert totals.orgs_processed == 2
        assert totals.orgs_skipped == 1
        assert totals.orgs_failed == 0
        assert totals.notifications_sent == 3
        assert totals.control_exposed == 2
        assert totals.skipped_no_data == 4
        assert totals.failed == 1

    def test_isolates_per_org_failures(self):
        def fake_build_and_send(org_id, flag_key, dry_run):
            if org_id == "2":
                raise RuntimeError("clickhouse exploded for org 2")
            return OrgDigestNotificationCounts(sent=1, control=1)

        with patch(f"{ACTIVITIES}._build_and_send_for_org", side_effect=fake_build_and_send):
            totals = _run_wa_digest_notification_batch(DigestBatchInput(org_ids=["1", "2", "3"]))

        assert totals.orgs_processed == 2
        assert totals.orgs_failed == 1
        assert totals.notifications_sent == 2
        assert totals.control_exposed == 2

    def test_passes_flag_key_and_dry_run_through(self):
        captured: list[tuple[str, str, bool]] = []

        def fake_build_and_send(org_id, flag_key, dry_run):
            captured.append((org_id, flag_key, dry_run))
            return OrgDigestNotificationCounts(sent=1)

        with patch(f"{ACTIVITIES}._build_and_send_for_org", side_effect=fake_build_and_send):
            _run_wa_digest_notification_batch(DigestBatchInput(org_ids=["1"], flag_key="custom-flag", dry_run=True))

        assert captured == [("1", "custom-flag", True)]

    def test_aggregates_via_real_build_and_send(self):
        control_user = User.objects.create_user(email="control@example.com", password="x", first_name="Ctrl")
        OrganizationMembership.objects.create(
            organization=self.organization, user=control_user, level=OrganizationMembership.Level.MEMBER
        )

        def variant_by_user(flag_key, distinct_id, **kwargs):
            return "control" if distinct_id == str(control_user.distinct_id) else "test"

        self.mock_get_flag.side_effect = variant_by_user

        totals = _run_wa_digest_notification_batch(DigestBatchInput(org_ids=[str(self.organization.id)]))

        assert totals.orgs_processed == 1
        assert totals.notifications_sent == 1
        assert totals.control_exposed == 1


class TestGetOrgBatchPage(_DigestNotificationTestBase):
    def setUp(self):
        super().setUp()
        self.kill_switch_patcher = patch(f"{ACTIVITIES}.get_kill_switch_level", return_value=KillSwitchLevel.OFF)
        self.mock_kill_switch = self.kill_switch_patcher.start()

    def tearDown(self):
        self.kill_switch_patcher.stop()
        super().tearDown()

    def test_returns_empty_when_kill_switch_active(self):
        self.mock_kill_switch.return_value = KillSwitchLevel.LIGHT

        page = _get_org_batch_page(OrgBatchPageInput(workflow_input=WADigestNotificationInput()))

        assert page.batches == []
        assert page.cursor is None

    def test_keyset_pagination_pages_through_orgs(self):
        orgs = [self.organization]
        orgs.extend(Organization.objects.create(name=f"Org {i}") for i in range(4))
        expected_ids = sorted(str(org.id) for org in orgs)

        first_page = _get_org_batch_page(
            OrgBatchPageInput(workflow_input=WADigestNotificationInput(batch_size=2), page_size=2)
        )
        assert [oid for batch in first_page.batches for oid in batch] == expected_ids[:2]
        assert first_page.cursor == expected_ids[1]

        final_ids: list[str] = []
        cursor: str | None = first_page.cursor
        while cursor is not None:
            page = _get_org_batch_page(
                OrgBatchPageInput(workflow_input=WADigestNotificationInput(batch_size=2), cursor=cursor, page_size=2)
            )
            final_ids.extend(oid for batch in page.batches for oid in batch)
            cursor = page.cursor

        assert expected_ids[:2] + final_ids == expected_ids

    def test_configured_org_ids_paginate_by_index(self):
        override = ["1111", "2222", "3333"]

        first_page = _get_org_batch_page(
            OrgBatchPageInput(workflow_input=WADigestNotificationInput(org_ids=override, batch_size=2), page_size=2)
        )
        assert [oid for batch in first_page.batches for oid in batch] == ["1111", "2222"]
        assert first_page.cursor == "2"

        second_page = _get_org_batch_page(
            OrgBatchPageInput(
                workflow_input=WADigestNotificationInput(org_ids=override, batch_size=2),
                cursor=first_page.cursor,
                page_size=2,
            )
        )
        assert [oid for batch in second_page.batches for oid in batch] == ["3333"]
        assert second_page.cursor is None


class TestSendTestDigestNotification(_DigestNotificationTestBase):
    def test_single_team_mode_sends_to_user_with_access(self):
        _send_test_digest_notification(email=self.user.email, team_id=self.team.id)

        self.mock_create_notification.assert_called_once()
        data = self.mock_create_notification.call_args.args[0]
        assert data.target_id == str(self.user.id)
        assert data.team_id == self.team.id

    def test_single_team_mode_bypasses_holdout_flag(self):
        _send_test_digest_notification(email=self.user.email, team_id=self.team.id)

        self.mock_get_flag.assert_not_called()

    def test_single_team_email_lookup_is_case_insensitive(self):
        _send_test_digest_notification(email=self.user.email.upper(), team_id=self.team.id)

        self.mock_create_notification.assert_called_once()

    def test_raises_when_email_has_no_user(self):
        with self.assertRaises(ValueError) as cm:
            _send_test_digest_notification(email="nobody@example.com", team_id=self.team.id)
        assert "No active user found" in str(cm.exception)
        self.mock_create_notification.assert_not_called()

    def test_raises_when_team_not_found(self):
        with self.assertRaises(ValueError) as cm:
            _send_test_digest_notification(email=self.user.email, team_id=999_999)
        assert "Team 999999 not found" in str(cm.exception)
        self.mock_create_notification.assert_not_called()

    def test_raises_when_user_not_in_teams_org(self):
        other_org = Organization.objects.create(name="Other org")
        other_team = Team.objects.create(organization=other_org, name="Other team")
        with self.assertRaises(PermissionError) as cm:
            _send_test_digest_notification(email=self.user.email, team_id=other_team.id)
        assert "is not a member of the organization" in str(cm.exception)
        self.mock_create_notification.assert_not_called()

    def test_raises_when_delivery_not_completed(self):
        self.mock_create_notification.return_value = None
        with self.assertRaises(RuntimeError) as cm:
            _send_test_digest_notification(email=self.user.email, team_id=self.team.id)
        assert "not delivered" in str(cm.exception)

    def test_full_user_mode_sends_one_notification_per_org(self):
        other_org = Organization.objects.create(name="Other org")
        Team.objects.create(organization=other_org, name="Other team")
        OrganizationMembership.objects.create(
            organization=other_org, user=self.user, level=OrganizationMembership.Level.MEMBER
        )

        self.mock_create_notification.side_effect = lambda data: _make_notification_event()

        _send_test_digest_notification(email=self.user.email)

        assert self.mock_create_notification.call_count == 2

    def test_full_user_mode_raises_when_no_memberships(self):
        self.organization_membership.delete()
        with self.assertRaises(ValueError) as cm:
            _send_test_digest_notification(email=self.user.email)
        assert "no organization memberships" in str(cm.exception)
        self.mock_create_notification.assert_not_called()

    def test_full_user_mode_raises_when_nothing_delivered(self):
        self.mock_create_notification.return_value = None
        with self.assertRaises(RuntimeError) as cm:
            _send_test_digest_notification(email=self.user.email)
        assert "No test digest notifications delivered" in str(cm.exception)
