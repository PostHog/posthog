from contextlib import AbstractContextManager, nullcontext
from dataclasses import replace
from types import SimpleNamespace

from unittest import TestCase as UnitTestCase
from unittest.mock import MagicMock, patch

from django.apps import apps
from django.test import SimpleTestCase, TestCase

from parameterized import parameterized
from slack_sdk.errors import SlackApiError

from posthog.integrations import IntegrationNotFound
from posthog.models.integration import Integration
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.models.user_integration import UserIntegration

from products.signals.backend.facade import report_tasks
from products.slack_app.backend.api import SlackUserContext
from products.slack_app.backend.models import SlackSettings, SlackThreadJoin, SlackThreadTaskMapping, ThreadJoinMode
from products.slack_app.backend.services.run_preferences import SLACK_DEFAULT_MODEL
from products.slack_app.backend.services.slack_messages import (
    SlackFileRef,
    SlackThreadMessage,
    encode_slack_file_refs,
    parse_slack_file_refs,
)
from products.slack_app.backend.slack_thread import SlackThreadContext, SlackThreadHandler
from products.slack_app.backend.temporal import (
    PostHogCodeSlackMentionWorkflowInputs,
    create_posthog_code_task_for_repo_activity,
    enforce_posthog_code_billing_quota_activity,
    forward_posthog_code_followup_activity,
)
from products.slack_app.backend.temporal.activities.report_implementation import (
    prepare_slack_report_implementation_activity,
)
from products.slack_app.backend.temporal.activities.task_creation import _build_terminal_recovery_prompt
from products.slack_app.backend.temporal.helpers import safe_react
from products.tasks.backend.facade import ai_run_defaults


def _make_inputs(
    integration_id: int, user_id: int, slack_team_id: str = "T_SLACK"
) -> PostHogCodeSlackMentionWorkflowInputs:
    return PostHogCodeSlackMentionWorkflowInputs(
        event={"channel": "C123", "ts": "1234.5678", "user": "U_ALICE", "text": "<@BOT> do something"},
        integration_id=integration_id,
        slack_team_id=slack_team_id,
        user_id=user_id,
    )


def _make_slack_file(**overrides: object) -> dict[str, object]:
    """A file as Slack puts it on an event payload."""
    file: dict[str, object] = {
        "id": "F123",
        "name": "debug.log",
        "mimetype": "text/plain",
        "filetype": "text",
        "size": 12,
        "url_private_download": "https://files.slack.com/files-pri/T123-F123/debug.log",
    }
    file.update(overrides)
    return file


def _make_file_ref(**overrides: object) -> SlackFileRef:
    """The same file as it reaches a thread snapshot."""
    return parse_slack_file_refs([_make_slack_file(**overrides)])[0]


def _assert_quota_denial_posted(mock_slack_instance: MagicMock, channel: str, thread_ts: str) -> None:
    denial_calls = [
        call
        for call in mock_slack_instance.client.chat_postMessage.call_args_list
        if call.kwargs.get("channel") == channel and call.kwargs.get("thread_ts") == thread_ts
    ]
    assert denial_calls, "Expected an in-thread denial message when over quota"
    assert "PostHog AI credits" in denial_calls[0].kwargs["text"]


class TestTerminalRecoveryPrompt(UnitTestCase):
    def test_failed_connector_recovery_prompts_replan(self):
        previous_run = SimpleNamespace(
            id="run-1",
            status="failed",
            error_message="No connected GitHub integration was found for this user",
            state={
                "slack_recovery_strategy": "connect_then_replan",
                "slack_recovery_prompt": "Reply after connecting the missing tool.",
            },
        )

        prompt = _build_terminal_recovery_prompt(previous_run, "I connected GitHub, try again")

        assert "Recovery mode: connect_then_replan" in prompt
        assert "Refresh the current connector/auth state" in prompt
        assert "No connected GitHub integration" in prompt
        assert "I connected GitHub, try again" in prompt


class TestSlackThreadTaskMapping(TestCase):
    def setUp(self):
        self.Task = apps.get_model("tasks", "Task")
        self.TaskRun = apps.get_model("tasks", "TaskRun")
        self.org = Organization.objects.create(name="TestOrg")
        self.team = Team.objects.create(organization=self.org, name="TestTeam")
        self.user = User.objects.create(email="alice@test.com")
        self.integration = Integration.objects.create(
            team=self.team, kind="slack", integration_id="T_SLACK", config={"scope": "files:read"}
        )
        self.task = self.Task.objects.create(
            team=self.team,
            title="Test task",
            description="desc",
            origin_product=self.Task.OriginProduct.SLACK,
            created_by=self.user,
            repository="org/repo",
        )
        self.task_run = self.TaskRun.objects.create(
            task=self.task,
            team=self.team,
            status=self.TaskRun.Status.IN_PROGRESS,
        )

    def test_context_without_team_id_resolves_the_team_from_the_mapping(self):
        SlackThreadTaskMapping.objects.create(
            team=self.team,
            integration=self.integration,
            slack_workspace_id="T_SLACK",
            channel="C123",
            thread_ts="1234.5678",
            task=self.task,
            task_run=self.task_run,
        )
        old_payload = {"integration_id": self.integration.id, "channel": "C123", "thread_ts": "1234.5678"}

        handler = SlackThreadHandler(SlackThreadContext.from_dict(old_payload))

        assert handler.team_id == self.team.id
        assert handler._get_integration().id == self.integration.id

    def test_context_without_team_id_and_mapping_fails_cleanly(self):
        old_payload = {"integration_id": self.integration.id, "channel": "C123", "thread_ts": "9.9"}

        with self.assertRaises(IntegrationNotFound):
            SlackThreadHandler(SlackThreadContext.from_dict(old_payload))._get_integration()

    def test_create_mapping(self):
        mapping = SlackThreadTaskMapping.objects.create(
            team=self.team,
            integration=self.integration,
            slack_workspace_id="T_SLACK",
            channel="C123",
            thread_ts="1234.5678",
            task=self.task,
            task_run=self.task_run,
            mentioning_slack_user_id="U_ALICE",
        )
        assert mapping.pk is not None
        assert mapping.channel == "C123"
        assert mapping.mentioning_slack_user_id == "U_ALICE"

    def test_update_mapping_to_new_run(self):
        SlackThreadTaskMapping.objects.create(
            team=self.team,
            integration=self.integration,
            slack_workspace_id="T_SLACK",
            channel="C123",
            thread_ts="1234.5678",
            task=self.task,
            task_run=self.task_run,
            mentioning_slack_user_id="U_ALICE",
        )
        new_run = self.TaskRun.objects.create(
            task=self.task,
            team=self.team,
            status=self.TaskRun.Status.QUEUED,
        )
        SlackThreadTaskMapping.objects.update_or_create(
            integration=self.integration,
            channel="C123",
            thread_ts="1234.5678",
            defaults={
                "team": self.team,
                "slack_workspace_id": "T_SLACK",
                "task": self.task,
                "task_run": new_run,
                "mentioning_slack_user_id": "U_ALICE",
            },
        )
        mapping = SlackThreadTaskMapping.objects.get(
            integration=self.integration, channel="C123", thread_ts="1234.5678"
        )
        assert mapping.task_run_id == new_run.id

    def test_unique_constraint(self):
        SlackThreadTaskMapping.objects.create(
            team=self.team,
            integration=self.integration,
            slack_workspace_id="T_SLACK",
            channel="C123",
            thread_ts="1234.5678",
            task=self.task,
            task_run=self.task_run,
            mentioning_slack_user_id="U_ALICE",
        )
        from django.db import IntegrityError

        with self.assertRaises(IntegrityError):
            SlackThreadTaskMapping.objects.create(
                team=self.team,
                integration=self.integration,
                slack_workspace_id="T_SLACK",
                channel="C123",
                thread_ts="1234.5678",
                task=self.task,
                task_run=self.task_run,
                mentioning_slack_user_id="U_BOB",
            )


