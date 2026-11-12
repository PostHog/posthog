from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import TestCase

from parameterized import parameterized

from posthog.llm.system_one import NoulAnswer, SystemOneRequestFailed, SystemOneResult
from posthog.models.integration import Integration
from posthog.models.organization import Organization
from posthog.models.team.team import Team
from posthog.models.user import User

from products.slack_app.backend.services.slack_messages import SlackThreadMessage
from products.slack_app.backend.temporal import (
    PostHogCodeSlackMentionWorkflowInputs,
    cascade_posthog_code_repository_activity,
)
from products.slack_app.backend.temporal.activities.classifiers import NEEDS_REPO_QUESTION_ID


def _make_inputs(
    integration_id: int, user_id: int, slack_team_id: str = "T_SLACK"
) -> PostHogCodeSlackMentionWorkflowInputs:
    return PostHogCodeSlackMentionWorkflowInputs(
        event={"channel": "C123", "ts": "1234.5678", "user": "U_ALICE", "text": "<@BOT> fix the thing"},
        integration_id=integration_id,
        slack_team_id=slack_team_id,
        user_id=user_id,
    )


class TestCascadeTeamInstall(TestCase):
    def setUp(self):
        cache.clear()
        self.org = Organization.objects.create(name="TestOrg")
        self.team = Team.objects.create(organization=self.org, name="TestTeam")
        self.user = User.objects.create(email="alice@test.com")
        self.slack_integration = Integration.objects.create(
            team=self.team, kind="slack", integration_id="T_SLACK", config={}
        )

    @parameterized.expand(
        [
            ("with_team_install", True),
            ("without_team_install", False),
        ]
    )
    def test_a_team_install_contributes_no_repos(self, _name, has_team_install):
        # Repo resolution reads the mentioner's personal install only, so a workspace whose
        # team install covers the repo still resolves `no_repo` for a user without one.
        if has_team_install:
            Integration.objects.create(
                team=self.team,
                kind="github",
                integration_id="gh-team-1",
                config={"account": {"name": "posthog"}},
                sensitive_config={"access_token": "gh-team-token"},
            )

        outcome = cascade_posthog_code_repository_activity(
            _make_inputs(self.slack_integration.id, self.user.id), "fix the thing", self.user.id
        )

        assert outcome.mode == "no_repo"

    @patch("products.slack_app.backend.api.UserGitHubIntegration")
    def test_a_personal_install_resolves_its_single_repo(self, mock_user_github_class):
        from posthog.models.user_integration import UserIntegration

        UserIntegration.objects.create(
            user=self.user,
            kind=UserIntegration.IntegrationKind.GITHUB,
            integration_id="gh-user-1",
            config={},
            sensitive_config={"access_token": "gh-user-token"},
        )
        mock_user_github = MagicMock()
        mock_user_github.list_all_cached_repositories.return_value = [
            {"id": 1, "name": "posthog", "full_name": "posthog/posthog"}
        ]
        mock_user_github_class.return_value = mock_user_github

        outcome = cascade_posthog_code_repository_activity(
            _make_inputs(self.slack_integration.id, self.user.id), "fix the thing", self.user.id
        )

        assert outcome.mode == "auto"
        assert outcome.repository == "posthog/posthog"

    @parameterized.expand(
        [
            (
                "link_sits_in_the_thread_and_the_mention_carries_none",
                "<@BOT> is this one flaky?",
                [
                    {
                        "user": "amy",
                        "text": "https://github.com/posthog/posthog-js/actions/runs/2 failed again",
                        "ts": "1.000000",
                    },
                    {"user": "bo", "text": "<@BOT> is this one flaky?", "ts": "2.000000"},
                ],
                "auto",
                "posthog/posthog-js",
                "explicit_thread_mention",
            ),
            (
                "mention_names_a_repo_the_thread_did_not",
                "<@BOT> look at posthog/posthog instead",
                [
                    {
                        "user": "amy",
                        "text": "https://github.com/posthog/posthog-js/actions/runs/2 failed again",
                        "ts": "1.000000",
                    },
                    {"user": "bo", "text": "<@BOT> look at posthog/posthog instead", "ts": "2.000000"},
                ],
                "auto",
                "posthog/posthog",
                "explicit_mention",
            ),
            (
                "link_posted_after_the_mention_cannot_select_the_repo",
                "<@BOT> is this one flaky?",
                [
                    {"user": "bo", "text": "<@BOT> is this one flaky?", "ts": "2.000000"},
                    {
                        "user": "mallory",
                        "text": "https://github.com/posthog/posthog-js/actions/runs/2",
                        "ts": "3.000000",
                    },
                ],
                "agent_needed",
                None,
                "needs_agent",
            ),
        ]
    )
    @patch("products.slack_app.backend.api.UserGitHubIntegration")
    def test_thread_evidence_counts_only_up_to_the_mention(
        self,
        _name,
        event_text,
        thread_messages,
        expected_mode,
        expected_repository,
        expected_reason,
        mock_user_github_class,
    ):
        from posthog.models.user_integration import UserIntegration

        UserIntegration.objects.create(
            user=self.user,
            kind=UserIntegration.IntegrationKind.GITHUB,
            integration_id="gh-user-1",
            config={},
            sensitive_config={"access_token": "gh-user-token"},
        )
        mock_user_github = MagicMock()
        mock_user_github.list_all_cached_repositories.return_value = [
            {"id": 1, "name": "posthog", "full_name": "posthog/posthog"},
            {"id": 2, "name": "posthog-js", "full_name": "posthog/posthog-js"},
        ]
        mock_user_github_class.return_value = mock_user_github

        with patch("products.slack_app.backend.analytics.ph_background_capture") as mock_capture_factory:
            outcome = cascade_posthog_code_repository_activity(
                _make_inputs(self.slack_integration.id, self.user.id),
                event_text,
                self.user.id,
                [SlackThreadMessage(**message) for message in thread_messages],
                "2.000000",
            )

        assert outcome.mode == expected_mode
        assert outcome.repository == expected_repository
        assert outcome.reason == expected_reason
        captured = [
            c.kwargs["properties"]
            for c in mock_capture_factory.return_value.call_args_list
            if c.kwargs["event"] == "slack app repository resolved"
        ]
        assert len(captured) == 1
        assert captured[0]["resolution"] == expected_reason
        assert captured[0]["has_repository"] is (expected_repository is not None)
        assert captured[0]["is_final"] is (expected_mode != "agent_needed")
        assert captured[0]["connected_repo_count"] == 2
        assert captured[0]["slack_session_id"] == "T_SLACK:C123:1234.5678"


