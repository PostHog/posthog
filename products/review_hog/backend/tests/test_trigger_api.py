from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import override_settings

from parameterized import parameterized
from rest_framework import status

from posthog.models.integration import Integration
from posthog.models.organization import OrganizationMembership
from posthog.models.team import Team
from posthog.models.user import User

from products.review_hog.backend.models import ReviewInstallationClaim, ReviewReport, ReviewRepository

TRIGGER_URL = "/api/review_hog/trigger/"
RESOLVE_URL = "/api/review_hog/resolve/"
_START = "products.review_hog.backend.api.trigger.start_review_pr_workflow"
_START_RESOLUTION = "products.review_hog.backend.api.trigger.start_resolution_workflow"
_BUSY = "products.review_hog.backend.api.trigger.workflow_running"


@override_settings(REVIEWHOG_TRIGGER_TOKEN="secret-token")
class TestReviewHogTriggerApi(APIBaseTest):
    def setUp(self):
        super().setUp()
        # Let Postgres auto-assign IDs to avoid collisions with the sequence.
        self.trigger_team = Team.objects.create(organization=self.organization, name="reviewhog trigger")
        self.run_user = User.objects.create(email="run-user@posthog.com")
        OrganizationMembership.objects.create(organization=self.organization, user=self.run_user)
        self._settings_ctx = self.settings(
            REVIEWHOG_RUN_USER_ID=self.run_user.id, REVIEWHOG_TEAM_IDS=[self.trigger_team.id, self.team.id]
        )
        self._settings_ctx.enable()
        self._own(self.trigger_team, "PostHog/posthog", "PostHog/ai-gateway")
        # The busy-guard probes Temporal on every trigger; tests must never open real connections.
        busy_patcher = patch(_BUSY, return_value=False)
        self.mock_busy = busy_patcher.start()
        self.addCleanup(busy_patcher.stop)

    def tearDown(self):
        self._settings_ctx.disable()
        super().tearDown()

    def _own(self, team: Team, *full_names: str, created_by: User | None = None) -> None:
        """Make `team` the project that reviews these repositories of the PostHog installation."""
        Integration.objects.create(
            team=team,
            kind="github",
            integration_id="1001",
            config={"account": {"name": "PostHog"}},
            sensitive_config={},
            created_by=created_by,
        )
        ReviewInstallationClaim.objects.for_team(team.id).create(
            team=team, installation_id="1001", scope=ReviewInstallationClaim.Scope.SELECTED
        )
        for full_name in full_names:
            ReviewRepository.objects.for_team(team.id).create(
                team=team, installation_id="1001", full_name=full_name, selected=True
            )

    def _move_ownership_to_self_team(self, created_by: User) -> None:
        ReviewRepository.objects.for_team(self.trigger_team.id).delete()
        self._own(self.team, "PostHog/posthog", created_by=created_by)

    @patch(_START, return_value="wf-1")
    def test_valid_trigger_starts_workflow_and_publishes_by_default(self, mock_start):
        resp = self.client.post(
            TRIGGER_URL,
            {"repo": "PostHog/posthog", "pr_number": 123},
            format="json",
            HTTP_AUTHORIZATION="Bearer secret-token",
        )
        self.assertEqual(resp.status_code, status.HTTP_202_ACCEPTED, resp.content)
        self.assertEqual(resp.json(), {"workflow_id": "wf-1", "status": "started"})
        mock_start.assert_called_once_with(
            pr_url="https://github.com/PostHog/posthog/pull/123",
            team_id=self.trigger_team.id,
            user_id=self.run_user.id,
            publish=True,
            trigger_source="label",
        )

    @patch(_START, return_value="wf-1")
    def test_publish_flag_passes_through(self, mock_start):
        resp = self.client.post(
            TRIGGER_URL,
            {"repo": "PostHog/posthog", "pr_number": 5, "publish": False},
            format="json",
            HTTP_AUTHORIZATION="Bearer secret-token",
        )
        self.assertEqual(resp.status_code, status.HTTP_202_ACCEPTED, resp.content)
        self.assertEqual(mock_start.call_args.kwargs["publish"], False)

    @parameterized.expand(
        [
            ("wrong_token", "Bearer nope"),
            ("missing_header", ""),
            ("raw_wrong", "nope"),
        ]
    )
    @patch(_START, return_value="wf-1")
    def test_invalid_token_rejected(self, _name, auth_header, mock_start):
        resp = self.client.post(
            TRIGGER_URL,
            {"repo": "PostHog/posthog", "pr_number": 1},
            format="json",
            HTTP_AUTHORIZATION=auth_header,
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        mock_start.assert_not_called()

    @parameterized.expand(
        [
            ("other_account", "evil/repo"),
            ("owned_name_other_account", "evil/ai-gateway"),
            ("owned_name_prefix", "PostHog/ai-gateway-fork"),
            ("not_selected_anywhere", "PostHog/posthog-js"),
        ]
    )
    @patch(_START, return_value="wf-1")
    def test_repository_no_project_reviews_is_rejected(self, _name, repo, mock_start):
        resp = self.client.post(
            TRIGGER_URL,
            {"repo": repo, "pr_number": 1},
            format="json",
            HTTP_AUTHORIZATION="Bearer secret-token",
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        mock_start.assert_not_called()

    @patch(_START, return_value="wf-1")
    def test_owner_project_outside_dogfood_teams_is_rejected(self, mock_start):
        with override_settings(REVIEWHOG_TEAM_IDS=[self.team.id]):
            resp = self.client.post(
                TRIGGER_URL,
                {"repo": "PostHog/posthog", "pr_number": 1},
                format="json",
                HTTP_AUTHORIZATION="Bearer secret-token",
            )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        mock_start.assert_not_called()

    @parameterized.expand(
        [
            ("posthog_lowercase", "posthog/posthog"),
            ("ai_gateway", "PostHog/ai-gateway"),
            ("ai_gateway_lowercase", "posthog/ai-gateway"),
        ]
    )
    @patch(_START, return_value="wf-1")
    def test_owned_repository_accepted(self, _name, repo, mock_start):
        resp = self.client.post(
            TRIGGER_URL,
            {"repo": repo, "pr_number": 7},
            format="json",
            HTTP_AUTHORIZATION="Bearer secret-token",
        )
        self.assertEqual(resp.status_code, status.HTTP_202_ACCEPTED, resp.content)
        mock_start.assert_called_once()
        self.assertEqual(mock_start.call_args.kwargs["pr_url"], f"https://github.com/{repo}/pull/7")

    @patch(_START, return_value="wf-1")
    def test_the_owning_project_runs_the_review(self, mock_start):
        self._move_ownership_to_self_team(created_by=self.user)
        resp = self.client.post(
            TRIGGER_URL,
            {"repo": "PostHog/posthog", "pr_number": 1},
            format="json",
            HTTP_AUTHORIZATION="Bearer secret-token",
        )
        self.assertEqual(resp.status_code, status.HTTP_202_ACCEPTED, resp.content)
        self.assertEqual(mock_start.call_args.kwargs["team_id"], self.team.id)

    @override_settings(DEBUG=False, TEST=False, REVIEWHOG_TRIGGER_TOKEN=None)
    @patch(_START, return_value="wf-1")
    def test_unconfigured_token_fails_closed_in_production(self, mock_start):
        resp = self.client.post(
            TRIGGER_URL,
            {"repo": "PostHog/posthog", "pr_number": 1},
            format="json",
            HTTP_AUTHORIZATION="Bearer anything",
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        mock_start.assert_not_called()

    @override_settings(REVIEWHOG_RUN_USER_ID=None)
    @patch(_START, return_value="wf-1")
    def test_run_user_falls_back_to_integration_creator(self, mock_start):
        self._move_ownership_to_self_team(created_by=self.user)
        resp = self.client.post(
            TRIGGER_URL,
            {"repo": "PostHog/posthog", "pr_number": 1},
            format="json",
            HTTP_AUTHORIZATION="Bearer secret-token",
        )
        self.assertEqual(resp.status_code, status.HTTP_202_ACCEPTED, resp.content)
        self.assertEqual(mock_start.call_args.kwargs["user_id"], self.user.id)

    @parameterized.expand(
        [
            ("membership_removed", False),
            ("still_member_but_disabled", True),
        ]
    )
    @override_settings(REVIEWHOG_RUN_USER_ID=None)
    @patch(_START, return_value="wf-1")
    def test_inactive_integration_creator_falls_back_to_active_org_member(self, _name, keep_membership, mock_start):
        departed = User.objects.create(email="departed@posthog.com", is_active=False)
        if keep_membership:
            OrganizationMembership.objects.create(organization=self.organization, user=departed)
        self._move_ownership_to_self_team(created_by=departed)
        resp = self.client.post(
            TRIGGER_URL,
            {"repo": "PostHog/posthog", "pr_number": 1},
            format="json",
            HTTP_AUTHORIZATION="Bearer secret-token",
        )
        self.assertEqual(resp.status_code, status.HTTP_202_ACCEPTED, resp.content)
        self.assertEqual(mock_start.call_args.kwargs["user_id"], self.user.id)

    @patch(_START, return_value="wf-1")
    def test_trigger_refused_while_resolution_is_running(self, mock_start):
        # The busy-guard: a review started while the PR's resolve-pr workflow runs would race the
        # resolution session's pushes and re-review threads it is mid-way through settling. Temporal
        # can't dedupe across the two workflow ids, so a dropped (or wrong-id) probe here means
        # double runs — the check must hit resolve-pr's exact deterministic id and refuse.
        self.mock_busy.return_value = True
        resp = self.client.post(
            TRIGGER_URL,
            {"repo": "PostHog/posthog", "pr_number": 123},
            format="json",
            HTTP_AUTHORIZATION="Bearer secret-token",
        )
        self.assertEqual(resp.status_code, status.HTTP_409_CONFLICT)
        self.assertIn("Still resolving comments", resp.json()["error"])
        self.mock_busy.assert_called_once_with(f"resolve-pr:{self.trigger_team.id}:posthog/posthog:123")
        mock_start.assert_not_called()

    @patch(_START, return_value="wf-1")
    def test_label_during_a_running_cheaper_review_lifts_the_tier_and_says_so(self, mock_start):
        # A same-id start joins the in-flight turn, so the label's trigger source never reaches the
        # fetch upsert: without this lift the cheap turn publishes, the full review the label asked
        # for never runs, and the Action reports success.
        report = ReviewReport.objects.for_team(self.trigger_team.id).create(
            team=self.trigger_team,
            repository="posthog/posthog",
            pr_number=123,
            pr_url="https://github.com/PostHog/posthog/pull/123",
            head_branch="fix",
            base_branch="master",
            review_tier="agent_p3_p4",
            review_reasoning_effort="low",
        )
        self.mock_busy.side_effect = lambda workflow_id: workflow_id.startswith("review-pr:")
        resp = self.client.post(
            TRIGGER_URL,
            {"repo": "PostHog/posthog", "pr_number": 123},
            format="json",
            HTTP_AUTHORIZATION="Bearer secret-token",
        )
        self.assertEqual(resp.status_code, status.HTTP_202_ACCEPTED, resp.content)
        self.assertEqual(resp.json(), {"workflow_id": "wf-1", "status": "joined_running_review"})
        mock_start.assert_called_once()
        report.refresh_from_db()
        self.assertEqual((report.review_tier, report.review_reasoning_effort), ("human", "xhigh"))

    @patch(_START_RESOLUTION, return_value="wf-r-1")
    def test_resolve_refused_while_review_is_running(self, mock_start_resolution):
        # The other direction: a standalone resolution during a live review would settle threads
        # the finishing review is about to chain its own resolution for.
        self.mock_busy.return_value = True
        resp = self.client.post(
            RESOLVE_URL,
            {"repo": "PostHog/posthog", "pr_number": 123},
            format="json",
            HTTP_AUTHORIZATION="Bearer secret-token",
        )
        self.assertEqual(resp.status_code, status.HTTP_409_CONFLICT)
        self.assertIn("review is already running", resp.json()["error"])
        self.mock_busy.assert_called_once_with(f"review-pr:{self.trigger_team.id}:posthog/posthog:123")
        mock_start_resolution.assert_not_called()

    @parameterized.expand(
        [
            ("deactivated", True),
            ("active_but_not_org_member", False),
        ]
    )
    @patch(_START, return_value="wf-1")
    def test_configured_run_user_applies_only_where_it_is_an_active_member(self, _name, deactivate, mock_start):
        if deactivate:
            User.objects.filter(id=self.run_user.id).update(is_active=False)
        else:
            OrganizationMembership.objects.filter(user_id=self.run_user.id).delete()
        resp = self.client.post(
            TRIGGER_URL,
            {"repo": "PostHog/posthog", "pr_number": 1},
            format="json",
            HTTP_AUTHORIZATION="Bearer secret-token",
        )
        self.assertEqual(resp.status_code, status.HTTP_202_ACCEPTED, resp.content)
        self.assertEqual(mock_start.call_args.kwargs["user_id"], self.user.id)