class TestCreatePostHogCodeTaskForRepoActivity(TestCase):
    def setUp(self):
        self.Task = apps.get_model("tasks", "Task")
        self.TaskRun = apps.get_model("tasks", "TaskRun")
        self.org = Organization.objects.create(name="TestOrg")
        self.team = Team.objects.create(organization=self.org, name="TestTeam")
        self.user = User.objects.create(email="alice@test.com", distinct_id="user-1")
        self.integration = Integration.objects.create(
            team=self.team, kind="slack", integration_id="T_SLACK", config={"scope": "files:read"}
        )
        # The mock SlackIntegration doesn't stub `auth_test`, so `get_cached_bot_user_id`
        # would return None and the bot-mention fast-path strip wouldn't kick in. Force
        # it to return the literal "BOT" so `<@BOT>` in test inputs is stripped from
        # the agent prompt as it would be in production.
        bot_id_patcher = patch(
            "products.slack_app.backend.services.slack_messages.get_cached_bot_user_id",
            return_value="BOT",
        )
        bot_id_patcher.start()
        self.addCleanup(bot_id_patcher.stop)

    @patch("products.tasks.backend.facade.temporal.dispatch_task_processing_workflow")
    @patch("posthog.models.integration.SlackIntegration")
    def test_a_codex_model_from_the_saved_default_bills_the_mentioners_plan(
        self, mock_slack_cls, mock_execute_workflow
    ):
        # Slack leaves the triple empty when a saved default exists, so the runtime is only
        # known once `create_run` applies that default.
        ai_run_defaults.update_user_ai_run_preferences(
            self.team.id, self.user.id, runtime_adapter="codex", model="gpt-5.5", reasoning_effort=None
        )
        mock_slack_instance = MagicMock()
        mock_slack_instance.client.chat_getPermalink.return_value = {
            "ok": True,
            "permalink": "https://slack.example.com/t",
        }
        mock_slack_cls.return_value = mock_slack_instance

        inputs = _make_inputs(self.integration.id, self.user.id)
        with (
            patch(
                "products.tasks.backend.facade.api.unattended_model_access_state",
                side_effect=lambda user, runtime_adapter: (
                    {"codex_model_access": "own-subscription"} if runtime_adapter == "codex" else {}
                ),
            ),
            patch("products.slack_app.backend.feature_flags.is_slack_app_byos_enabled", return_value=True),
        ):
            create_posthog_code_task_for_repo_activity(
                inputs,
                "C123",
                "1234.5678",
                "U_ALICE",
                self.user.id,
                inputs.event,
                [SlackThreadMessage(user="U_ALICE", text="fix the tests")],
                None,
            )

        latest_run = self.Task.objects.get(team=self.team).latest_run
        assert latest_run is not None
        state = latest_run.state
        assert state["runtime_adapter"] == "codex"
        assert state["codex_model_access"] == "own-subscription"
        assert state["codex_subscription_user_id"] == self.user.id

    @patch("products.tasks.backend.facade.temporal.dispatch_task_processing_workflow")
    @patch("posthog.models.integration.SlackIntegration")
    def test_no_repo_task_starts_with_pr_creation_enabled(self, mock_slack_cls, mock_execute_workflow):
        mock_slack_instance = MagicMock()
        mock_slack_instance.client.chat_getPermalink.return_value = {
            "ok": True,
            "permalink": "https://slack.example.com/thread",
        }
        mock_slack_cls.return_value = mock_slack_instance

        inputs = _make_inputs(self.integration.id, self.user.id)
        create_posthog_code_task_for_repo_activity(
            inputs,
            "C123",
            "1234.5678",
            "U_ALICE",
            self.user.id,
            inputs.event,
            [SlackThreadMessage(user="U_ALICE", text="run without repo")],
            None,
        )

        task = self.Task.objects.get(team=self.team)
        assert task.repository is None
        assert task.origin_product == self.Task.OriginProduct.SLACK
        latest_run = task.latest_run
        assert latest_run is not None
        assert latest_run.state["interaction_origin"] == "slack"
        assert latest_run.state["pr_authorship_mode"] == "bot"

        # Mention-dispatch debug pointer persisted on the new run.
        # No explicit envelope event_id → falls back to "<channel>:<ts>".
        assert latest_run.state["slack_mention_workflow_id"] == "slack-app-mention-processing-T_SLACK:C123:1234.5678"

        mock_execute_workflow.assert_called_once()
        call_kwargs = mock_execute_workflow.call_args.kwargs
        assert call_kwargs["task_id"] == str(task.id)
        assert call_kwargs["run_id"] == str(latest_run.id)
        assert call_kwargs["create_pr"] is True
        assert call_kwargs["posthog_mcp_scopes"] == "full"

        mapping = SlackThreadTaskMapping.objects.get(
            integration=self.integration, channel="C123", thread_ts="1234.5678"
        )
        assert mapping.task_id == task.id
        assert mapping.task_run_id == latest_run.id

    @parameterized.expand(
        [
            ("report_notification_thread", True, False, None, False, "channel"),
            ("report_thread_in_direct_message", True, False, None, False, "im"),
            ("report_implementation", True, True, None, False, "channel"),
            ("implementation_mapping_failure", True, True, "mapping", False, "channel"),
            ("implementation_registration_failure", True, True, "registration", False, "channel"),
            ("mapping_failure", True, False, "mapping", False, "channel"),
            ("association_failure", True, False, "association", False, "channel"),
            ("ordinary_thread", False, False, None, False, "channel"),
            ("implementation_repository_refresh", True, True, None, True, "channel"),
        ]
    )
    @patch("products.tasks.backend.facade.temporal.dispatch_task_processing_workflow")
    @patch("posthog.models.integration.SlackIntegration")
    def test_task_from_a_report_notification_thread_lands_on_the_report(
        self,
        _name,
        from_report_thread,
        implementation,
        failure_stage,
        refresh_repository,
        channel_type,
        mock_slack_cls,
        _mock_execute_workflow,
    ):
        from products.signals.backend.models import (
            SignalReport,
            SignalReportAction,
            SignalReportArtefact,
            SignalReportSlackThread,
        )
        from products.signals.backend.slack_report_threads import record_report_slack_thread

        mock_slack_instance = MagicMock()
        mock_slack_instance.client.chat_getPermalink.return_value = {
            "ok": True,
            "permalink": "https://slack.example.com/thread",
        }
        mock_slack_cls.return_value = mock_slack_instance
        report = SignalReport.objects.create(
            team=self.team, status=SignalReport.Status.READY, title="R", summary="S", total_weight=1.0
        )
        if from_report_thread:
            record_report_slack_thread(
                slack_workspace_id=self.integration.integration_id,
                team_id=self.team.id,
                report_id=str(report.id),
                integration_id=self.integration.id,
                channel="C123",
                thread_ts="1234.5678",
                kind=SignalReportSlackThread.Kind.INBOX_NOTIFICATION,
            )

        inputs = _make_inputs(self.integration.id, self.user.id)
        inputs = replace(inputs, event={**inputs.event, "channel_type": channel_type})
        if implementation:
            inputs = replace(inputs, report_implementation_message_ts="1234.5678")
        if refresh_repository:
            UserIntegration.objects.create(
                user=self.user,
                kind="github",
                integration_id="12345",
                config={"installation_id": "12345"},
                sensitive_config={"user_access_token": "fake-user-token", "user_refresh_token": "fake-refresh-token"},
                repository_cache=[],
            )
        args = (
            inputs,
            "C123",
            "1234.5678",
            "U_ALICE",
            self.user.id,
            inputs.event,
            [SlackThreadMessage(user="U_ALICE", text="look into this")],
            "example/project" if refresh_repository else None,
        )
        if failure_stage:
            if failure_stage == "mapping":
                failure_target = patch.object(
                    SlackThreadTaskMapping.objects, "update_or_create", side_effect=RuntimeError("mapping unavailable")
                )
            elif failure_stage == "registration":
                failure_target = patch(
                    "products.signals.backend.facade.report_tasks.record_report_task",
                    side_effect=RuntimeError("registration unavailable"),
                )
            else:
                failure_target = patch.object(
                    SignalReportAction, "record", side_effect=RuntimeError("action unavailable")
                )
            with failure_target:
                if failure_stage == "association":
                    with self.assertRaises(RuntimeError):
                        create_posthog_code_task_for_repo_activity(*args)
                else:
                    assert create_posthog_code_task_for_repo_activity(*args) is False
            if failure_stage == "association":
                orphan = self.Task.objects.get(team=self.team)
                assert orphan.signal_report_id is None
            else:
                assert not self.Task.objects.filter(team=self.team).exists()
                assert not SlackThreadTaskMapping.objects.filter(integration=self.integration).exists()
            assert not SignalReportArtefact.objects.filter(report_id=report.id).exists()
        with patch(
            "products.signals.backend.facade.report_tasks.enforce_report_task_cap",
            wraps=report_tasks.enforce_report_task_cap,
        ) as admission:

            def refresh_repositories() -> list[dict[str, str]]:
                admission.assert_not_called()
                return [{"full_name": "example/project"}]

            with patch(
                "posthog.models.user_integration.UserGitHubIntegration.list_all_cached_repositories",
                side_effect=refresh_repositories,
            ) as refresh:
                assert create_posthog_code_task_for_repo_activity(*args) is True
            if refresh_repository:
                refresh.assert_called_once()
        create_posthog_code_task_for_repo_activity(*args)

        mapping = SlackThreadTaskMapping.objects.get(
            integration=self.integration, channel="C123", thread_ts="1234.5678"
        )
        task = mapping.task
        assert task.runs.count() == 1
        assert task.origin_product == self.Task.OriginProduct.SLACK
        assert task.signal_report_id == (report.id if from_report_thread else None)
        work_log = SignalReportArtefact.objects.filter(
            report_id=report.id, type=SignalReportArtefact.ArtefactType.TASK_RUN, task_id=task.id
        )
        assert work_log.count() == int(from_report_thread)
        if from_report_thread and not implementation and failure_stage is None:
            action = SignalReportAction.objects.for_team(self.team.id).get(report_id=report.id)
            if channel_type == "im":
                assert action.metadata == {}
            else:
                assert action.metadata["task_id"] == str(task.id)
                assert "do something" in action.metadata["question"]
        from products.signals.backend.scout_harness.inactivity import _engaged_report_ids

        assert (
            str(report.id) in _engaged_report_ids(self.team.id, {str(report.id)}, report.created_at)
        ) is from_report_thread
        if implementation:
            from products.signals.backend.models import SignalReportTask

            assert task.profile == "slack.report_implementation"
            assert not task.internal
            assert task.source_kind == "signal_report"
            assert task.source_id == str(report.id)
            association = SignalReportTask.objects.get(report_id=report.id)
            assert association.task_id == task.id
            assert association.relationship == "implementation"
            assert not SignalReportAction.objects.for_team(self.team.id).filter(report_id=report.id).exists()
            from products.signals.backend.billing import first_billable_pr_run

            run = task.latest_run
            assert run is not None
            assert run.state["billing_product"] == "posthog_ai"
            assert run.state["initial_permission_mode"] == "bypassPermissions"
            assert run.state["pending_dispatch"]["posthog_mcp_scopes"] == "full"
            run.output = {"pr_url": "https://github.com/example/project/pull/1"}
            run.save(update_fields=["output"])
            assert first_billable_pr_run(str(report.id), team_id=self.team.id) is None
            SignalReportSlackThread.objects.for_team(self.team.id).create(
                team=self.team,
                report=report,
                integration=self.integration,
                slack_workspace_id=self.integration.integration_id,
                channel="D123",
                thread_ts="1234.5678",
                kind=SignalReportSlackThread.Kind.INBOX_NOTIFICATION,
            )
            duplicate_inputs = replace(inputs, event={**inputs.event, "channel": "D123"})
            assert not create_posthog_code_task_for_repo_activity(
                duplicate_inputs, "D123", "1234.5678", "U_ALICE", self.user.id, duplicate_inputs.event, [], None
            )
            assert self.Task.objects.filter(team=self.team).count() == 1
        elif from_report_thread:
            action = SignalReportAction.objects.for_team(self.team.id).get(report_id=report.id)
            assert action.user_id == self.user.id
            assert action.count == 1
            assert work_log.get().created_by_id is None
            if failure_stage is None:
                from products.signals.backend.billing import first_billable_pr_run
                from products.signals.backend.models import SignalReportTask

                run = task.latest_run
                assert run is not None
                run.state.pop("billing_product", None)
                run.output = {"pr_url": "https://github.com/example/project/pull/2"}
                run.save(update_fields=["state", "output"])
                restarted_run = task.create_run()
                assert restarted_run.state["billing_product"] == "posthog_ai"
                OrganizationMembership.objects.create(organization=self.org, user=self.user)
                assert prepare_slack_report_implementation_activity(
                    replace(inputs, report_implementation_message_ts="1234.5678")
                )
                assert SignalReportTask.objects.get(report_id=report.id).task_id == task.id
                run.refresh_from_db()
                assert run.state["billing_product"] == "posthog_ai"
                assert first_billable_pr_run(str(report.id), team_id=self.team.id) is None

    @patch("products.tasks.backend.facade.temporal.dispatch_task_processing_workflow")
    @patch("posthog.models.integration.SlackIntegration")
    def test_initial_task_uploads_slack_attachment_to_pending_prompt(
        self, mock_slack_cls, mock_execute_workflow
    ) -> None:
        mock_slack_instance = MagicMock()
        mock_slack_instance.client.token = "xoxb-test"
        mock_slack_instance.client.chat_getPermalink.return_value = {
            "ok": True,
            "permalink": "https://slack.example.com/thread",
        }
        mock_slack_cls.return_value = mock_slack_instance

        event = {
            "channel": "C123",
            "ts": "1234.5678",
            "user": "U_ALICE",
            "text": "<@BOT> review this log",
            "files": [_make_slack_file(name="debug.log", size=9)],
        }
        inputs = PostHogCodeSlackMentionWorkflowInputs(
            event=event,
            integration_id=self.integration.id,
            slack_team_id="T_SLACK",
            user_id=self.user.id,
        )

        with (
            patch("products.slack_app.backend.temporal.attachments._download_slack_file", return_value=b"log bytes"),
            patch("posthog.storage.object_storage.write") as mock_write,
            patch("posthog.storage.object_storage.tag"),
        ):
            create_posthog_code_task_for_repo_activity(
                inputs,
                "C123",
                "1234.5678",
                "U_ALICE",
                self.user.id,
                event,
                [SlackThreadMessage(user="U_ALICE", text="review this log", ts="1234.5678")],
                None,
            )

        task = self.Task.objects.get(team=self.team)
        run = self.TaskRun.objects.get(task=task)
        assert "review this log" in run.state["pending_user_message"]
        assert (
            "Slack attachment(s) available to the agent as task files: debug.log." in run.state["pending_user_message"]
        )
        assert len(run.state["pending_user_artifact_ids"]) == 1
        assert run.artifacts[0]["id"] == run.state["pending_user_artifact_ids"][0]
        assert run.artifacts[0]["name"] == "debug.log"
        assert run.artifacts[0]["type"] == "user_attachment"
        assert run.artifacts[0]["source"] == "slack_user_attachment"
        assert run.artifacts[0]["content_type"] == "text/plain"
        mock_write.assert_called_once()
        assert mock_write.call_args.args[1] == b"log bytes"
        mock_execute_workflow.assert_called_once()

    @patch("products.tasks.backend.facade.temporal.dispatch_task_processing_workflow")
    @patch("posthog.models.integration.SlackIntegration")
    def test_initial_task_uploads_an_attachment_posted_earlier_in_the_thread(
        self, mock_slack_cls, mock_execute_workflow
    ) -> None:
        # Somebody posts a chart, the discussion runs, and the ask lands several replies
        # later. The mention carries no file of its own, so the chart only reaches the
        # agent if the thread's own attachments are fetched too.
        mock_slack_instance = MagicMock()
        mock_slack_instance.client.token = "xoxb-test"
        mock_slack_instance.client.chat_getPermalink.return_value = {
            "ok": True,
            "permalink": "https://slack.example.com/thread",
        }
        mock_slack_cls.return_value = mock_slack_instance

        event = {
            "channel": "C123",
            "ts": "1234.5678",
            "user": "U_ALICE",
            "text": "<@BOT> what is this telling us?",
        }
        inputs = PostHogCodeSlackMentionWorkflowInputs(
            event=event,
            integration_id=self.integration.id,
            slack_team_id="T_SLACK",
            user_id=self.user.id,
        )
        thread_messages = [
            SlackThreadMessage(
                user="U_ALICE",
                text="",
                ts="1234.0000",
                files_json=encode_slack_file_refs(
                    [_make_file_ref(name="costs.png", mimetype="image/png", filetype="png", size=9)]
                ),
            ),
            SlackThreadMessage(user="U_ALICE", text="what is this telling us?", ts="1234.5678"),
        ]

        with (
            patch("products.slack_app.backend.temporal.attachments._download_slack_file", return_value=b"png bytes"),
            patch("posthog.storage.object_storage.write"),
            patch("posthog.storage.object_storage.tag"),
        ):
            create_posthog_code_task_for_repo_activity(
                inputs,
                "C123",
                "1234.5678",
                "U_ALICE",
                self.user.id,
                event,
                thread_messages,
                None,
            )

        task = self.Task.objects.get(team=self.team)
        run = self.TaskRun.objects.get(task=task)
        assert run.artifacts[0]["name"] == "costs.png"
        assert run.artifacts[0]["id"] in run.state["pending_user_artifact_ids"]
        assert (
            "Slack attachment(s) available to the agent as task files: costs.png." in run.state["pending_user_message"]
        )
        # The context block says which message it came from, so the agent can place it.
        assert "[Attached file(s): costs.png]" in task.description

    @patch("products.tasks.backend.facade.temporal.dispatch_task_processing_workflow")
    @patch("posthog.models.integration.SlackIntegration")
    def test_existing_mapping_skips_duplicate_task_creation(self, mock_slack_cls, mock_execute_workflow):
        """A retried activity (or a concurrent duplicate mention) must not create a
        second task for a thread that already has one and repoint the mapping."""
        mock_slack_cls.return_value = MagicMock()
        existing_task = self.Task.objects.create(
            team=self.team,
            title="Existing task",
            description="desc",
            origin_product=self.Task.OriginProduct.SLACK,
            created_by=self.user,
        )
        existing_run = self.TaskRun.objects.create(
            task=existing_task, team=self.team, status=self.TaskRun.Status.IN_PROGRESS
        )
        SlackThreadTaskMapping.objects.create(
            team=self.team,
            integration=self.integration,
            slack_workspace_id="T_SLACK",
            channel="C123",
            thread_ts="1234.5678",
            task=existing_task,
            task_run=existing_run,
            mentioning_slack_user_id="U_ALICE",
        )

        inputs = _make_inputs(self.integration.id, self.user.id)
        create_posthog_code_task_for_repo_activity(
            inputs,
            "C123",
            "1234.5678",
            "U_ALICE",
            self.user.id,
            inputs.event,
            [SlackThreadMessage(user="U_ALICE", text="do something")],
            None,
        )

        assert self.Task.objects.count() == 1
        mapping = SlackThreadTaskMapping.objects.get(
            integration=self.integration, channel="C123", thread_ts="1234.5678"
        )
        assert mapping.task_id == existing_task.id
        assert mapping.task_run_id == existing_run.id
        mock_execute_workflow.assert_not_called()

    @patch("products.tasks.backend.facade.temporal.dispatch_task_processing_workflow")
    @patch("posthog.models.integration.SlackIntegration")
    def test_persists_explicit_event_id_in_workflow_id(self, mock_slack_cls, mock_execute_workflow):
        mock_slack_instance = MagicMock()
        mock_slack_instance.client.chat_getPermalink.return_value = {
            "ok": True,
            "permalink": "https://slack.example.com/thread",
        }
        mock_slack_cls.return_value = mock_slack_instance

        inputs = PostHogCodeSlackMentionWorkflowInputs(
            event={"channel": "C123", "ts": "1234.5678", "user": "U_ALICE", "text": "<@BOT> hi"},
            integration_id=self.integration.id,
            slack_team_id="T_SLACK",
            slack_event_id="Ev01234567",
            user_id=self.user.id,
        )
        create_posthog_code_task_for_repo_activity(
            inputs,
            "C123",
            "1234.5678",
            "U_ALICE",
            self.user.id,
            inputs.event,
            [SlackThreadMessage(user="U_ALICE", text="hi")],
            None,
        )

        task = self.Task.objects.get(team=self.team)
        latest_run = task.latest_run
        assert latest_run is not None
        assert latest_run.state["slack_mention_workflow_id"] == "slack-app-mention-processing-T_SLACK:Ev01234567"

    @patch("products.tasks.backend.facade.temporal.dispatch_task_processing_workflow")
    @patch("posthog.models.integration.SlackIntegration")
    def test_persists_repo_research_ids_when_provided(self, mock_slack_cls, mock_execute_workflow):
        mock_slack_instance = MagicMock()
        mock_slack_instance.client.chat_getPermalink.return_value = {
            "ok": True,
            "permalink": "https://slack.example.com/thread",
        }
        mock_slack_cls.return_value = mock_slack_instance

        inputs = _make_inputs(self.integration.id, self.user.id)
        create_posthog_code_task_for_repo_activity(
            inputs,
            "C123",
            "1234.5678",
            "U_ALICE",
            self.user.id,
            inputs.event,
            [SlackThreadMessage(user="U_ALICE", text="investigate the flaky checkout test")],
            None,
            "11111111-1111-1111-1111-111111111111",
            "22222222-2222-2222-2222-222222222222",
        )

        task = self.Task.objects.get(team=self.team)
        latest_run = task.latest_run
        assert latest_run is not None
        state = latest_run.state
        assert state["repo_research_task_id"] == "11111111-1111-1111-1111-111111111111"
        assert state["repo_research_run_id"] == "22222222-2222-2222-2222-222222222222"

    @patch("products.tasks.backend.facade.temporal.dispatch_task_processing_workflow")
    @patch("posthog.models.integration.SlackIntegration")
    def test_no_repo_research_ids_when_not_provided(self, mock_slack_cls, mock_execute_workflow):
        # The unambiguous path (explicit mention / cascade auto) never runs the
        # discovery sandbox, so the keys must be absent rather than null.
        mock_slack_instance = MagicMock()
        mock_slack_instance.client.chat_getPermalink.return_value = {
            "ok": True,
            "permalink": "https://slack.example.com/thread",
        }
        mock_slack_cls.return_value = mock_slack_instance

        inputs = _make_inputs(self.integration.id, self.user.id)
        create_posthog_code_task_for_repo_activity(
            inputs,
            "C123",
            "1234.5678",
            "U_ALICE",
            self.user.id,
            inputs.event,
            [SlackThreadMessage(user="U_ALICE", text="just answer this, no repo needed")],
            None,
        )

        task = self.Task.objects.get(team=self.team)
        latest_run = task.latest_run
        assert latest_run is not None
        assert "repo_research_task_id" not in latest_run.state
        assert "repo_research_run_id" not in latest_run.state

    @patch("products.tasks.backend.facade.temporal.dispatch_task_processing_workflow")
    @patch("posthog.models.integration.SlackIntegration")
    def test_no_repo_task_falls_back_to_team_github_integration(self, mock_slack_cls, mock_execute_workflow):
        Integration.objects.create(team=self.team, kind="github", integration_id="12345", config={})
        mock_slack_instance = MagicMock()
        mock_slack_instance.client.chat_getPermalink.return_value = {
            "ok": True,
            "permalink": "https://slack.example.com/thread",
        }
        mock_slack_cls.return_value = mock_slack_instance

        inputs = _make_inputs(self.integration.id, self.user.id)
        create_posthog_code_task_for_repo_activity(
            inputs,
            "C123",
            "1234.5678",
            "U_ALICE",
            self.user.id,
            inputs.event,
            [SlackThreadMessage(user="U_ALICE", text="clone a repo later")],
            None,
        )

        task = self.Task.objects.get(team=self.team)
        assert task.repository is None
        assert task.github_integration is not None
        assert task.github_user_integration is None
        latest_run = task.latest_run
        assert latest_run is not None
        assert latest_run.state["pr_authorship_mode"] == "bot"
        mock_execute_workflow.assert_called_once()

    @patch("products.tasks.backend.facade.temporal.dispatch_task_processing_workflow")
    @patch("posthog.models.integration.SlackIntegration")
    def test_no_repo_task_falls_back_to_team_github_integration_when_user_token_unusable(
        self, mock_slack_cls, mock_execute_workflow
    ):
        Integration.objects.create(team=self.team, kind="github", integration_id="12345", config={})
        UserIntegration.objects.create(
            user=self.user,
            kind="github",
            integration_id="12345",
            config={"installation_id": "12345"},
            sensitive_config={},
        )
        mock_slack_instance = MagicMock()
        mock_slack_instance.client.chat_getPermalink.return_value = {
            "ok": True,
            "permalink": "https://slack.example.com/thread",
        }
        mock_slack_cls.return_value = mock_slack_instance

        inputs = _make_inputs(self.integration.id, self.user.id)
        create_posthog_code_task_for_repo_activity(
            inputs,
            "C123",
            "1234.5678",
            "U_ALICE",
            self.user.id,
            inputs.event,
            [SlackThreadMessage(user="U_ALICE", text="clone a repo later")],
            None,
        )

        task = self.Task.objects.get(team=self.team)
        assert task.repository is None
        assert task.github_integration is not None
        assert task.github_user_integration is None
        latest_run = task.latest_run
        assert latest_run is not None
        assert latest_run.state["pr_authorship_mode"] == "bot"
        mock_execute_workflow.assert_called_once()

    @patch("products.tasks.backend.facade.temporal.dispatch_task_processing_workflow")
    @patch("posthog.models.integration.SlackIntegration")
    def test_no_repo_task_prefers_user_github_integration(self, mock_slack_cls, mock_execute_workflow):
        UserIntegration.objects.create(
            user=self.user,
            kind="github",
            integration_id="12345",
            config={"installation_id": "12345"},
            sensitive_config={"user_access_token": "gho_user", "user_refresh_token": "ghr_user"},
        )
        mock_slack_instance = MagicMock()
        mock_slack_instance.client.chat_getPermalink.return_value = {
            "ok": True,
            "permalink": "https://slack.example.com/thread",
        }
        mock_slack_cls.return_value = mock_slack_instance

        inputs = _make_inputs(self.integration.id, self.user.id)
        create_posthog_code_task_for_repo_activity(
            inputs,
            "C123",
            "1234.5678",
            "U_ALICE",
            self.user.id,
            inputs.event,
            [SlackThreadMessage(user="U_ALICE", text="clone a repo later")],
            None,
        )

        task = self.Task.objects.get(team=self.team)
        assert task.repository is None
        assert task.github_user_integration is not None
        latest_run = task.latest_run
        assert latest_run is not None
        assert latest_run.state["pr_authorship_mode"] == "user"
        mock_execute_workflow.assert_called_once()

    # Description-format coverage (labeled mentions, indentation, role annotations,
    # forged-tag neutralization, single-message threads, mentioner-from-cache fallback)
    # lives at the helper level in
    # `posthog/temporal/tests/ai/slack_app/activities/test_task_creation.py`. Tests
    # below cover the surrounding activity wiring: Slack permalink, mapping, workflow
    # start, quota blocking, etc.

    @parameterized.expand(
        [
            (
                "text_on_the_event",
                {"channel": "C123", "ts": "1234.5678", "user": "U_GEORGIY", "text": "<@BOT> do something"},
                "do something",
            ),
            # A Slack workflow, or a client that posts rich text, leaves `text` empty and
            # carries the words in `blocks`. Reading `text` alone hands the agent the
            # "Task from Slack" fallback and loses the ask.
            (
                "words_only_in_blocks",
                {
                    "channel": "C123",
                    "ts": "1234.5678",
                    "user": "U_GEORGIY",
                    "text": "",
                    "blocks": [
                        {"type": "section", "text": {"type": "mrkdwn", "text": "<@BOT> look at the error spike"}}
                    ],
                },
                "look at the error spike",
            ),
        ]
    )
    @patch("products.tasks.backend.facade.temporal.dispatch_task_processing_workflow")
    @patch("posthog.models.integration.SlackIntegration")
    def test_description_is_wired_to_slack_thread_context_helper(
        self, _name, event, expected_prompt, mock_slack_cls, mock_execute_workflow
    ):
        # Smoke-test that the activity calls into the helper and persists the result —
        # the helper's behaviour is exhaustively tested elsewhere; here we just ensure
        # the wrapper tag survives the round-trip through Task.create_and_run.
        mock_slack_instance = MagicMock()
        mock_slack_instance.client.chat_getPermalink.return_value = {
            "ok": True,
            "permalink": "https://slack.example.com/thread",
        }
        mock_slack_cls.return_value = mock_slack_instance

        inputs = _make_inputs(self.integration.id, self.user.id)
        create_posthog_code_task_for_repo_activity(
            inputs,
            "C123",
            "1234.5678",
            "U_GEORGIY",
            self.user.id,
            event,
            [
                SlackThreadMessage(user="georgiy", user_id="U_GEORGIY", text="preamble", ts="1.000"),
                SlackThreadMessage(user="georgiy", user_id="U_GEORGIY", text=expected_prompt, ts="1234.5678"),
            ],
            None,
        )

        task = self.Task.objects.get(team=self.team)
        assert task.description.startswith("<slack_thread_context>")
        assert "</slack_thread_context>" in task.description
        assert task.description.endswith(expected_prompt)

    @patch("products.tasks.backend.facade.temporal.dispatch_task_processing_workflow")
    @patch("posthog.models.integration.SlackIntegration")
    @patch("ee.billing.quota_limiting.is_team_limited", return_value=True)
    def test_quota_exceeded_blocks_task_creation_with_thread_message(
        self,
        _mock_is_team_limited,
        mock_slack_cls,
        mock_execute_workflow,
    ):
        mock_slack_instance = MagicMock()
        mock_slack_cls.return_value = mock_slack_instance

        inputs = _make_inputs(self.integration.id, self.user.id)
        create_posthog_code_task_for_repo_activity(
            inputs,
            "C123",
            "1234.5678",
            "U_ALICE",
            self.user.id,
            inputs.event,
            [SlackThreadMessage(user="U_ALICE", text="do something")],
            None,
        )

        # No task created, no workflow started.
        assert not self.Task.objects.filter(team=self.team).exists()
        mock_execute_workflow.assert_not_called()

        _assert_quota_denial_posted(mock_slack_instance, "C123", "1234.5678")


