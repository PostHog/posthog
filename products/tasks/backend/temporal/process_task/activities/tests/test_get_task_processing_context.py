import pytest
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import override_settings

from asgiref.sync import async_to_sync

from posthog.models import OrganizationMembership, User
from posthog.models.user_integration import UserIntegration

from products.tasks.backend.constants import (
    AGENT_PROXY_KEEP_STREAM_OPEN_FEATURE_FLAG,
    CONTINUE_AS_NEW_FEATURE_FLAG,
    DESKTOP_WORKSPACE_WARM_FEATURE_FLAG,
    MODAL_VM_SANDBOX_FEATURE_FLAG,
    PR_BABYSIT_SNAPSHOT_FEATURE_FLAG,
    RTK_DISABLED_FEATURE_FLAG,
    SANDBOX_EVENT_INGEST_FEATURE_FLAG,
    vm_sandbox_allowed_origin_products,
    vm_sandbox_default_base_origin_products,
    vm_sandbox_default_custom_image,
    vm_sandbox_origin_in_rollout,
    vm_sandbox_origin_rollout_percentages,
)
from products.tasks.backend.exceptions import TaskInvalidStateError, TaskRunNotReadyError
from products.tasks.backend.models import TASK_OWNERSHIP_VERSION_STATE_KEY, SandboxEnvironment, Task
from products.tasks.backend.temporal.process_task.activities.get_task_processing_context import (
    GetTaskProcessingContextInput,
    TaskProcessingContext,
    VmSandboxDecision,
    _is_agent_otel_telemetry_enabled,
    _is_agent_proxy_keep_stream_open_enabled,
    _is_burstable_sandbox_resources_enabled,
    _is_continue_as_new_enabled,
    _is_desktop_workspace_warm_enabled,
    _is_pr_babysit_snapshot_enabled,
    _is_rtk_enabled,
    _is_sandbox_event_ingest_enabled,
    _resolve_modal_vm_sandbox,
    get_task_processing_context,
)
from products.tasks.backend.temporal.process_task.utils import get_actor_distinct_id

VM_FLAG_PAYLOAD_TARGET = "products.tasks.backend.constants.posthoganalytics.get_feature_flag_payload"


@pytest.mark.parametrize(
    "state,expected",
    [
        ({}, False),
        ({"resume_from_run_id": "previous-run"}, False),
        ({"handoff_resumed": True}, False),
        ({"snapshot_external_id": "snapshot-id"}, False),
        (
            {
                "resume_from_run_id": "previous-run",
                "snapshot_external_id": "snapshot-id",
            },
            True,
        ),
        (
            {
                "handoff_resumed": True,
                "snapshot_external_id": "snapshot-id",
            },
            True,
        ),
    ],
)
def test_snapshot_resume_requires_a_resume_marker_and_snapshot(state: dict[str, str | bool], expected: bool):
    context = TaskProcessingContext(
        task_id="task-id",
        run_id="run-id",
        team_id=1,
        team_uuid="team-uuid",
        organization_id="organization-id",
        github_integration_id=None,
        repository=None,
        distinct_id="distinct-id",
        state=state,
    )

    assert context.is_snapshot_resume is expected


@pytest.mark.parametrize("flag_value,expected", [(True, True), (False, False), (None, False)])
def test_desktop_workspace_warm_flag_uses_organization_rollout(flag_value, expected):
    with patch(
        "products.tasks.backend.temporal.process_task.activities.get_task_processing_context.posthoganalytics.feature_enabled",
        return_value=flag_value,
    ) as feature_enabled_mock:
        assert (
            _is_desktop_workspace_warm_enabled(
                distinct_id="distinct-id",
                organization_id="organization-id",
                run_id="run-id",
            )
            is expected
        )

    feature_enabled_mock.assert_called_once_with(
        DESKTOP_WORKSPACE_WARM_FEATURE_FLAG,
        distinct_id="distinct-id",
        groups={"organization": "organization-id"},
        group_properties={"organization": {"id": "organization-id"}},
        only_evaluate_locally=False,
        send_feature_flag_events=False,
    )


def test_desktop_workspace_warm_flag_fails_closed():
    with patch(
        "products.tasks.backend.temporal.process_task.activities.get_task_processing_context.posthoganalytics.feature_enabled",
        side_effect=RuntimeError("flag service failed"),
    ):
        assert (
            _is_desktop_workspace_warm_enabled(
                distinct_id="distinct-id",
                organization_id="organization-id",
                run_id="run-id",
            )
            is False
        )


@pytest.mark.requires_secrets
class TestIsAgentOtelTelemetryEnabled:
    @pytest.mark.parametrize(
        "debug,state,expected",
        [
            # DEBUG must win over the stamp: local dev always stamps False (SDK disabled),
            # and the SANDBOX_AGENT_OTEL_* settings are the local opt-in.
            (True, {"agent_otel_telemetry_enabled": False}, True),
            (True, {}, True),
            (False, {"agent_otel_telemetry_enabled": True}, True),
            (False, {"agent_otel_telemetry_enabled": False}, False),
        ],
    )
    def test_debug_wins_then_stamp(self, debug, state, expected):
        with override_settings(DEBUG=debug):
            assert (
                _is_agent_otel_telemetry_enabled(distinct_id="d", organization_id="o", run_id="r", state=state)
                is expected
            )