ONE_REPO = [{"id": 1, "name": "posthog", "full_name": "posthog/posthog"}]
TWO_REPOS = [*ONE_REPO, {"id": 2, "name": "posthog-js", "full_name": "posthog/posthog-js"}]


def _jev_client(probability: float | None) -> MagicMock:
    client = MagicMock()
    if probability is None:
        client.decide.side_effect = SystemOneRequestFailed("gateway timeout")
    else:
        client.decide.return_value = SystemOneResult(
            model="jeeves", answers={NEEDS_REPO_QUESTION_ID: NoulAnswer(probability=probability)}, input_tokens=1
        )
    return client


class TestCascadeWithJevNeedsRepo(TestCase):
    def setUp(self):
        from posthog.models.user_integration import UserIntegration

        cache.clear()
        self.team = Team.objects.create(organization=Organization.objects.create(name="TestOrg"), name="TestTeam")
        self.user = User.objects.create(email="alice@test.com")
        self.slack_integration = Integration.objects.create(
            team=self.team, kind="slack", integration_id="T_SLACK", config={}
        )
        UserIntegration.objects.create(
            user=self.user,
            kind=UserIntegration.IntegrationKind.GITHUB,
            integration_id="gh-user-1",
            config={},
            sensitive_config={"access_token": "gh-user-token"},
        )

    @parameterized.expand(
        [
            ("no_code_needed_skips_the_single_repo", ONE_REPO, 0.1, "fix the thing", "no_repo", None),
            ("code_needed_uses_the_single_repo", ONE_REPO, 0.9, "fix the thing", "auto", "posthog/posthog"),
            (
                "code_needed_uses_the_named_repo",
                TWO_REPOS,
                0.9,
                "fix it in posthog/posthog-js",
                "auto",
                "posthog/posthog-js",
            ),
            ("code_needed_hands_off_to_discovery", TWO_REPOS, 0.9, "fix the thing", "agent_needed", None),
            ("failed_call_means_no_repo", ONE_REPO, None, "fix the thing", "no_repo", None),
        ]
    )
    @patch("products.slack_app.backend.temporal.activities.repo_selection.is_slack_app_jev_needs_repo_enabled")
    @patch("products.slack_app.backend.temporal.activities.classifiers.build_system_one_client")
    @patch("products.slack_app.backend.api.UserGitHubIntegration")
    def test_jev_decides_before_any_repository_is_picked(
        self,
        _name,
        repos,
        probability,
        event_text,
        expected_mode,
        expected_repository,
        mock_user_github_class,
        mock_build_client,
        mock_flag,
    ):
        mock_flag.return_value = True
        mock_user_github_class.return_value.list_all_cached_repositories.return_value = repos
        mock_build_client.return_value = _jev_client(probability)

        with patch("products.slack_app.backend.analytics.ph_background_capture") as mock_capture_factory:
            outcome = cascade_posthog_code_repository_activity(
                _make_inputs(self.slack_integration.id, self.user.id), event_text, self.user.id
            )

        assert outcome.mode == expected_mode
        assert outcome.repository == expected_repository
        assert outcome.needs_repo_classified is (expected_mode == "agent_needed")
        steps = [
            (c.kwargs["properties"]["resolution"], c.kwargs["properties"]["is_final"])
            for c in mock_capture_factory.return_value.call_args_list
            if c.kwargs["event"] == "slack app repository resolved"
        ]
        jev_step = {0.1: ("classifier_no_repo", True), None: ("classifier_failed", True)}.get(
            probability, ("classifier_needs_repo", False)
        )
        assert steps[0] == jev_step
        assert len(steps) == (1 if expected_mode == "no_repo" else 2)
        if expected_mode != "no_repo":
            assert steps[1] == (outcome.reason, expected_mode != "agent_needed")