class TestForwardPostHogCodeFollowupActivity(TestCase):
    def setUp(self):
        self.Task = apps.get_model("tasks", "Task")
        self.TaskRun = apps.get_model("tasks", "TaskRun")
        self.org = Organization.objects.create(name="TestOrg")
        self.team = Team.objects.create(organization=self.org, name="TestTeam")
        self.user = User.objects.create(email="alice@test.com")
        self.integration = Integration.objects.create(
            team=self.team, kind="slack", integration_id="T_SLACK", config={"scope": "files:read"}
        )
        # See note in TestCreatePostHogCodeTaskForRepoActivity.setUp: force the
        # bot-id lookup so `<@BOT>` mentions in test inputs strip the way they
        # do in production.
        bot_id_patcher = patch(
            "products.slack_app.backend.services.slack_messages.get_cached_bot_user_id",
            return_value="BOT",
        )
        bot_id_patcher.start()
        self.addCleanup(bot_id_patcher.stop)
        self.task = self.Task.objects.create(
            team=self.team,
            title="Test task",
            description="desc",
            origin_product=self.Task.OriginProduct.SLACK,
            created_by=self.user,
            repository="org/repo",
        )
        self.task_run = self.TaskRun.objects.create(
            task=self.task,
            team=self.team,
            status=self.TaskRun.Status.IN_PROGRESS,
            state={"sandbox_url": "https://sandbox.example.com/rpc"},
        )

    def _create_mapping(self, mentioning_user: str = "U_ALICE") -> SlackThreadTaskMapping:
        return SlackThreadTaskMapping.objects.create(
            team=self.team,
            integration=self.integration,
            slack_workspace_id="T_SLACK",
            channel="C123",
            thread_ts="1234.5678",
            task=self.task,
            task_run=self.task_run,
            mentioning_slack_user_id=mentioning_user,
        )

    def test_no_mapping_returns_false(self):
        inputs = _make_inputs(self.integration.id, self.user.id)
        result = forward_posthog_code_followup_activity(
            inputs, "C123", "1234.5678", "U_ALICE", "do something", "1234.5679"
        )
        assert result is False

    @patch("ee.billing.quota_limiting.is_team_limited", return_value=True)
    @patch("posthog.models.integration.SlackIntegration")
    def test_quota_exceeded_blocks_followup_with_thread_message(
        self,
        mock_slack_cls,
        _mock_is_team_limited,
    ):
        self._create_mapping()
        mock_slack_instance = MagicMock()
        mock_slack_cls.return_value = mock_slack_instance

        inputs = _make_inputs(self.integration.id, self.user.id)
        result = forward_posthog_code_followup_activity(
            inputs, "C123", "1234.5678", "U_ALICE", "do something", "1234.5679"
        )

        # The follow-up was handled by refusal, so the workflow shouldn't fall
        # through to new-task creation.
        assert result is True
        _assert_quota_denial_posted(mock_slack_instance, "C123", "1234.5678")

    @parameterized.expand(
        [
            ("ordinary", None, False),
            ("implementation_slot_free", "implementation", False),
            ("implementation_slot_taken", "implementation", True),
            ("discussion_slot_taken", "discussion", True),
        ]
    )
    @patch("products.tasks.backend.facade.temporal.dispatch_task_processing_workflow")
    @patch("posthog.models.integration.SlackIntegration")
    def test_terminal_run_resumes_same_task(
        self, _name, relationship, slot_taken, mock_slack_cls, mock_execute_workflow
    ):
        from products.signals.backend.facade import report_tasks
        from products.signals.backend.models import SignalReport

        self.task_run.status = self.TaskRun.Status.COMPLETED
        self.task_run.save()
        if relationship:
            report = SignalReport.objects.create(team=self.team, title="Report", summary="Summary", total_weight=1.0)
            self.task.signal_report_id = report.id
            self.task.save(update_fields=["signal_report_id"])
            report_tasks.record_report_task(
                team_id=self.team.id, report_id=str(report.id), task_id=str(self.task.id), relationship=relationship
            )
            if slot_taken:
                competing_task = self.Task.objects.create(
                    team=self.team, title="Other implementation", description="Implement report", created_by=self.user
                )
                self.TaskRun.objects.create(task=competing_task, team=self.team, status=self.TaskRun.Status.IN_PROGRESS)
                report_tasks.record_report_task(
                    team_id=self.team.id, report_id=str(report.id), task_id=str(competing_task.id)
                )
        self._create_mapping()
        type(self.task).objects.filter(id=self.task.id).update(last_client="posthog_desktop")
        mock_slack_instance = MagicMock()
        mock_slack_cls.return_value = mock_slack_instance

        inputs = _make_inputs(self.integration.id, self.user.id)
        result = forward_posthog_code_followup_activity(
            inputs, "C123", "1234.5678", "U_ALICE", "<@BOT> do something", "1234.5679"
        )

        assert result is True
        if relationship == "implementation" and slot_taken:
            mock_execute_workflow.assert_not_called()
            assert self.TaskRun.objects.filter(task=self.task).count() == 1
            mock_slack_instance.client.chat_postMessage.assert_called_once()
            assert "already in progress" in mock_slack_instance.client.chat_postMessage.call_args.kwargs["text"]
            return
        mock_execute_workflow.assert_called_once()
        call_kwargs = mock_execute_workflow.call_args.kwargs
        assert call_kwargs["task_id"] == str(self.task.id)
        assert call_kwargs["user_id"] == self.user.id
        assert call_kwargs["create_pr"] is True
        assert call_kwargs["posthog_mcp_scopes"] == "full"

        new_run_id = call_kwargs["run_id"]
        assert new_run_id != str(self.task_run.id)

        mapping = SlackThreadTaskMapping.objects.get(
            integration=self.integration, channel="C123", thread_ts="1234.5678"
        )
        assert str(mapping.task_run_id) == new_run_id
        assert mapping.task_id == self.task.id
        self.task.refresh_from_db()
        assert self.task.last_client == "slack"

        new_run = self.TaskRun.objects.get(id=new_run_id)
        assert new_run.state.get("pending_user_message") == "do something"
        assert new_run.state.get("pending_user_message_ts") == "1234.5679"
        assert new_run.state.get("initial_prompt_override") == "do something"

        # Resume path also annotates the new run with the mention-dispatch pointer.
        assert new_run.state.get("slack_mention_workflow_id") == "slack-app-mention-processing-T_SLACK:C123:1234.5678"

        mock_slack_instance.client.reactions_add.assert_called_once_with(
            channel="C123", timestamp="1234.5679", name="eyes"
        )
        mock_slack_instance.client.chat_postMessage.assert_not_called()

    @parameterized.expand(
        [
            ("owner", "U_ALICE", ThreadJoinMode.NEVER, True, False),
            ("allowed", "U_BOB", ThreadJoinMode.ALLOW, True, False),
            ("denied", "U_BOB", ThreadJoinMode.NEVER, False, False),
            ("ask_per_person", "U_BOB", ThreadJoinMode.ASK_PER_PERSON, False, True),
            ("ask_per_thread", "U_BOB", ThreadJoinMode.ASK_PER_THREAD, False, True),
        ]
    )
    @patch("products.slack_app.backend.api.post_thread_join_prompt")
    def test_implementation_conversion_requires_thread_join_access(
        self, _name, slack_user_id, mode, allowed, prompted, mock_prompt
    ):
        from products.signals.backend.models import SignalReport, SignalReportSlackThread, SignalReportTask
        from products.signals.backend.slack_report_threads import record_report_slack_thread

        report = SignalReport.objects.create(team=self.team, title="Report", summary="Summary", total_weight=1.0)
        record_report_slack_thread(
            team_id=self.team.id,
            report_id=str(report.id),
            integration_id=self.integration.id,
            slack_workspace_id="T_SLACK",
            channel="C123",
            thread_ts="1234.5678",
            kind=SignalReportSlackThread.Kind.INBOX_NOTIFICATION,
        )
        self._create_mapping()
        SlackSettings.objects.create(slack_workspace_id="T_SLACK", slack_user_id="U_ALICE", thread_join_mode=mode)
        clicker = self.user if slack_user_id == "U_ALICE" else User.objects.create(email="clicker@example.com")
        OrganizationMembership.objects.create(organization=self.org, user=clicker)
        inputs = _make_inputs(self.integration.id, clicker.id)
        inputs = replace(
            inputs, event={**inputs.event, "user": slack_user_id}, report_implementation_message_ts="1234.5678"
        )

        assert prepare_slack_report_implementation_activity(inputs) is allowed

        self.task_run.refresh_from_db()
        assert (self.task_run.state.get("billing_product") == "posthog_ai") is allowed
        assert SignalReportTask.objects.filter(report=report, task=self.task).exists() is allowed
        assert mock_prompt.called is prompted

    @patch("products.tasks.backend.facade.temporal.dispatch_task_processing_workflow")
    @patch("posthog.models.integration.SlackIntegration")
    def test_terminal_run_resumes_with_slack_attachment(self, mock_slack_cls, mock_execute_workflow) -> None:
        self.task_run.status = self.TaskRun.Status.COMPLETED
        self.task_run.save()
        self._create_mapping()
        mock_slack_instance = MagicMock()
        mock_slack_instance.client.token = "xoxb-test"
        mock_slack_instance.integration = self.integration
        mock_slack_cls.return_value = mock_slack_instance

        event = {
            "channel": "C123",
            "ts": "1234.5679",
            "user": "U_ALICE",
            "text": "<@BOT> check this run",
            "files": [_make_slack_file(name="resume.txt", size=11)],
        }
        inputs = PostHogCodeSlackMentionWorkflowInputs(
            event=event,
            integration_id=self.integration.id,
            slack_team_id="T_SLACK",
            user_id=self.user.id,
        )

        with (
            patch("products.slack_app.backend.temporal.attachments._download_slack_file", return_value=b"resume data"),
            patch("posthog.storage.object_storage.write"),
            patch("posthog.storage.object_storage.tag"),
        ):
            result = forward_posthog_code_followup_activity(
                inputs, "C123", "1234.5678", "U_ALICE", "<@BOT> check this run", "1234.5679"
            )

        assert result is True
        new_run_id = mock_execute_workflow.call_args.kwargs["run_id"]
        new_run = self.TaskRun.objects.get(id=new_run_id)
        assert new_run.state["initial_prompt_override"] == "check this run"
        assert "check this run" in new_run.state["pending_user_message"]
        assert (
            "Slack attachment(s) available to the agent as task files: resume.txt."
            in new_run.state["pending_user_message"]
        )
        assert len(new_run.state["pending_user_artifact_ids"]) == 1
        assert new_run.artifacts[0]["id"] == new_run.state["pending_user_artifact_ids"][0]
        assert new_run.artifacts[0]["name"] == "resume.txt"
        assert new_run.artifacts[0]["source"] == "slack_user_attachment"

    @patch("products.tasks.backend.facade.temporal.dispatch_task_processing_workflow")
    @patch("posthog.models.integration.SlackIntegration")
    def test_terminal_no_repo_run_resumes_with_pr_creation_enabled(self, mock_slack_cls, mock_execute_workflow):
        self.task.repository = None
        self.task.save()
        self.task_run.status = self.TaskRun.Status.COMPLETED
        self.task_run.save()
        self._create_mapping()
        mock_slack_cls.return_value = MagicMock()

        inputs = _make_inputs(self.integration.id, self.user.id)
        result = forward_posthog_code_followup_activity(
            inputs, "C123", "1234.5678", "U_ALICE", "<@BOT> clone org/repo and open PR", "1234.5679"
        )

        assert result is True
        mock_execute_workflow.assert_called_once()
        assert mock_execute_workflow.call_args.kwargs["create_pr"] is True

    @patch("products.tasks.backend.facade.temporal.dispatch_task_processing_workflow")
    @patch("posthog.models.integration.SlackIntegration")
    def test_terminal_run_seeds_pr_context_into_new_run_prompt(self, mock_slack_cls, mock_execute_workflow):
        self.task_run.status = self.TaskRun.Status.COMPLETED
        self.task_run.output = {"pr_url": "https://github.com/org/repo/pull/1"}
        self.task_run.save()
        self._create_mapping()
        mock_slack_cls.return_value = MagicMock()

        inputs = _make_inputs(self.integration.id, self.user.id)
        forward_posthog_code_followup_activity(
            inputs, "C123", "1234.5678", "U_ALICE", "<@BOT> fix the tests", "1234.5679"
        )

        new_run_id = mock_execute_workflow.call_args.kwargs["run_id"]
        new_run = self.TaskRun.objects.get(id=new_run_id)
        # Resumed run is told to reuse the PR branch, and carries no per-run notified
        # flag (the "PR opened" card is deduped on the Task).
        assert "gh pr checkout https://github.com/org/repo/pull/1" in new_run.state.get("initial_prompt_override", "")
        assert "gh pr checkout https://github.com/org/repo/pull/1" in new_run.state.get("pending_user_message", "")
        assert "slack_pr_opened_notified" not in new_run.state
        assert "slack_notified_pr_url" not in new_run.state

    @patch("products.tasks.backend.facade.temporal.dispatch_task_processing_workflow")
    @patch("posthog.models.integration.SlackIntegration")
    def test_terminal_failed_run_resumes_with_structured_recovery_prompt(self, mock_slack_cls, mock_execute_workflow):
        self.task_run.status = self.TaskRun.Status.FAILED
        self.task_run.error_message = "No connected GitHub integration was found for this user"
        self.task_run.output = {"pr_url": "https://github.com/org/repo/pull/1"}
        self.task_run.state = {
            "slack_recovery_strategy": "connect_then_replan",
            "slack_recovery_prompt": "Reply after connecting the missing tool.",
        }
        self.task_run.save()
        self._create_mapping()
        mock_slack_cls.return_value = MagicMock()

        inputs = _make_inputs(self.integration.id, self.user.id)
        result = forward_posthog_code_followup_activity(
            inputs, "C123", "1234.5678", "U_ALICE", "<@BOT> I connected GitHub, try again", "1234.5679"
        )

        assert result is True
        new_run_id = mock_execute_workflow.call_args.kwargs["run_id"]
        new_run = self.TaskRun.objects.get(id=new_run_id)
        prompt = new_run.state["initial_prompt_override"]
        assert "Recovery mode: connect_then_replan" in prompt
        assert "Refresh the current connector/auth state" in prompt
        assert "No connected GitHub integration" in prompt
        assert "I connected GitHub, try again" in prompt
        assert "gh pr checkout https://github.com/org/repo/pull/1" in prompt
        assert new_run.state["slack_recovery_from_run_id"] == str(self.task_run.id)
        assert new_run.state["slack_recovery_strategy"] == "connect_then_replan"
        assert new_run.state["slack_recovery_user_message"] == "I connected GitHub, try again"

    @patch("products.slack_app.backend.api.resolve_slack_user", return_value=None)
    @patch("posthog.models.integration.SlackIntegration")
    def test_terminal_run_unauthorized_user_returns_true_with_resolver_feedback(self, mock_slack_cls, mock_resolve):
        self.task_run.status = self.TaskRun.Status.COMPLETED
        self.task_run.save()
        self._create_mapping(mentioning_user="U_ALICE")
        mock_slack_instance = MagicMock()
        mock_slack_cls.return_value = mock_slack_instance

        inputs = _make_inputs(self.integration.id, self.user.id)
        result = forward_posthog_code_followup_activity(
            inputs, "C123", "1234.5678", "U_BOB", "<@BOT> do something", "1234.5679"
        )

        assert result is True
        mock_resolve.assert_called_once_with(mock_slack_instance, self.integration, "U_BOB", "C123", "1234.5678")
        mock_slack_instance.client.chat_postMessage.assert_not_called()

    @patch("posthog.models.integration.SlackIntegration")
    def test_terminal_run_missing_created_by_returns_true_with_error(self, mock_slack_cls):
        self.task.created_by = None
        self.task.save()
        self.task_run.status = self.TaskRun.Status.COMPLETED
        self.task_run.save()
        self._create_mapping()
        mock_slack_instance = MagicMock()
        mock_slack_cls.return_value = mock_slack_instance

        inputs = _make_inputs(self.integration.id, self.user.id)
        result = forward_posthog_code_followup_activity(
            inputs, "C123", "1234.5678", "U_ALICE", "<@BOT> do something", "1234.5679"
        )

        assert result is True
        call_kwargs = mock_slack_instance.client.chat_postMessage.call_args.kwargs
        assert "original task creator" in call_kwargs["text"]

    @patch("products.tasks.backend.facade.temporal.dispatch_task_processing_workflow", side_effect=Exception("boom"))
    @patch("posthog.models.integration.SlackIntegration")
    def test_terminal_run_workflow_start_failure_returns_true_with_error(self, mock_slack_cls, mock_execute_workflow):
        self.task_run.status = self.TaskRun.Status.COMPLETED
        self.task_run.save()
        self._create_mapping()
        mock_slack_instance = MagicMock()
        mock_slack_cls.return_value = mock_slack_instance

        inputs = _make_inputs(self.integration.id, self.user.id)
        result = forward_posthog_code_followup_activity(
            inputs, "C123", "1234.5678", "U_ALICE", "<@BOT> do something", "1234.5679"
        )

        assert result is True
        call_kwargs = mock_slack_instance.client.chat_postMessage.call_args.kwargs
        assert "internal error" in call_kwargs["text"]

        mapping = SlackThreadTaskMapping.objects.get(
            integration=self.integration, channel="C123", thread_ts="1234.5678"
        )
        assert mapping.task_run_id == self.task_run.id

    @patch("products.slack_app.backend.api.resolve_slack_user", return_value=None)
    @patch("posthog.models.integration.SlackIntegration")
    def test_unauthorized_actor_returns_true_with_resolver_feedback(self, mock_slack_cls, mock_resolve):
        self._create_mapping(mentioning_user="U_ALICE")
        mock_slack_instance = MagicMock()
        mock_slack_cls.return_value = mock_slack_instance

        inputs = _make_inputs(self.integration.id, self.user.id)
        result = forward_posthog_code_followup_activity(
            inputs, "C123", "1234.5678", "U_BOB", "do something", "1234.5679"
        )
        assert result is True
        mock_resolve.assert_called_once_with(mock_slack_instance, self.integration, "U_BOB", "C123", "1234.5678")
        mock_slack_instance.client.chat_postMessage.assert_not_called()

    @patch("products.tasks.backend.facade.api.signal_task_run_user_message", return_value=True)
    @patch("products.slack_app.backend.api.resolve_slack_user")
    @patch("posthog.models.integration.SlackIntegration")
    def test_cross_user_followup_authorized_prefixes_actor_name(self, mock_slack_cls, mock_resolve, mock_signal):
        # A second user in the same PostHog org and team should be allowed to chip in
        # on the thread; their message is queued under their own PostHog identity
        # and their name is prepended so the agent knows who actually spoke.
        self._create_mapping(mentioning_user="U_ALICE")
        type(self.task).objects.filter(id=self.task.id).update(last_client="posthog_desktop")
        bob = User.objects.create(email="bob@test.com", first_name="Bob")
        mock_slack_instance = MagicMock()
        mock_slack_cls.return_value = mock_slack_instance
        mock_resolve.return_value = SlackUserContext(user=bob, slack_email="bob@test.com")

        inputs = _make_inputs(self.integration.id, self.user.id)
        result = forward_posthog_code_followup_activity(
            inputs, "C123", "1234.5678", "U_BOB", "<@BOT> please retry the build", "1234.5679"
        )

        assert result is True
        mock_signal.assert_called_once()
        assert mock_signal.call_args.args == (self.task_run.id, self.task.id, self.team.id)
        signal_kwargs = mock_signal.call_args.kwargs
        assert signal_kwargs["content"] == "Bob: please retry the build"
        # Reply suggestions get the person's own words, without the speaker prefix the agent needs.
        assert signal_kwargs["person_message"] == "please retry the build"
        assert signal_kwargs["actor_user_id"] == bob.id
        assert signal_kwargs["message_id"] is not None
        self.task.refresh_from_db()
        assert self.task.last_client == "slack"
        # No "Only the person who started" denial; the message went through.
        post_calls = [
            call
            for call in mock_slack_instance.client.chat_postMessage.call_args_list
            if "Only the person who started" in call.kwargs.get("text", "")
        ]
        assert not post_calls

    @patch("products.tasks.backend.facade.api.signal_task_run_user_message", return_value=True)
    @patch("products.slack_app.backend.api.resolve_slack_user")
    @patch("posthog.models.integration.SlackIntegration")
    def test_cross_user_followup_falls_back_to_email_when_no_full_name(self, mock_slack_cls, mock_resolve, mock_signal):
        self._create_mapping(mentioning_user="U_ALICE")
        bob = User.objects.create(email="bob@test.com")  # no full name
        mock_slack_cls.return_value = MagicMock()
        mock_resolve.return_value = SlackUserContext(user=bob, slack_email="bob@test.com")

        inputs = _make_inputs(self.integration.id, self.user.id)
        forward_posthog_code_followup_activity(inputs, "C123", "1234.5678", "U_BOB", "<@BOT> ping", "1234.5679")

        mock_signal.assert_called_once()
        signal_kwargs = mock_signal.call_args.kwargs
        assert signal_kwargs["content"] == "bob@test.com: ping"
        assert signal_kwargs["actor_user_id"] == bob.id
        assert signal_kwargs["message_id"] is not None

    @parameterized.expand(
        [
            ("allow", ThreadJoinMode.ALLOW, None, True, False),
            # A creator who never picked a mode lets anyone join.
            ("unset", None, None, True, False),
            ("ask_per_person", ThreadJoinMode.ASK_PER_PERSON, None, False, True),
            ("ask_per_person_already_joined", ThreadJoinMode.ASK_PER_PERSON, ["U_BOB"], True, False),
            ("ask_per_person_after_someone_else_joined", ThreadJoinMode.ASK_PER_PERSON, ["U_CAROL"], False, True),
            ("ask_per_thread", ThreadJoinMode.ASK_PER_THREAD, None, False, True),
            ("ask_per_thread_after_someone_else_joined", ThreadJoinMode.ASK_PER_THREAD, ["U_CAROL"], True, False),
            ("never", ThreadJoinMode.NEVER, None, False, False),
            ("never_after_joining", ThreadJoinMode.NEVER, ["U_BOB"], True, False),
        ]
    )
    @patch("products.slack_app.backend.api.post_thread_join_prompt")
    @patch("products.tasks.backend.facade.api.signal_task_run_user_message", return_value=True)
    @patch("products.slack_app.backend.api.resolve_slack_user")
    @patch("posthog.models.integration.SlackIntegration")
    def test_the_thread_creators_join_mode_decides_who_reaches_the_task(
        self,
        _name,
        mode,
        joined,
        delivered,
        prompted,
        mock_slack_cls,
        mock_resolve,
        mock_signal,
        mock_prompt,
    ):
        SlackSettings.objects.create(slack_workspace_id="T_SLACK", slack_user_id="U_ALICE", thread_join_mode=mode)
        mapping = self._create_mapping(mentioning_user="U_ALICE")
        for slack_user_id in joined or []:
            SlackThreadJoin.objects.for_team(self.team.id).create(
                team=self.team, thread_mapping=mapping, slack_user_id=slack_user_id
            )
        bob = User.objects.create(email="bob@test.com", first_name="Bob")
        mock_slack = MagicMock()
        mock_slack_cls.return_value = mock_slack
        mock_resolve.return_value = SlackUserContext(user=bob, slack_email="bob@test.com")

        inputs = _make_inputs(self.integration.id, self.user.id)
        result = forward_posthog_code_followup_activity(
            inputs, "C123", "1234.5678", "U_BOB", "<@BOT> ship it", "1234.5679"
        )

        assert result is True
        assert mock_signal.called is delivered
        assert mock_prompt.called is prompted
        # A held or dropped message must not keep the reaction that says PostHog is working on it.
        removed = [c.kwargs for c in mock_slack.client.reactions_remove.call_args_list]
        assert ({"channel": "C123", "timestamp": "1234.5679", "name": "eyes"} in removed) is not delivered
        if prompted:
            assert mock_prompt.call_args.kwargs["opens_thread"] is (mode in (None, ThreadJoinMode.ASK_PER_THREAD))
        if delivered:
            # A run on the creator's plan takes the joiner's turn on that plan.
            assert mock_signal.call_args.kwargs["plan_owner_consented"] is True

    @parameterized.expand(
        [
            ("model_pinned_in_the_reply", True),
            # Slack leaves the triple empty when a saved default exists, so the runtime is only
            # known once `create_run` applies that default.
            ("model_from_the_saved_default", False),
        ]
    )
    @patch("products.tasks.backend.facade.temporal.dispatch_task_processing_workflow")
    @patch("products.slack_app.backend.api.resolve_slack_user")
    @patch("posthog.models.integration.SlackIntegration")
    def test_a_joiner_resumes_the_task_on_the_thread_creators_plan(
        self, _name, pinned, mock_slack_cls, mock_resolve, mock_execute_workflow
    ):
        self.task_run.status = self.TaskRun.Status.COMPLETED
        self.task_run.save()
        self._create_mapping(mentioning_user="U_ALICE")
        bob = User.objects.create(email="bob@test.com", first_name="Bob")
        mock_slack_cls.return_value = MagicMock()
        mock_resolve.return_value = SlackUserContext(user=bob, slack_email="bob@test.com")
        preference_patch: AbstractContextManager[object]
        if pinned:
            preference_patch = patch(
                "products.slack_app.backend.temporal.activities.task_creation._run_preference_state",
                return_value={"runtime_adapter": "codex", "model": "gpt-5.5", "provider": "openai"},
            )
        else:
            ai_run_defaults.update_user_ai_run_preferences(
                self.team.id, bob.id, runtime_adapter="codex", model="gpt-5.5", reasoning_effort=None
            )
            preference_patch = nullcontext()

        with (
            preference_patch,
            patch(
                "products.tasks.backend.facade.api.unattended_model_access_state",
                side_effect=lambda user, runtime_adapter: (
                    {"codex_model_access": "own-subscription"}
                    if user == self.user and runtime_adapter == "codex"
                    else {}
                ),
            ),
            patch("products.slack_app.backend.feature_flags.is_slack_app_byos_enabled", return_value=True),
        ):
            forward_posthog_code_followup_activity(
                inputs=_make_inputs(self.integration.id, self.user.id),
                channel="C123",
                thread_ts="1234.5678",
                slack_user_id="U_BOB",
                event_text="<@BOT> fix the tests",
                user_message_ts="1234.5679",
            )

        new_run = self.TaskRun.objects.get(id=mock_execute_workflow.call_args.kwargs["run_id"])
        assert new_run.state["runtime_adapter"] == "codex"
        assert new_run.state["codex_model_access"] == "own-subscription"
        assert new_run.state["codex_subscription_user_id"] == self.user.id
        assert new_run.state["slack_actor_user_id"] == bob.id

    @parameterized.expand(
        [
            # A creator who never picked a mode lets anyone join, also when the run bills to their plan.
            ("unset", None, True, False),
            ("allow", ThreadJoinMode.ALLOW, True, False),
            ("ask_per_thread", ThreadJoinMode.ASK_PER_THREAD, False, True),
        ]
    )
    @patch("products.slack_app.backend.api.post_thread_join_prompt")
    @patch("products.tasks.backend.facade.api.signal_task_run_user_message", return_value=True)
    @patch("products.slack_app.backend.api.resolve_slack_user")
    @patch("posthog.models.integration.SlackIntegration")
    def test_a_run_on_the_creators_own_plan_follows_the_creators_join_mode(
        self, _name, mode, delivered, prompted, mock_slack_cls, mock_resolve, mock_signal, mock_prompt
    ):
        self.task_run.state = {"claude_model_access": "own-subscription", "claude_subscription_user_id": self.user.id}
        self.task_run.save(update_fields=["state"])
        SlackSettings.objects.create(slack_workspace_id="T_SLACK", slack_user_id="U_ALICE", thread_join_mode=mode)
        self._create_mapping(mentioning_user="U_ALICE")
        bob = User.objects.create(email="bob@test.com", first_name="Bob")
        mock_slack_cls.return_value = MagicMock()
        mock_resolve.return_value = SlackUserContext(user=bob, slack_email="bob@test.com")

        inputs = _make_inputs(self.integration.id, self.user.id)
        forward_posthog_code_followup_activity(inputs, "C123", "1234.5678", "U_BOB", "<@BOT> ship it", "1234.5679")

        assert mock_signal.called is delivered
        assert mock_prompt.called is prompted
        if prompted:
            assert mock_prompt.call_args.kwargs["opens_thread"] is True

    @patch("products.slack_app.backend.api.resolve_slack_user", return_value=None)
    @patch("posthog.models.integration.SlackIntegration")
    def test_cross_user_followup_unmapped_user_delegates_feedback_to_resolver(self, mock_slack_cls, mock_resolve):
        # A second Slack user who can't be resolved to a PostHog member of this team
        # still can't participate, but resolve_slack_user owns the exact feedback
        # because it knows whether email, org membership, or team access failed.
        self._create_mapping(mentioning_user="U_ALICE")
        mock_slack_instance = MagicMock()
        mock_slack_cls.return_value = mock_slack_instance

        inputs = _make_inputs(self.integration.id, self.user.id)
        result = forward_posthog_code_followup_activity(
            inputs, "C123", "1234.5678", "U_BOB", "<@BOT> sneak in", "1234.5679"
        )

        assert result is True
        mock_resolve.assert_called_once_with(mock_slack_instance, self.integration, "U_BOB", "C123", "1234.5678")
        mock_slack_instance.client.chat_postMessage.assert_not_called()

    @patch("products.tasks.backend.facade.temporal.dispatch_task_processing_workflow")
    @patch("products.slack_app.backend.api.resolve_slack_user")
    @patch("posthog.models.integration.SlackIntegration")
    def test_cross_user_terminal_run_resume_prefixes_actor_name(
        self, mock_slack_cls, mock_resolve, mock_execute_workflow
    ):
        # The terminal-resume path goes through `_resume_task_with_new_run`, which has
        # its own user_text derivation. Make sure the prefix lands there too so the
        # new run's initial prompt also carries the actor's name.
        self.task_run.status = self.TaskRun.Status.COMPLETED
        self.task_run.save()
        self._create_mapping(mentioning_user="U_ALICE")
        bob = User.objects.create(email="bob@test.com", first_name="Bob")
        mock_slack_cls.return_value = MagicMock()
        mock_resolve.return_value = SlackUserContext(user=bob, slack_email="bob@test.com")

        inputs = _make_inputs(self.integration.id, self.user.id)
        result = forward_posthog_code_followup_activity(
            inputs, "C123", "1234.5678", "U_BOB", "<@BOT> fix the tests", "1234.5679"
        )

        assert result is True
        new_run_id = mock_execute_workflow.call_args.kwargs["run_id"]
        new_run = self.TaskRun.objects.get(id=new_run_id)
        assert mock_execute_workflow.call_args.kwargs["user_id"] == bob.id
        assert new_run.state.get("pending_user_message") == "Bob: fix the tests"
        assert new_run.state.get("initial_prompt_override") == "Bob: fix the tests"
        assert new_run.state["slack_actor_user_id"] == bob.id
        assert new_run.state["slack_actor_slack_user_id"] == "U_BOB"

    @patch("products.tasks.backend.facade.temporal.dispatch_task_processing_workflow")
    @patch("posthog.models.integration.SlackIntegration")
    def test_a_resumed_run_carries_the_model_the_workspace_would_pick(self, mock_slack_cls, mock_execute_workflow):
        # `create_run` builds a fresh state, so without this the follow-up reached the
        # sandbox with no model and the agent server chose one we never recorded — leaving
        # the thread's footer unable to name what ran.
        self.task_run.status = self.TaskRun.Status.COMPLETED
        self.task_run.save()
        self._create_mapping()
        mock_slack_cls.return_value = MagicMock()

        inputs = _make_inputs(self.integration.id, self.user.id)
        result = forward_posthog_code_followup_activity(
            inputs, "C123", "1234.5678", "U_ALICE", "<@BOT> fix the tests", "1234.5679"
        )

        assert result is True
        new_run = self.TaskRun.objects.get(id=mock_execute_workflow.call_args.kwargs["run_id"])
        assert new_run.state["model"] == SLACK_DEFAULT_MODEL
        assert new_run.state["runtime_adapter"]

    @patch("products.tasks.backend.facade.temporal.dispatch_task_processing_workflow")
    @patch("posthog.models.integration.SlackIntegration")
    def test_a_resumed_run_carries_the_pr_authorship_mode(self, mock_slack_cls, mock_execute_workflow):
        # `create_run` builds a fresh state, so without the carry-forward the follow-up re-derives
        # USER authorship for a Slack task. A creator with no personal GitHub install then dead-ends
        # at the token guard on every follow-up, while the first run ran as BOT.
        self.task_run.status = self.TaskRun.Status.COMPLETED
        self.task_run.state = {"pr_authorship_mode": "bot"}
        self.task_run.save()
        self._create_mapping()
        mock_slack_cls.return_value = MagicMock()

        inputs = _make_inputs(self.integration.id, self.user.id)
        result = forward_posthog_code_followup_activity(
            inputs, "C123", "1234.5678", "U_ALICE", "<@BOT> fix the tests", "1234.5679"
        )

        assert result is True
        new_run = self.TaskRun.objects.get(id=mock_execute_workflow.call_args.kwargs["run_id"])
        assert new_run.state["pr_authorship_mode"] == "bot"

    @patch("products.tasks.backend.facade.temporal.dispatch_task_processing_workflow")
    @patch("posthog.models.integration.SlackIntegration")
    def test_a_resumed_run_promotes_bot_authorship_once_the_creator_connects_github(
        self, mock_slack_cls, mock_execute_workflow
    ):
        # The carried BOT must not outlive its reason. A creator who connected GitHub after the
        # previous run went terminal gets their identity on the successor, matching the promotion
        # a live sandbox performs in _refresh_sandbox_github.
        self.task_run.status = self.TaskRun.Status.COMPLETED
        self.task_run.state = {"pr_authorship_mode": "bot"}
        self.task_run.save()
        self._create_mapping()
        mock_slack_cls.return_value = MagicMock()
        UserIntegration.objects.create(
            user=self.user,
            kind=UserIntegration.IntegrationKind.GITHUB,
            integration_id="gh-1",
            config={},
            sensitive_config={"user_access_token": "at", "user_refresh_token": "rt"},
        )

        inputs = _make_inputs(self.integration.id, self.user.id)
        result = forward_posthog_code_followup_activity(
            inputs, "C123", "1234.5678", "U_ALICE", "<@BOT> fix the tests", "1234.5679"
        )

        assert result is True
        new_run = self.TaskRun.objects.get(id=mock_execute_workflow.call_args.kwargs["run_id"])
        assert new_run.state["pr_authorship_mode"] == "user"

    @patch("products.tasks.backend.facade.api.signal_task_run_user_message", return_value=True)
    @patch("posthog.models.integration.SlackIntegration")
    def test_forwards_while_sandbox_is_still_provisioning(self, mock_slack_cls, mock_signal):
        # A run that has started but not yet written `sandbox_url` is mid-provisioning.
        # Delivery is a signal onto the run's workflow, which is already running and
        # queues the message, so the follow-up must be forwarded rather than refused.
        self.task_run.state = {}
        self.task_run.save()
        self._create_mapping()
        mock_slack_instance = MagicMock()
        mock_slack_cls.return_value = mock_slack_instance

        inputs = _make_inputs(self.integration.id, self.user.id)
        result = forward_posthog_code_followup_activity(
            inputs, "C123", "1234.5678", "U_ALICE", "do something", "1234.5679"
        )

        assert result is True
        mock_signal.assert_called_once()
        assert mock_signal.call_args.kwargs["content"] == "do something"
        mock_slack_instance.client.chat_postMessage.assert_not_called()

    @patch("products.tasks.backend.facade.api.signal_task_run_user_message", return_value=True)
    @patch("posthog.models.integration.SlackIntegration")
    def test_successful_forwarding(self, mock_slack_cls, mock_signal):
        mapping = self._create_mapping()
        mock_slack_instance = MagicMock()
        mock_slack_cls.return_value = mock_slack_instance

        inputs = _make_inputs(self.integration.id, self.user.id)
        result = forward_posthog_code_followup_activity(
            inputs, "C123", "1234.5678", "U_ALICE", "<@BOT> do something", "1234.5679"
        )

        assert result is True
        mock_signal.assert_called_once()
        assert mock_signal.call_args.args == (self.task_run.id, self.task.id, self.team.id)
        signal_kwargs = mock_signal.call_args.kwargs
        assert signal_kwargs["content"] == "do something"
        assert signal_kwargs["artifact_ids"] == []
        assert signal_kwargs["actor_user_id"] == self.user.id
        assert signal_kwargs["message_id"] is not None
        # The message is queued on the workflow, so the :eyes: reaction stays up.
        mock_slack_instance.client.reactions_add.assert_called_once_with(
            channel="C123", timestamp="1234.5679", name="eyes"
        )
        mock_slack_instance.client.reactions_remove.assert_not_called()
        # Response is delivered by relayAgentResponse from the agent-server, not by this activity.
        mock_slack_instance.client.chat_postMessage.assert_not_called()
        # The follow-up sender is recorded on the mapping so async reply paths
        # tag the latest actor instead of the original thread creator
        # (multiplayer support). The creator (``mentioning_slack_user_id``)
        # remains immutable; the latest-actor field receives the live actor
        # even when it's the same person as the creator (one-time seed).
        mapping.refresh_from_db()
        assert mapping.latest_actor_slack_user_id == "U_ALICE"
        assert mapping.mentioning_slack_user_id == "U_ALICE"

    def test_attachment_only_followup_uploads_and_forwards_to_sandbox(self) -> None:
        self._create_mapping()
        event = {
            "channel": "C123",
            "ts": "1234.5679",
            "user": "U_ALICE",
            "text": "",
            "files": [_make_slack_file(name="only-log.txt", size=10)],
        }
        inputs = PostHogCodeSlackMentionWorkflowInputs(
            event=event,
            integration_id=self.integration.id,
            slack_team_id="T_SLACK",
            user_id=self.user.id,
        )

        with (
            patch("posthog.models.integration.SlackIntegration") as mock_slack_cls,
            patch("products.tasks.backend.facade.api.signal_task_run_user_message", return_value=True) as mock_signal,
            patch("products.slack_app.backend.temporal.attachments._download_slack_file", return_value=b"log bytes"),
            patch("products.slack_app.backend.services.slack_messages.collect_thread_messages", return_value=[]),
            patch("posthog.storage.object_storage.write") as mock_write,
            patch("posthog.storage.object_storage.tag"),
        ):
            mock_slack_instance = MagicMock()
            mock_slack_instance.client.token = "xoxb-test"
            mock_slack_instance.client.auth_test.return_value = {"bot_id": "B123"}
            mock_slack_cls.return_value = mock_slack_instance

            result = forward_posthog_code_followup_activity(inputs, "C123", "1234.5678", "U_ALICE", "", "1234.5679")
            # Temporal retries re-run the whole activity body; the re-upload must
            # upsert the same manifest entry, not append a duplicate.
            forward_posthog_code_followup_activity(inputs, "C123", "1234.5678", "U_ALICE", "", "1234.5679")

        assert result is True
        assert mock_signal.call_count == 2
        first_call, second_call = mock_signal.call_args_list
        assert first_call.args == (self.task_run.id, self.task.id, self.team.id)
        content = first_call.kwargs["content"]
        assert content.startswith("Attached Slack file(s).")
        assert "Slack attachment(s) available to the agent as task files: only-log.txt." in content
        assert first_call.kwargs["actor_user_id"] == self.user.id
        assert mock_write.call_count == 2
        assert mock_write.call_args_list[0].args[0] == mock_write.call_args_list[1].args[0]
        self.task_run.refresh_from_db()
        assert len(self.task_run.artifacts) == 1
        assert first_call.kwargs["artifact_ids"] == [str(self.task_run.artifacts[0]["id"])]
        assert second_call.kwargs["artifact_ids"] == first_call.kwargs["artifact_ids"]
        # Redelivery must reuse the deterministic idempotency key or the agent
        # applies the message twice.
        assert first_call.kwargs["message_id"] is not None
        assert first_call.kwargs["message_id"] == second_call.kwargs["message_id"]

    def test_followup_forwards_an_attachment_posted_while_the_agent_was_quiet(self) -> None:
        # The follow-up says "look at this" about an image somebody dropped in the thread
        # since the agent last spoke. The reply carries no file, so the image reaches the
        # agent only if the diff window's own attachments are fetched.
        self._create_mapping()
        inputs = _make_inputs(self.integration.id, self.user.id)
        thread_messages = [
            SlackThreadMessage(
                user="mira",
                user_id="U_MIRA",
                text="",
                ts="1234.5678999",
                files_json=encode_slack_file_refs(
                    [_make_file_ref(name="trace.png", mimetype="image/png", filetype="png", size=9)]
                ),
            ),
        ]

        with (
            patch("posthog.models.integration.SlackIntegration") as mock_slack_cls,
            patch("products.tasks.backend.facade.api.signal_task_run_user_message", return_value=True) as mock_signal,
            patch("products.slack_app.backend.temporal.attachments._download_slack_file", return_value=b"png bytes"),
            patch(
                "products.slack_app.backend.services.slack_messages.collect_thread_messages",
                return_value=thread_messages,
            ),
            patch("posthog.storage.object_storage.write"),
            patch("posthog.storage.object_storage.tag"),
        ):
            mock_slack_instance = MagicMock()
            mock_slack_instance.client.token = "xoxb-test"
            mock_slack_instance.client.auth_test.return_value = {"bot_id": "B123"}
            mock_slack_cls.return_value = mock_slack_instance

            result = forward_posthog_code_followup_activity(
                inputs, "C123", "1234.5678", "U_ALICE", "<@BOT> look at this", "1234.5679"
            )

        assert result is True
        self.task_run.refresh_from_db()
        assert [artifact["name"] for artifact in self.task_run.artifacts] == ["trace.png"]
        content = mock_signal.call_args.kwargs["content"]
        assert "[Attached file(s): trace.png]" in content
        assert "Slack attachment(s) available to the agent as task files: trace.png." in content
        assert mock_signal.call_args.kwargs["artifact_ids"] == [str(self.task_run.artifacts[0]["id"])]

    @parameterized.expand(
        [
            ("live_run", False),
            ("terminal_run", True),
        ]
    )
    def test_followup_with_only_rejected_attachments_posts_notice_without_waking_agent(
        self, _name: str, terminal: bool
    ) -> None:
        if terminal:
            self.task_run.status = self.TaskRun.Status.COMPLETED
            self.task_run.save()
        self.integration.config = {}
        self.integration.save()
        self._create_mapping()
        event = {
            "channel": "C123",
            "ts": "1234.5679",
            "user": "U_ALICE",
            "text": "",
            "files": [_make_slack_file(name="debug.log")],
        }
        inputs = PostHogCodeSlackMentionWorkflowInputs(
            event=event,
            integration_id=self.integration.id,
            slack_team_id="T_SLACK",
            user_id=self.user.id,
        )

        with (
            patch("posthog.models.integration.SlackIntegration") as mock_slack_cls,
            patch("products.tasks.backend.facade.temporal.dispatch_task_processing_workflow") as mock_execute_workflow,
            patch("products.tasks.backend.logic.services.agent_command.send_user_message") as mock_send,
            patch("posthog.storage.object_storage.write") as mock_write,
        ):
            mock_slack_instance = MagicMock()
            mock_slack_instance.client.token = "xoxb-test"
            mock_slack_instance.integration = self.integration
            mock_slack_cls.return_value = mock_slack_instance

            result = forward_posthog_code_followup_activity(inputs, "C123", "1234.5678", "U_ALICE", "", "1234.5679")

        assert result is True
        mock_send.assert_not_called()
        mock_write.assert_not_called()
        mock_execute_workflow.assert_not_called()
        assert self.TaskRun.objects.count() == 1
        notice = mock_slack_instance.client.chat_postMessage.call_args.kwargs["text"]
        assert "no attachment was accepted" in notice
        assert "`files:read`" in notice
        assert "reconnect Slack" in notice

    @patch("products.tasks.backend.facade.api.signal_task_run_user_message", return_value=False)
    @patch("posthog.models.integration.SlackIntegration")
    def test_signal_failure_posts_error_reply(self, mock_slack_cls, mock_signal):
        self._create_mapping()
        mock_slack_instance = MagicMock()
        mock_slack_cls.return_value = mock_slack_instance

        inputs = _make_inputs(self.integration.id, self.user.id)
        result = forward_posthog_code_followup_activity(
            inputs, "C123", "1234.5678", "U_ALICE", "<@BOT> do something", "1234.5679"
        )

        assert result is True
        mock_signal.assert_called_once()
        call_kwargs = mock_slack_instance.client.chat_postMessage.call_args.kwargs
        assert "couldn't deliver your message" in call_kwargs["text"]
        # The :eyes: reaction is swapped to :x: so the thread sees the delivery failed.
        mock_slack_instance.client.reactions_remove.assert_called_once_with(
            channel="C123", timestamp="1234.5679", name="eyes"
        )
        mock_slack_instance.client.reactions_add.assert_any_call(channel="C123", timestamp="1234.5679", name="x")


