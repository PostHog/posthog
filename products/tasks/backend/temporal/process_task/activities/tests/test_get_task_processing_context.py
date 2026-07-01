import pytest
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import override_settings

from asgiref.sync import async_to_sync

from posthog.models import OrganizationMembership, User
from posthog.models.user_integration import UserIntegration

from products.tasks.backend.constants import (
    AGENT_PROXY_KEEP_STREAM_OPEN_FEATURE_FLAG,
    MODAL_DIRECTORY_RESUME_SNAPSHOTS_FEATURE_FLAG,
    MODAL_VM_SANDBOX_FEATURE_FLAG,
    SANDBOX_EVENT_INGEST_FEATURE_FLAG,
)
from products.tasks.backend.exceptions import TaskInvalidStateError, TaskRunNotReadyError
from products.tasks.backend.models import SandboxEnvironment, Task
from products.tasks.backend.temporal.process_task.activities.get_task_processing_context import (
    GetTaskProcessingContextInput,
    TaskProcessingContext,
    _is_agent_proxy_keep_stream_open_enabled,
    _is_burstable_sandbox_resources_enabled,
    _is_modal_vm_sandbox_enabled,
    _is_sandbox_event_ingest_enabled,
    _vm_sandbox_allowed_origin_products,
    get_task_processing_context,
)
from products.tasks.backend.temporal.process_task.utils import get_actor_distinct_id