class TestGetTaskProcessingContextActivity:
    def _create_task_with_repo(self, team, user, github_integration, repo_config):
        return Task.objects.create(
            team=team,
            title="Test Task",
            description="Test task description",
            origin_product=Task.OriginProduct.USER_CREATED,
            github_integration=github_integration,
            repository=repo_config,
            created_by=user,
        )

    def _cleanup_task(self, task):
        task.soft_delete()

    @pytest.mark.django_db(transaction=True)
    def test_get_task_processing_context_success(self, activity_environment, test_task):
        task_run = test_task.create_run()
        input_data = GetTaskProcessingContextInput(run_id=str(task_run.id))

        result = async_to_sync(activity_environment.run)(get_task_processing_context, input_data)

        assert isinstance(result, TaskProcessingContext)
        assert result.task_id == str(test_task.id)
        assert result.run_id == str(task_run.id)
        assert result.team_id == test_task.team_id
        assert result.github_integration_id == test_task.github_integration_id
        assert result.repository == "posthog/posthog-js"
        assert result.create_pr is True

    @pytest.mark.django_db(transaction=True)
    def test_get_task_processing_context_rejects_previous_owner_run(self, activity_environment, test_task):
        task_run = test_task.create_run()
        test_task.state = {TASK_OWNERSHIP_VERSION_STATE_KEY: "new-owner"}
        test_task.save(update_fields=["state", "updated_at"])

        with pytest.raises(TaskInvalidStateError):
            async_to_sync(activity_environment.run)(
                get_task_processing_context,
                GetTaskProcessingContextInput(run_id=str(task_run.id)),
            )

    @pytest.mark.django_db(transaction=True)
    def test_get_task_processing_context_task_not_found_is_retryable(self, activity_environment):
        # A missing TaskRun is treated as a transient (retryable) condition, not a fatal error,
        # so the activity's retry policy can recover once a just-created row becomes visible.
        non_existent_run_id = "550e8400-e29b-41d4-a716-446655440000"
        input_data = GetTaskProcessingContextInput(run_id=non_existent_run_id)

        with pytest.raises(TaskRunNotReadyError) as exc_info:
            async_to_sync(activity_environment.run)(get_task_processing_context, input_data)

        assert exc_info.value.non_retryable is False

    @pytest.mark.django_db(transaction=True)
    def test_get_task_processing_context_invalid_uuid(self, activity_environment):
        invalid_run_id = "not-a-uuid"
        input_data = GetTaskProcessingContextInput(run_id=invalid_run_id)

        with pytest.raises(ValidationError):
            async_to_sync(activity_environment.run)(get_task_processing_context, input_data)

    @pytest.mark.django_db(transaction=True)
    def test_get_task_processing_context_with_different_repository(
        self, activity_environment, team, user, github_integration
    ):
        task = self._create_task_with_repo(team, user, github_integration, "posthog/posthog-js")
        task_run = task.create_run()

        try:
            input_data = GetTaskProcessingContextInput(run_id=str(task_run.id))
            result = async_to_sync(activity_environment.run)(get_task_processing_context, input_data)

            assert result.task_id == str(task.id)
            assert result.run_id == str(task_run.id)
            assert result.team_id == task.team_id
            assert result.github_integration_id == github_integration.id
            assert result.repository == "posthog/posthog-js"
        finally:
            self._cleanup_task(task)

    @pytest.mark.django_db(transaction=True)
    def test_get_task_processing_context_with_create_pr_false(self, activity_environment, test_task):
        task_run = test_task.create_run()
        input_data = GetTaskProcessingContextInput(run_id=str(task_run.id), create_pr=False)
        result = async_to_sync(activity_environment.run)(get_task_processing_context, input_data)

        assert isinstance(result, TaskProcessingContext)
        assert result.create_pr is False

    @pytest.mark.django_db(transaction=True)
    def test_get_task_processing_context_resolves_user_github_integration_without_repository(
        self, activity_environment, team, user
    ):
        user_integration = UserIntegration.objects.create(
            user=user,
            kind="github",
            integration_id="12345",
            config={"installation_id": "12345"},
            sensitive_config={"user_access_token": "gho_test", "user_refresh_token": "ghr_test"},
        )
        task = Task.objects.create(
            team=team,
            created_by=user,
            title="Slack task without repository",
            description="Clone a repo later from chat",
            origin_product=Task.OriginProduct.SLACK,
        )
        task_run = task.create_run(
            extra_state={
                "interaction_origin": "slack",
                "pr_authorship_mode": "user",
                "slack_actor_user_id": user.id,
            }
        )

        result = async_to_sync(activity_environment.run)(
            get_task_processing_context,
            GetTaskProcessingContextInput(run_id=str(task_run.id)),
        )

        assert result.repository is None
        assert result.github_integration_id is None
        assert result.github_user_integration_id == str(user_integration.id)
        assert result.has_github_credentials is True

    @pytest.mark.django_db(transaction=True)
    def test_get_task_processing_context_requires_valid_slack_actor(self, activity_environment, team, user):
        task = Task.objects.create(
            team=team,
            created_by=user,
            title="Slack task with unresolvable actor",
            description="Summarize the thread",
            origin_product=Task.OriginProduct.SLACK,
        )
        task_run = task.create_run(
            extra_state={
                "interaction_origin": "slack",
                "pr_authorship_mode": "user",
                "slack_actor_user_id": user.id + 999_999,
            }
        )

        with pytest.raises(TaskInvalidStateError):
            async_to_sync(activity_environment.run)(
                get_task_processing_context,
                GetTaskProcessingContextInput(run_id=str(task_run.id)),
            )

    @pytest.mark.django_db(transaction=True)
    def test_get_task_processing_context_grandfathers_slack_runs_without_actor_state(
        self, activity_environment, team, user
    ):
        task = Task.objects.create(
            team=team,
            created_by=user,
            title="Slack task started before actor tracking",
            description="Summarize the thread",
            origin_product=Task.OriginProduct.SLACK,
        )
        task_run = task.create_run(extra_state={"interaction_origin": "slack", "pr_authorship_mode": "bot"})

        result = async_to_sync(activity_environment.run)(
            get_task_processing_context,
            GetTaskProcessingContextInput(run_id=str(task_run.id)),
        )

        assert result.distinct_id == get_actor_distinct_id(user)

    @pytest.mark.django_db(transaction=True)
    def test_get_task_processing_context_uses_team_integration_without_repository(
        self, activity_environment, team, user, github_integration
    ):
        task = Task.objects.create(
            team=team,
            created_by=user,
            title="Slack task without repository",
            description="Clone a repo later from chat",
            origin_product=Task.OriginProduct.SLACK,
            github_integration=github_integration,
        )
        task_run = task.create_run(
            extra_state={
                "interaction_origin": "slack",
                "pr_authorship_mode": "bot",
                "slack_actor_user_id": user.id,
            }
        )

        result = async_to_sync(activity_environment.run)(
            get_task_processing_context,
            GetTaskProcessingContextInput(run_id=str(task_run.id)),
        )

        assert result.repository is None
        assert result.github_integration_id == github_integration.id
        assert result.github_user_integration_id is None
        assert result.has_github_credentials is True

    @pytest.mark.django_db(transaction=True)
    def test_get_task_processing_context_resolves_allowed_domains(self, activity_environment, test_task):
        sandbox_environment = SandboxEnvironment.objects.create(
            team=test_task.team,
            created_by=test_task.created_by,
            name="Restricted env",
            network_access_level=SandboxEnvironment.NetworkAccessLevel.CUSTOM,
            allowed_domains=["example.com"],
        )
        task_run = test_task.create_run(extra_state={"sandbox_environment_id": str(sandbox_environment.id)})

        input_data = GetTaskProcessingContextInput(run_id=str(task_run.id))
        result = async_to_sync(activity_environment.run)(get_task_processing_context, input_data)

        assert result.sandbox_environment_id == str(sandbox_environment.id)
        assert result.sandbox_environment_name == "Restricted env"
        assert result.allowed_domains == ["example.com"]

    @pytest.mark.django_db(transaction=True)
    def test_get_task_processing_context_preserves_empty_restricted_domains(self, activity_environment, test_task):
        sandbox_environment = SandboxEnvironment.objects.create(
            team=test_task.team,
            created_by=test_task.created_by,
            name="Restricted empty env",
            network_access_level=SandboxEnvironment.NetworkAccessLevel.CUSTOM,
            allowed_domains=[],
        )
        task_run = test_task.create_run(extra_state={"sandbox_environment_id": str(sandbox_environment.id)})

        input_data = GetTaskProcessingContextInput(run_id=str(task_run.id))
        result = async_to_sync(activity_environment.run)(get_task_processing_context, input_data)

        assert result.sandbox_environment_id == str(sandbox_environment.id)
        assert result.allowed_domains == []

    @pytest.mark.django_db(transaction=True)
    def test_get_task_processing_context_keeps_full_access_unrestricted(self, activity_environment, test_task):
        sandbox_environment = SandboxEnvironment.objects.create(
            team=test_task.team,
            created_by=test_task.created_by,
            name="Full access env",
            network_access_level=SandboxEnvironment.NetworkAccessLevel.FULL,
            allowed_domains=[],
        )
        task_run = test_task.create_run(extra_state={"sandbox_environment_id": str(sandbox_environment.id)})

        input_data = GetTaskProcessingContextInput(run_id=str(task_run.id))
        result = async_to_sync(activity_environment.run)(get_task_processing_context, input_data)

        assert result.sandbox_environment_id == str(sandbox_environment.id)
        assert result.allowed_domains is None

    @pytest.mark.django_db(transaction=True)
    def test_get_task_processing_context_rejects_other_users_private_sandbox_environment(
        self, activity_environment, test_task
    ):
        other_user = User.objects.create_user(
            email="victim@example.com",
            first_name="Victim",
            password="password",
        )
        OrganizationMembership.objects.create(
            user=other_user,
            organization_id=test_task.team.organization_id,
        )
        sandbox_environment = SandboxEnvironment.objects.create(
            team=test_task.team,
            created_by=other_user,
            name="Victim's private env",
            private=True,
            environment_variables={"SECRET_KEY": "secret_value"},
        )
        task_run = test_task.create_run(extra_state={"sandbox_environment_id": str(sandbox_environment.id)})

        input_data = GetTaskProcessingContextInput(run_id=str(task_run.id))

        with pytest.raises(TaskInvalidStateError):
            async_to_sync(activity_environment.run)(get_task_processing_context, input_data)

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.parametrize(
        "flag_value, expected",
        [
            (True, True),
            (False, False),
            (None, False),  # the activity coalesces None to False
        ],
    )
    def test_pr_loop_enabled_reflects_feature_flag(self, activity_environment, test_task, flag_value, expected):
        task_run = test_task.create_run()
        input_data = GetTaskProcessingContextInput(run_id=str(task_run.id))

        def feature_enabled(flag_key, **kwargs):
            if flag_key == "tasks-pr-loop":
                return flag_value
            return False

        with patch(
            "products.tasks.backend.temporal.process_task.activities.get_task_processing_context.posthoganalytics.feature_enabled",
            side_effect=feature_enabled,
        ) as feature_enabled_mock:
            result = async_to_sync(activity_environment.run)(get_task_processing_context, input_data)

        assert result.pr_loop_enabled is expected
        assert result.sandbox_event_ingest_enabled is False
        args, kwargs = feature_enabled_mock.call_args_list[0]
        assert args[0] == "tasks-pr-loop"
        assert kwargs["distinct_id"] == get_actor_distinct_id(test_task.created_by)
        org_id = str(test_task.team.organization_id)
        assert kwargs["groups"] == {"organization": org_id}
        assert kwargs["group_properties"] == {"organization": {"id": org_id}}
        sandbox_args, _sandbox_kwargs = feature_enabled_mock.call_args_list[1]
        assert sandbox_args[0] == SANDBOX_EVENT_INGEST_FEATURE_FLAG

    @pytest.mark.django_db(transaction=True)
    def test_pi_runtime_enables_event_ingest_without_bypassing_persistent_upload_rollout(
        self, activity_environment, test_task
    ):
        test_task.runtime = Task.Runtime.PI
        test_task.save(update_fields=["runtime"])
        task_run = test_task.create_run()
        input_data = GetTaskProcessingContextInput(run_id=str(task_run.id))

        with patch(
            "products.tasks.backend.temporal.process_task.activities.get_task_processing_context.posthoganalytics.feature_enabled",
            return_value=False,
        ):
            result = async_to_sync(activity_environment.run)(get_task_processing_context, input_data)

        assert result.sandbox_event_ingest_enabled is True
        assert result.agent_proxy_keep_stream_open is False

    @pytest.mark.django_db(transaction=True)
    def test_pi_runtime_respects_persistent_event_streaming_kill_switches(self, activity_environment, test_task):
        test_task.runtime = Task.Runtime.PI
        test_task.save(update_fields=["runtime"])
        task_run = test_task.create_run(
            extra_state={
                "sandbox_event_ingest_enabled": False,
                "agent_proxy_keep_stream_open": False,
            }
        )
        input_data = GetTaskProcessingContextInput(run_id=str(task_run.id))

        result = async_to_sync(activity_environment.run)(get_task_processing_context, input_data)

        assert result.sandbox_event_ingest_enabled is False
        assert result.agent_proxy_keep_stream_open is False

    @pytest.mark.django_db(transaction=True)
    def test_pr_loop_enabled_for_signal_report_origin_ignores_flag(self, activity_environment, test_task):
        # Signals implementation PRs are bot-authored and always opt into the PR
        # follow-up loop ("babysitting"), independent of the org-level `tasks-pr-loop`
        # rollout that gates other origins.
        test_task.origin_product = Task.OriginProduct.SIGNAL_REPORT
        test_task.save(update_fields=["origin_product"])
        task_run = test_task.create_run()
        input_data = GetTaskProcessingContextInput(run_id=str(task_run.id))

        def feature_enabled(flag_key, **kwargs):
            return False  # `tasks-pr-loop` disabled for the org

        with patch(
            "products.tasks.backend.temporal.process_task.activities.get_task_processing_context.posthoganalytics.feature_enabled",
            side_effect=feature_enabled,
        ) as feature_enabled_mock:
            result = async_to_sync(activity_environment.run)(get_task_processing_context, input_data)

        assert result.pr_loop_enabled is True
        # The signal_report origin short-circuits the gate, so the flag is never consulted.
        called_flags = [call.args[0] for call in feature_enabled_mock.call_args_list]
        assert "tasks-pr-loop" not in called_flags

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.parametrize(
        "pr_loop_flag, babysit_flag, expected, babysit_flag_consulted",
        [
            (False, True, False, False),
            (True, False, False, True),
            (True, True, True, True),
        ],
    )
    def test_pr_babysit_enabled_requires_both_the_loop_and_its_own_flag(
        self,
        activity_environment,
        test_task,
        pr_loop_flag,
        babysit_flag,
        expected,
        babysit_flag_consulted,
    ):
        task_run = test_task.create_run()
        input_data = GetTaskProcessingContextInput(run_id=str(task_run.id))

        def feature_enabled(flag_key, **kwargs):
            if flag_key == "tasks-pr-loop":
                return pr_loop_flag
            if flag_key == PR_BABYSIT_SNAPSHOT_FEATURE_FLAG:
                return babysit_flag
            return False

        with patch(
            "products.tasks.backend.temporal.process_task.activities.get_task_processing_context.posthoganalytics.feature_enabled",
            side_effect=feature_enabled,
        ) as feature_enabled_mock:
            result = async_to_sync(activity_environment.run)(get_task_processing_context, input_data)

        assert result.pr_babysit_enabled is expected
        called_flags = [call.args[0] for call in feature_enabled_mock.call_args_list]
        assert (PR_BABYSIT_SNAPSHOT_FEATURE_FLAG in called_flags) is babysit_flag_consulted

    def test_pr_babysit_snapshot_flag_fails_closed(self):
        with patch(
            "products.tasks.backend.temporal.process_task.activities.get_task_processing_context.posthoganalytics.feature_enabled",
            side_effect=RuntimeError("flag service failed"),
        ):
            assert (
                _is_pr_babysit_snapshot_enabled(
                    distinct_id="distinct-id",
                    organization_id="organization-id",
                    run_id="run-id",
                )
                is False
            )

    @pytest.mark.parametrize(
        "flag_value, expected",
        [
            (True, True),
            (False, False),
            (None, False),
        ],
    )
    def test_sandbox_event_ingest_flag_uses_organization_rollout(self, flag_value, expected):
        with patch(
            "products.tasks.backend.temporal.process_task.activities.get_task_processing_context.posthoganalytics.feature_enabled",
            return_value=flag_value,
        ) as feature_enabled_mock:
            assert (
                _is_sandbox_event_ingest_enabled(
                    distinct_id="distinct-id",
                    organization_id="organization-id",
                    run_id="run-id",
                )
                is expected
            )

        feature_enabled_mock.assert_called_once_with(
            SANDBOX_EVENT_INGEST_FEATURE_FLAG,
            distinct_id="distinct-id",
            groups={"organization": "organization-id"},
            group_properties={"organization": {"id": "organization-id"}},
            only_evaluate_locally=False,
            send_feature_flag_events=False,
        )

    def test_sandbox_event_ingest_flag_fails_closed(self):
        with patch(
            "products.tasks.backend.temporal.process_task.activities.get_task_processing_context.posthoganalytics.feature_enabled",
            side_effect=RuntimeError("flag service failed"),
        ):
            assert (
                _is_sandbox_event_ingest_enabled(
                    distinct_id="distinct-id",
                    organization_id="organization-id",
                    run_id="run-id",
                )
                is False
            )

    def test_sandbox_event_ingest_state_override_skips_flag_check(self):
        with patch(
            "products.tasks.backend.temporal.process_task.activities.get_task_processing_context.posthoganalytics.feature_enabled",
            return_value=False,
        ) as feature_enabled_mock:
            assert (
                _is_sandbox_event_ingest_enabled(
                    distinct_id="distinct-id",
                    organization_id="organization-id",
                    run_id="run-id",
                    state={"sandbox_event_ingest_enabled": True},
                )
                is True
            )

        feature_enabled_mock.assert_not_called()

    def test_sandbox_event_ingest_disabled_for_slack_runs_regardless_of_override(self):
        # Permission brokering and Slack approval cards only exist on the relay path;
        # a Slack run in ingest mode would stall forever on its first gated tool call.
        with patch(
            "products.tasks.backend.temporal.process_task.activities.get_task_processing_context.posthoganalytics.feature_enabled",
            return_value=True,
        ) as feature_enabled_mock:
            assert (
                _is_sandbox_event_ingest_enabled(
                    distinct_id="distinct-id",
                    organization_id="organization-id",
                    run_id="run-id",
                    state={"interaction_origin": "slack", "sandbox_event_ingest_enabled": True},
                )
                is False
            )

        feature_enabled_mock.assert_not_called()

    @pytest.mark.parametrize(
        "flag_value, expected",
        [
            (True, True),
            (False, False),
            (None, False),
        ],
    )
    def test_agent_proxy_keep_stream_open_flag_uses_organization_rollout(self, flag_value, expected):
        with patch(
            "products.tasks.backend.temporal.process_task.activities.get_task_processing_context.posthoganalytics.feature_enabled",
            return_value=flag_value,
        ) as feature_enabled_mock:
            assert (
                _is_agent_proxy_keep_stream_open_enabled(
                    distinct_id="distinct-id",
                    organization_id="organization-id",
                    run_id="run-id",
                )
                is expected
            )

        feature_enabled_mock.assert_called_once_with(
            AGENT_PROXY_KEEP_STREAM_OPEN_FEATURE_FLAG,
            distinct_id="distinct-id",
            groups={"organization": "organization-id"},
            group_properties={"organization": {"id": "organization-id"}},
            only_evaluate_locally=False,
            send_feature_flag_events=False,
        )

    def test_agent_proxy_keep_stream_open_flag_fails_closed(self):
        with patch(
            "products.tasks.backend.temporal.process_task.activities.get_task_processing_context.posthoganalytics.feature_enabled",
            side_effect=RuntimeError("flag service failed"),
        ):
            assert (
                _is_agent_proxy_keep_stream_open_enabled(
                    distinct_id="distinct-id",
                    organization_id="organization-id",
                    run_id="run-id",
                )
                is False
            )

    def test_agent_proxy_keep_stream_open_state_override_skips_flag_check(self):
        with patch(
            "products.tasks.backend.temporal.process_task.activities.get_task_processing_context.posthoganalytics.feature_enabled",
            return_value=False,
        ) as feature_enabled_mock:
            assert (
                _is_agent_proxy_keep_stream_open_enabled(
                    distinct_id="distinct-id",
                    organization_id="organization-id",
                    run_id="run-id",
                    state={"agent_proxy_keep_stream_open": True},
                )
                is True
            )

        feature_enabled_mock.assert_not_called()

    @pytest.mark.parametrize(
        "kill_switch_value, expected",
        [
            (True, False),
            (False, True),
            (None, True),
        ],
    )
    def test_rtk_enabled_defaults_on_with_kill_switch(self, kill_switch_value, expected):
        with patch(
            "products.tasks.backend.temporal.process_task.activities.get_task_processing_context.posthoganalytics.feature_enabled",
            return_value=kill_switch_value,
        ) as feature_enabled_mock:
            assert (
                _is_rtk_enabled(
                    distinct_id="distinct-id",
                    organization_id="organization-id",
                    run_id="run-id",
                )
                is expected
            )

        feature_enabled_mock.assert_called_once_with(
            RTK_DISABLED_FEATURE_FLAG,
            distinct_id="distinct-id",
            groups={"organization": "organization-id"},
            group_properties={"organization": {"id": "organization-id"}},
            only_evaluate_locally=False,
            send_feature_flag_events=False,
        )

    def test_rtk_enabled_fails_open_on_flag_error(self):
        with patch(
            "products.tasks.backend.temporal.process_task.activities.get_task_processing_context.posthoganalytics.feature_enabled",
            side_effect=RuntimeError("flag service failed"),
        ):
            assert (
                _is_rtk_enabled(
                    distinct_id="distinct-id",
                    organization_id="organization-id",
                    run_id="run-id",
                )
                is True
            )

    @pytest.mark.parametrize("state_override", [True, False])
    def test_rtk_enabled_state_override_applies_when_kill_switch_inactive(self, state_override):
        with patch(
            "products.tasks.backend.temporal.process_task.activities.get_task_processing_context.posthoganalytics.feature_enabled",
            return_value=False,
        ):
            assert (
                _is_rtk_enabled(
                    distinct_id="distinct-id",
                    organization_id="organization-id",
                    run_id="run-id",
                    state={"rtk_enabled": state_override},
                )
                is state_override
            )

    @pytest.mark.parametrize("state_override", [True, False])
    def test_rtk_kill_switch_beats_any_state_override(self, state_override):
        with patch(
            "products.tasks.backend.temporal.process_task.activities.get_task_processing_context.posthoganalytics.feature_enabled",
            return_value=True,
        ):
            assert (
                _is_rtk_enabled(
                    distinct_id="distinct-id",
                    organization_id="organization-id",
                    run_id="run-id",
                    state={"rtk_enabled": state_override},
                )
                is False
            )

    def test_rtk_flag_error_still_honors_state_override(self):
        with patch(
            "products.tasks.backend.temporal.process_task.activities.get_task_processing_context.posthoganalytics.feature_enabled",
            side_effect=RuntimeError("flag service failed"),
        ):
            assert (
                _is_rtk_enabled(
                    distinct_id="distinct-id",
                    organization_id="organization-id",
                    run_id="run-id",
                    state={"rtk_enabled": False},
                )
                is False
            )

    @pytest.mark.parametrize("flag_value, expected", [(True, True), (False, False)])
    @override_settings(TASKS_CONTINUE_AS_NEW_ENABLED=False)
    def test_continue_as_new_flag_uses_organization_rollout(self, flag_value, expected):
        with patch(
            "products.tasks.backend.temporal.process_task.activities.get_task_processing_context.posthoganalytics.feature_enabled",
            return_value=flag_value,
        ) as feature_enabled_mock:
            assert (
                _is_continue_as_new_enabled(
                    distinct_id="distinct-id",
                    organization_id="organization-id",
                    run_id="run-id",
                )
                is expected
            )

        feature_enabled_mock.assert_called_once_with(
            CONTINUE_AS_NEW_FEATURE_FLAG,
            distinct_id="distinct-id",
            groups={"organization": "organization-id"},
            group_properties={"organization": {"id": "organization-id"}},
            only_evaluate_locally=False,
            send_feature_flag_events=False,
        )

    @override_settings(TASKS_CONTINUE_AS_NEW_ENABLED=False)
    def test_continue_as_new_fails_closed_on_flag_error(self):
        with patch(
            "products.tasks.backend.temporal.process_task.activities.get_task_processing_context.posthoganalytics.feature_enabled",
            side_effect=RuntimeError("flag service failed"),
        ):
            assert (
                _is_continue_as_new_enabled(
                    distinct_id="distinct-id",
                    organization_id="organization-id",
                    run_id="run-id",
                )
                is False
            )

    @override_settings(TASKS_CONTINUE_AS_NEW_ENABLED=True)
    def test_continue_as_new_env_setting_force_enables_without_flag(self):
        # The force-on env setting must not depend on the flag service.
        with patch(
            "products.tasks.backend.temporal.process_task.activities.get_task_processing_context.posthoganalytics.feature_enabled",
        ) as feature_enabled_mock:
            assert (
                _is_continue_as_new_enabled(
                    distinct_id="distinct-id",
                    organization_id="organization-id",
                    run_id="run-id",
                )
                is True
            )
        feature_enabled_mock.assert_not_called()

    @pytest.mark.parametrize(
        "payload, expected",
        [
            ('{"origin_products": ["user_created"]}', True),
            (None, False),
        ],
    )
    def test_modal_vm_sandbox_flag_uses_organization_rollout(self, payload, expected):
        with patch(
            VM_FLAG_PAYLOAD_TARGET,
            return_value=payload,
        ) as payload_mock:
            assert (
                _resolve_modal_vm_sandbox(
                    distinct_id="distinct-id",
                    organization_id="organization-id",
                    run_id="run-id",
                    origin_product="user_created",
                    allowed_domains=None,
                    custom_image_available=True,
                ).use_vm_sandbox
                is expected
            )

        payload_mock.assert_called_once_with(
            MODAL_VM_SANDBOX_FEATURE_FLAG,
            distinct_id="distinct-id",
            groups={"organization": "organization-id"},
            group_properties={"organization": {"id": "organization-id"}},
            only_evaluate_locally=False,
            send_feature_flag_events=False,
        )

    def test_modal_vm_sandbox_flag_fails_closed(self):
        with patch(
            VM_FLAG_PAYLOAD_TARGET,
            side_effect=RuntimeError("flag service failed"),
        ):
            assert (
                _resolve_modal_vm_sandbox(
                    distinct_id="distinct-id",
                    organization_id="organization-id",
                    run_id="run-id",
                    origin_product="user_created",
                    allowed_domains=None,
                ).use_vm_sandbox
                is False
            )

    @pytest.mark.parametrize(
        "origin_product, custom_image_available, expected",
        [
            ("image_builder", False, True),
            ("user_created", False, False),
            ("user_created", True, True),
        ],
    )
    def test_modal_vm_sandbox_state_override_skips_flag_check(self, origin_product, custom_image_available, expected):
        with patch(
            VM_FLAG_PAYLOAD_TARGET,
            return_value=None,
        ) as payload_mock:
            assert (
                _resolve_modal_vm_sandbox(
                    distinct_id="distinct-id",
                    organization_id="organization-id",
                    run_id="run-id",
                    origin_product=origin_product,
                    allowed_domains=None,
                    custom_image_available=custom_image_available,
                    state={"use_modal_vm_sandbox": True},
                ).use_vm_sandbox
                is expected
            )

        payload_mock.assert_not_called()

    def test_modal_vm_sandbox_restricted_egress_forces_gvisor(self):
        with patch(
            VM_FLAG_PAYLOAD_TARGET,
            return_value='{"origin_products": ["user_created"]}',
        ) as payload_mock:
            assert (
                _resolve_modal_vm_sandbox(
                    distinct_id="distinct-id",
                    organization_id="organization-id",
                    run_id="run-id",
                    origin_product="user_created",
                    allowed_domains=["github.com"],
                ).use_vm_sandbox
                is False
            )

        payload_mock.assert_not_called()

    def test_modal_vm_sandbox_restricted_egress_overrides_state_override(self):
        with patch(
            VM_FLAG_PAYLOAD_TARGET,
            return_value='{"origin_products": ["user_created"]}',
        ) as payload_mock:
            assert (
                _resolve_modal_vm_sandbox(
                    distinct_id="distinct-id",
                    organization_id="organization-id",
                    run_id="run-id",
                    origin_product="user_created",
                    allowed_domains=["github.com"],
                    state={"use_modal_vm_sandbox": True},
                ).use_vm_sandbox
                is False
            )

        payload_mock.assert_not_called()

    def test_modal_vm_sandbox_restricted_egress_overrides_default_base(self):
        # A restricted run cannot use any VM routing source until the independent network-policy
        # flag is enabled, so the runtime flag is not consulted on this path.
        with patch(
            VM_FLAG_PAYLOAD_TARGET,
            return_value='{"default_base_origin_products": ["user_created"]}',
        ) as payload_mock:
            assert (
                _resolve_modal_vm_sandbox(
                    distinct_id="distinct-id",
                    organization_id="organization-id",
                    run_id="run-id",
                    origin_product="user_created",
                    allowed_domains=["github.com"],
                ).use_vm_sandbox
                is False
            )

        payload_mock.assert_not_called()

    def test_modal_vm_sandbox_restricted_egress_uses_vm_when_provider_policy_is_enabled(self):
        with patch(
            VM_FLAG_PAYLOAD_TARGET,
            return_value='{"origin_products": ["user_created"]}',
        ):
            decision = _resolve_modal_vm_sandbox(
                distinct_id="distinct-id",
                organization_id="organization-id",
                run_id="run-id",
                origin_product="user_created",
                allowed_domains=["github.com"],
                use_modal_network_allowlist=True,
                custom_image_available=True,
            )

        assert decision.use_vm_sandbox is True

    def test_modal_vm_sandbox_restricted_state_override_requires_provider_policy(self):
        with patch(VM_FLAG_PAYLOAD_TARGET, return_value=None) as payload_mock:
            decision = _resolve_modal_vm_sandbox(
                distinct_id="distinct-id",
                organization_id="organization-id",
                run_id="run-id",
                origin_product="image_builder",
                allowed_domains=["github.com"],
                use_modal_network_allowlist=True,
                state={"use_modal_vm_sandbox": True},
            )

        assert decision.use_vm_sandbox is True
        payload_mock.assert_not_called()

    def test_modal_vm_sandbox_restricted_default_base_requires_provider_policy(self):
        with patch(
            VM_FLAG_PAYLOAD_TARGET,
            return_value='{"default_base_origin_products": ["user_created"]}',
        ):
            decision = _resolve_modal_vm_sandbox(
                distinct_id="distinct-id",
                organization_id="organization-id",
                run_id="run-id",
                origin_product="user_created",
                allowed_domains=["github.com"],
                use_modal_network_allowlist=True,
            )

        assert decision.use_vm_sandbox is True

    def test_modal_vm_sandbox_false_state_override_forces_gvisor_over_default_base(self):
        # A trusted server-set use_modal_vm_sandbox=False forces gVisor even when the org's payload
        # would place this origin on the VM base; the bool override also skips the flag fetch.
        with patch(
            VM_FLAG_PAYLOAD_TARGET,
            return_value='{"default_base_origin_products": ["user_created"]}',
        ) as payload_mock:
            assert (
                _resolve_modal_vm_sandbox(
                    distinct_id="distinct-id",
                    organization_id="organization-id",
                    run_id="run-id",
                    origin_product="user_created",
                    allowed_domains=None,
                    custom_image_available=True,
                    state={"use_modal_vm_sandbox": False},
                ).use_vm_sandbox
                is False
            )

        payload_mock.assert_not_called()

    @pytest.mark.parametrize(
        "origin_product, payload, custom_image_available, expected",
        [
            ("user_created", None, True, False),
            ("signals_scout", None, False, False),
            ("signals_scout", {"origin_products": ["signals_scout"]}, False, False),
            ("signals_scout", ["signals_scout", "user_created"], False, False),
            ("signals_scout", {"origin_products": ["signals_scout"]}, True, True),
            ("image_builder", {"origin_products": ["image_builder"]}, False, True),
            ("user_created", {"origin_products": ["signals_scout"]}, True, False),
            ("user_created", '{"origin_products": ["user_created"]}', False, False),
            ("user_created", '{"origin_products": ["user_created"]}', True, True),
            # default_base_origin_products: listed origins run on the bare VM base image
            # with no custom image at all — the "VM as default" rollout knob.
            (
                "user_created",
                {"origin_products": ["user_created"], "default_base_origin_products": ["user_created"]},
                False,
                True,
            ),
            # default-base alone (no origin_products) is enough for a no-custom-image run.
            ("user_created", {"default_base_origin_products": ["user_created"]}, False, True),
            # the waiver is scoped per origin — an unlisted origin still gets gVisor.
            ("signals_scout", {"default_base_origin_products": ["user_created"]}, False, False),
            ("signals_scout", {"origin_product_rollout_percentages": {"signals_scout": 100}}, False, True),
            # origin_products membership alone does NOT waive the custom-image requirement.
            (
                "user_created",
                {"origin_products": ["user_created"], "default_base_origin_products": ["signals_scout"]},
                False,
                False,
            ),
        ],
    )
    def test_modal_vm_sandbox_origin_product_gating(self, origin_product, payload, custom_image_available, expected):
        with patch(
            VM_FLAG_PAYLOAD_TARGET,
            return_value=payload,
        ):
            assert (
                _resolve_modal_vm_sandbox(
                    distinct_id="distinct-id",
                    organization_id="organization-id",
                    run_id="run-id",
                    origin_product=origin_product,
                    allowed_domains=None,
                    custom_image_available=custom_image_available,
                ).use_vm_sandbox
                is expected
            )

    @pytest.mark.parametrize(
        "payload, expected",
        [
            (None, set()),
            (["a", "b"], {"a", "b"}),
            ({"origin_products": ["x"]}, {"x"}),
            ('{"origin_products": ["y", "z"]}', {"y", "z"}),
            ("not-json", set()),
            ({"other": 1}, set()),
            ([1, 2], set()),
        ],
    )
    def test_vm_sandbox_allowed_origin_products_parsing(self, payload, expected):
        assert vm_sandbox_allowed_origin_products(payload) == expected

    @pytest.mark.parametrize(
        "payload, expected",
        [
            (None, set()),
            ({"default_base_origin_products": ["user_created"]}, {"user_created"}),
            ('{"default_base_origin_products": ["a", "b"]}', {"a", "b"}),
            # Distinct from vm_sandbox_allowed_origin_products: read only from the explicit
            # dict key, and a bare list is never an opt-in (it keeps origin_products meaning).
            ({"origin_products": ["user_created"]}, set()),
            (["user_created"], set()),
            ("not-json", set()),
            ({"default_base_origin_products": [1, 2]}, set()),
        ],
    )
    def test_vm_sandbox_default_base_origin_products_parsing(self, payload, expected):
        assert vm_sandbox_default_base_origin_products(payload) == expected

    @pytest.mark.parametrize(
        "payload,expected",
        [
            ({"origin_product_rollout_percentages": {"signals_scout": 10}}, {"signals_scout": 10.0}),
            ('{"origin_product_rollout_percentages":{"signals_scout":12.5}}', {"signals_scout": 12.5}),
            ({"origin_product_rollout_percentages": {"negative": -1, "large": 101, "bool": True}}, {}),
            ({"origin_product_rollout_percentages": ["signals_scout"]}, {}),
            (None, {}),
        ],
    )
    def test_vm_sandbox_origin_rollout_percentages_parsing(self, payload, expected):
        assert vm_sandbox_origin_rollout_percentages(payload) == expected

    def test_vm_sandbox_origin_percentage_rollout_is_stable_and_distributed(self):
        percentages = {"signals_scout": 10.0}
        decisions = [
            vm_sandbox_origin_in_rollout("signals_scout", f"run-{index}", percentages) for index in range(1000)
        ]

        assert decisions == [
            vm_sandbox_origin_in_rollout("signals_scout", f"run-{index}", percentages) for index in range(1000)
        ]
        assert 70 <= sum(decisions) <= 130
        assert not vm_sandbox_origin_in_rollout("onboarding", "run-1", percentages)
        assert vm_sandbox_origin_in_rollout(None, "run-1", {"": 50}) == vm_sandbox_origin_in_rollout(
            "", "run-1", {"": 50}
        )

    @pytest.mark.parametrize(
        "payload, expected",
        [
            (None, None),
            ({"default_custom_image": "posthog-dev-stack"}, "posthog-dev-stack"),
            ('{"default_custom_image": "posthog-dev-stack"}', "posthog-dev-stack"),
            ({"default_custom_image": "  padded  "}, "padded"),
            # Empty/whitespace/non-string values and payloads without the key must resolve
            # to "no default", never crash routing — the payload is human-edited flag JSON.
            ({"default_custom_image": ""}, None),
            ({"default_custom_image": "   "}, None),
            ({"default_custom_image": 3}, None),
            ({"origin_products": ["user_created"]}, None),
            (["posthog-dev-stack"], None),
            ("not-json", None),
        ],
    )
    def test_vm_sandbox_default_custom_image_parsing(self, payload, expected):
        assert vm_sandbox_default_custom_image(payload) == expected

    @pytest.mark.parametrize(
        "origin_product, expected",
        [
            # Default-base origin resolves to VM and picks up the org's default image.
            (
                "user_created",
                VmSandboxDecision(use_vm_sandbox=True, default_custom_image="posthog-dev-stack"),
            ),
            # An origin that stays on gVisor must not leak the (VM-only) default image out.
            ("signals_scout", VmSandboxDecision(use_vm_sandbox=False)),
        ],
    )
    def test_modal_vm_sandbox_default_custom_image_resolution(self, origin_product, expected):
        with patch(
            VM_FLAG_PAYLOAD_TARGET,
            return_value='{"default_base_origin_products": ["user_created"], "default_custom_image": "posthog-dev-stack"}',
        ):
            assert (
                _resolve_modal_vm_sandbox(
                    distinct_id="distinct-id",
                    organization_id="organization-id",
                    run_id="run-id",
                    origin_product=origin_product,
                    allowed_domains=None,
                )
                == expected
            )

    def test_modal_vm_sandbox_state_override_never_gets_default_custom_image(self):
        # Image-builder runs (trusted state override) must keep layering on the plain VM
        # base: the flag is never consulted, so the org default image cannot apply.
        with patch(
            VM_FLAG_PAYLOAD_TARGET,
            return_value='{"default_base_origin_products": ["image_builder"], "default_custom_image": "posthog-dev-stack"}',
        ) as payload_mock:
            decision = _resolve_modal_vm_sandbox(
                distinct_id="distinct-id",
                organization_id="organization-id",
                run_id="run-id",
                origin_product="image_builder",
                allowed_domains=None,
                state={"use_modal_vm_sandbox": True},
            )

        assert decision == VmSandboxDecision(use_vm_sandbox=True, default_custom_image=None)
        payload_mock.assert_not_called()

    @pytest.mark.parametrize(
        "state,expected",
        [
            (None, True),
            ({}, True),
            ({"burstable_sandbox_resources_enabled": True}, True),
            ({"burstable_sandbox_resources_enabled": False}, False),
        ],
    )
    def test_burstable_sandbox_resources_defaults_true_and_respects_state(self, state, expected):
        assert _is_burstable_sandbox_resources_enabled(run_id="run-id", state=state) is expected

    @pytest.mark.django_db(transaction=True)
    def test_get_task_processing_context_uses_sandbox_event_ingest_state_override(
        self, activity_environment, test_task
    ):
        task_run = test_task.create_run(extra_state={"sandbox_event_ingest_enabled": True})
        input_data = GetTaskProcessingContextInput(run_id=str(task_run.id))

        with patch(
            "products.tasks.backend.temporal.process_task.activities.get_task_processing_context.posthoganalytics.feature_enabled",
            return_value=False,
        ):
            result = async_to_sync(activity_environment.run)(get_task_processing_context, input_data)

        assert result.sandbox_event_ingest_enabled is True

    @pytest.mark.django_db(transaction=True)
    def test_get_task_processing_context_enables_directory_resume_snapshots(self, activity_environment, test_task):
        task_run = test_task.create_run()
        input_data = GetTaskProcessingContextInput(run_id=str(task_run.id))

        with patch(
            "products.tasks.backend.temporal.process_task.activities.get_task_processing_context.posthoganalytics.feature_enabled",
            return_value=False,
        ):
            result = async_to_sync(activity_environment.run)(get_task_processing_context, input_data)

        assert result.use_modal_resume_snapshots is True
        assert result.use_modal_directory_resume_snapshots is True

    @pytest.mark.django_db(transaction=True)
    def test_get_task_processing_context_applies_org_default_custom_image(self, activity_environment, test_task):
        # Wiring guard for the elif chain in the activity body: a VM run with no
        # user/environment image must land the payload's default in custom_image_name.
        task_run = test_task.create_run()
        input_data = GetTaskProcessingContextInput(run_id=str(task_run.id))

        with patch(
            VM_FLAG_PAYLOAD_TARGET,
            return_value='{"default_base_origin_products": ["user_created"], "default_custom_image": "posthog-dev-stack"}',
        ):
            result = async_to_sync(activity_environment.run)(get_task_processing_context, input_data)

        assert result.use_modal_vm_sandbox is True
        assert result.custom_image_name == "posthog-dev-stack"

    @pytest.mark.django_db(transaction=True)
    def test_get_task_processing_context_exposes_ci_prompt(self, activity_environment, test_task):
        custom_prompt = "Re-run the failed mypy checks and push a fix."
        test_task.ci_prompt = custom_prompt
        test_task.save(update_fields=["ci_prompt"])

        task_run = test_task.create_run()
        input_data = GetTaskProcessingContextInput(run_id=str(task_run.id))
        result = async_to_sync(activity_environment.run)(get_task_processing_context, input_data)

        assert result.ci_prompt == custom_prompt

    @pytest.mark.django_db(transaction=True)
    def test_get_task_processing_context_creates_native_pi_session(self, activity_environment, test_task):
        test_task.runtime = Task.Runtime.PI
        test_task.save(update_fields=["runtime"])
        task_run = test_task.create_run()

        input_data = GetTaskProcessingContextInput(run_id=str(task_run.id))
        result = async_to_sync(activity_environment.run)(get_task_processing_context, input_data)

        task_run.refresh_from_db()
        assert task_run.active_task_session is not None
        assert task_run.active_task_session.object_storage_key is None
        assert task_run.active_task_session.team_id == test_task.team_id
        assert result.task_runtime == "pi"
        assert result.runtime_adapter is None
        assert result.provider is None
        assert result.model is None
        assert result.reasoning_effort is None
        assert result.initial_permission_mode is None