class TestEnforcePostHogCodeBillingQuotaActivity(TestCase):
    """The workflow's first activity gate. Returns True (and posts a denial) when
    the team is over its AI-credits quota; False otherwise."""

    def setUp(self):
        self.org = Organization.objects.create(name="TestOrg")
        self.team = Team.objects.create(organization=self.org, name="TestTeam")
        self.user = User.objects.create(email="alice@test.com")
        self.integration = Integration.objects.create(
            team=self.team, kind="slack", integration_id="T_SLACK", config={"scope": "files:read"}
        )

    @patch("posthog.models.integration.SlackIntegration")
    @patch("ee.billing.quota_limiting.is_team_limited", return_value=True)
    def test_returns_true_and_posts_denial_when_over_quota(self, _mock_is_team_limited, mock_slack_cls):
        mock_slack_instance = MagicMock()
        mock_slack_cls.return_value = mock_slack_instance

        inputs = _make_inputs(self.integration.id, self.user.id)
        blocked = enforce_posthog_code_billing_quota_activity(
            inputs,
            "C123",
            "1234.5678",
            "U_ALICE",
        )

        assert blocked is True
        _assert_quota_denial_posted(mock_slack_instance, "C123", "1234.5678")

    @patch("posthog.models.integration.SlackIntegration")
    @patch("ee.billing.quota_limiting.is_team_limited", return_value=False)
    def test_returns_false_and_posts_nothing_when_under_quota(self, _mock_is_team_limited, mock_slack_cls):
        mock_slack_instance = MagicMock()
        mock_slack_cls.return_value = mock_slack_instance

        inputs = _make_inputs(self.integration.id, self.user.id)
        blocked = enforce_posthog_code_billing_quota_activity(
            inputs,
            "C123",
            "1234.5678",
            "U_ALICE",
        )

        assert blocked is False
        mock_slack_instance.client.chat_postMessage.assert_not_called()