@pytest.mark.requires_secrets
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
    def test_get_task_processing_context_requires_slack_actor(self, activity_environment, team, user):
        task = Task.objects.create(
            team=team,
            created_by=user,
            title="Slack task without actor",
            description="Summarize the thread",
            origin_product=Task.OriginProduct.SLACK,
        )
        task_run = task.create_run(extra_state={"interaction_origin": "slack", "pr_authorship_mode": "user"})

        with pytest.raises(TaskInvalidStateError):
            async_to_sync(activity_environment.run)(
                get_task_processing_context,
                GetTaskProcessingContextInput(run_id=str(task_run.id)),
            )

    @pytest.mark.django_db(transaction=True)
    def test_get_task_processing_context_exposes_general_task_kind(self, activity_environment, team, user):
        task = Task.objects.create(
            team=team,
            created_by=user,
            title="General Slack task",
            description="Summarize the thread",
            origin_product=Task.OriginProduct.SLACK,
            task_kind=Task.TaskKind.GENERAL,
        )
        task_run = task.create_run(
            extra_state={
                "interaction_origin": "slack",
                "task_kind": Task.TaskKind.GENERAL,
                "slack_actor_user_id": user.id,
            }
        )

        result = async_to_sync(activity_environment.run)(
            get_task_processing_context,
            GetTaskProcessingContextInput(run_id=str(task_run.id)),
        )

        assert result.task_kind == Task.TaskKind.GENERAL
        assert result.has_github_credentials is False

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
        "flag_value, expected",
        [
            (True, True),
            (False, False),
            (None, False),
        ],
    )
    def test_modal_vm_sandbox_flag_uses_organization_rollout(self, flag_value, expected):
        with (
            patch(
                "products.tasks.backend.temporal.process_task.activities.get_task_processing_context.posthoganalytics.feature_enabled",
                return_value=flag_value,
            ) as feature_enabled_mock,
            patch(
                "products.tasks.backend.temporal.process_task.activities.get_task_processing_context.posthoganalytics.get_feature_flag_payload",
                return_value=["user_created"],
            ),
        ):
            assert (
                _is_modal_vm_sandbox_enabled(
                    distinct_id="distinct-id",
                    organization_id="organization-id",
                    run_id="run-id",
                    origin_product="user_created",
                    allowed_domains=None,
                )
                is expected
            )

        feature_enabled_mock.assert_called_once_with(
            MODAL_VM_SANDBOX_FEATURE_FLAG,
            distinct_id="distinct-id",
            groups={"organization": "organization-id"},
            group_properties={"organization": {"id": "organization-id"}},
            only_evaluate_locally=False,
            send_feature_flag_events=False,
        )

    def test_modal_vm_sandbox_flag_fails_closed(self):
        with patch(
            "products.tasks.backend.temporal.process_task.activities.get_task_processing_context.posthoganalytics.feature_enabled",
            side_effect=RuntimeError("flag service failed"),
        ):
            assert (
                _is_modal_vm_sandbox_enabled(
                    distinct_id="distinct-id",
                    organization_id="organization-id",
                    run_id="run-id",
                    origin_product="user_created",
                    allowed_domains=None,
                )
                is False
            )

    def test_modal_vm_sandbox_state_override_skips_flag_check(self):
        with patch(
            "products.tasks.backend.temporal.process_task.activities.get_task_processing_context.posthoganalytics.feature_enabled",
            return_value=False,
        ) as feature_enabled_mock:
            assert (
                _is_modal_vm_sandbox_enabled(
                    distinct_id="distinct-id",
                    organization_id="organization-id",
                    run_id="run-id",
                    origin_product="user_created",
                    allowed_domains=None,
                    state={"use_modal_vm_sandbox": True},
                )
                is True
            )

        feature_enabled_mock.assert_not_called()

    def test_modal_vm_sandbox_restricted_egress_forces_gvisor(self):
        with patch(
            "products.tasks.backend.temporal.process_task.activities.get_task_processing_context.posthoganalytics.feature_enabled",
            return_value=True,
        ) as feature_enabled_mock:
            assert (
                _is_modal_vm_sandbox_enabled(
                    distinct_id="distinct-id",
                    organization_id="organization-id",
                    run_id="run-id",
                    origin_product="user_created",
                    allowed_domains=["github.com"],
                )
                is False
            )

        feature_enabled_mock.assert_not_called()

    def test_modal_vm_sandbox_restricted_egress_overrides_state_override(self):
        with patch(
            "products.tasks.backend.temporal.process_task.activities.get_task_processing_context.posthoganalytics.feature_enabled",
            return_value=True,
        ) as feature_enabled_mock:
            assert (
                _is_modal_vm_sandbox_enabled(
                    distinct_id="distinct-id",
                    organization_id="organization-id",
                    run_id="run-id",
                    origin_product="user_created",
                    allowed_domains=["github.com"],
                    state={"use_modal_vm_sandbox": True},
                )
                is False
            )

        feature_enabled_mock.assert_not_called()

    @pytest.mark.parametrize(
        "origin_product, payload, expected",
        [
            ("user_created", None, False),
            ("signals_scout", None, False),
            ("signals_scout", {"origin_products": ["signals_scout"]}, True),
            ("signals_scout", ["signals_scout", "user_created"], True),
            ("user_created", {"origin_products": ["signals_scout"]}, False),
            ("user_created", '{"origin_products": ["user_created"]}', True),
        ],
    )
    def test_modal_vm_sandbox_origin_product_gating(self, origin_product, payload, expected):
        with (
            patch(
                "products.tasks.backend.temporal.process_task.activities.get_task_processing_context.posthoganalytics.feature_enabled",
                return_value=True,
            ),
            patch(
                "products.tasks.backend.temporal.process_task.activities.get_task_processing_context.posthoganalytics.get_feature_flag_payload",
                return_value=payload,
            ),
        ):
            assert (
                _is_modal_vm_sandbox_enabled(
                    distinct_id="distinct-id",
                    organization_id="organization-id",
                    run_id="run-id",
                    origin_product=origin_product,
                    allowed_domains=None,
                )
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
        assert _vm_sandbox_allowed_origin_products(payload) == expected

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
    @pytest.mark.parametrize(
        "legacy_resume_snapshots, directory_resume_snapshots, run_state, expected_resume_snapshots",
        [
            (True, False, {}, True),
            (False, True, {}, True),
            (False, False, {}, False),
            (False, False, {"use_modal_directory_resume_snapshots": True}, False),
            (False, True, {"use_modal_directory_resume_snapshots": False}, True),
        ],
    )
    def test_get_task_processing_context_combines_legacy_and_directory_resume_snapshot_flags(
        self,
        activity_environment,
        test_task,
        legacy_resume_snapshots,
        directory_resume_snapshots,
        run_state,
        expected_resume_snapshots,
    ):
        task_run = test_task.create_run(extra_state=run_state)
        input_data = GetTaskProcessingContextInput(run_id=str(task_run.id))

        def feature_enabled(flag_key, *args, **kwargs):
            if flag_key == MODAL_DIRECTORY_RESUME_SNAPSHOTS_FEATURE_FLAG:
                return directory_resume_snapshots
            return False

        with (
            override_settings(TASKS_USE_MODAL_RESUME_SNAPSHOTS=legacy_resume_snapshots),
            patch(
                "products.tasks.backend.temporal.process_task.activities.get_task_processing_context.posthoganalytics.feature_enabled",
                side_effect=feature_enabled,
            ),
        ):
            result = async_to_sync(activity_environment.run)(get_task_processing_context, input_data)

        assert result.use_modal_resume_snapshots is expected_resume_snapshots
        assert result.use_modal_directory_resume_snapshots is directory_resume_snapshots

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
    def test_get_task_processing_context_exposes_runtime_metadata(self, activity_environment, test_task):
        task_run = test_task.create_run(
            extra_state={
                "runtime_adapter": "codex",
                "provider": "openai",
                "model": "gpt-5.3-codex",
                "reasoning_effort": "high",
                "initial_permission_mode": "plan",
            }
        )

        input_data = GetTaskProcessingContextInput(run_id=str(task_run.id))
        result = async_to_sync(activity_environment.run)(get_task_processing_context, input_data)

        assert result.runtime_adapter == "codex"
        assert result.provider == "openai"
        assert result.model == "gpt-5.3-codex"
        assert result.reasoning_effort == "high"
        assert result.initial_permission_mode == "plan"