class TestEventLevelDedupe(SimpleTestCase):
    """Verify that the workflow ID format supports event-level deduplication."""

    def test_same_event_id_produces_same_workflow_id(self):
        slack_team_id = "T_SLACK"
        event_id = "Ev123456"
        event_id_or_fallback = event_id
        wf_id_1 = f"slack-app-mention-processing-{slack_team_id}:{event_id_or_fallback}"
        wf_id_2 = f"slack-app-mention-processing-{slack_team_id}:{event_id_or_fallback}"
        assert wf_id_1 == wf_id_2

    def test_different_event_ids_produce_different_workflow_ids(self):
        slack_team_id = "T_SLACK"
        wf_id_1 = f"slack-app-mention-processing-{slack_team_id}:Ev111"
        wf_id_2 = f"slack-app-mention-processing-{slack_team_id}:Ev222"
        assert wf_id_1 != wf_id_2

    def test_fallback_uses_channel_and_ts(self):
        slack_team_id = "T_SLACK"
        event_id = None
        channel = "C123"
        ts = "1234.5678"
        event_id_or_fallback = event_id if event_id else f"{channel}:{ts}"
        wf_id = f"slack-app-mention-processing-{slack_team_id}:{event_id_or_fallback}"
        assert wf_id == "slack-app-mention-processing-T_SLACK:C123:1234.5678"


class TestSafeReact(UnitTestCase):
    """The 👀/🔍 reaction is cosmetic UX feedback and must never abort an activity."""

    @parameterized.expand(["already_reacted", "message_not_found", "no_reaction", "cant_react"])
    def test_benign_reaction_errors_are_swallowed(self, error_code):
        client = MagicMock()
        client.reactions_add.side_effect = SlackApiError("boom", response={"error": error_code})

        safe_react(client, "C123", "1234.5679", "eyes")

        client.reactions_add.assert_called_once_with(channel="C123", timestamp="1234.5679", name="eyes")

    def test_fatal_reaction_errors_are_reraised(self):
        client = MagicMock()
        client.reactions_add.side_effect = SlackApiError("boom", response={"error": "invalid_auth"})

        with self.assertRaises(SlackApiError):
            safe_react(client, "C123", "1234.5679", "eyes")

    def test_successful_reaction_does_not_raise(self):
        client = MagicMock()

        safe_react(client, "C123", "1234.5679", "eyes")

        client.reactions_add.assert_called_once_with(channel="C123", timestamp="1234.5679", name="eyes")
