import importlib

from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings

from products.slack_app.backend.slack_thread import SlackThreadHandler

_post_slack_update_module = importlib.import_module(
    "products.tasks.backend.temporal.process_task.activities.post_slack_update"
)
PostSlackUpdateInput = _post_slack_update_module.PostSlackUpdateInput
post_slack_update = _post_slack_update_module.post_slack_update


@override_settings(SITE_URL="http://localhost:8000")
class TestPostSlackUpdate(TestCase):
    def setUp(self):
        self.slack_thread_context = {
            "integration_id": 1,
            "channel": "C001",
            "thread_ts": "1111.0000",
            "user_message_ts": "2222.0000",
        }
        # Default the access gate to allow so existing call/URL assertions remain meaningful;
        # tests that exercise the deny / error paths re-patch it locally.
        self._access_patcher = patch(
            "products.tasks.backend.temporal.process_task.activities.post_slack_update.has_tasks_access",
            return_value=True,
        )
        self._access_patcher.start()
        self.addCleanup(self._access_patcher.stop)
        # The PR-opened notification path resolves the reply target from a live
        # SlackThreadTaskMapping. Default that lookup to "no mapping" so tests
        # that don't exercise multiplayer tagging aren't forced to seed the
        # model; tests that care override the mock locally.
        self._mapping_patcher = patch("products.slack_app.backend.models.SlackThreadTaskMapping")
        mock_mapping_class = self._mapping_patcher.start()
        mock_mapping_class.objects.filter.return_value.first.return_value = None
        self.addCleanup(self._mapping_patcher.stop)

    def _make_mock_run(self, status: str, **kwargs):
        mock_run = MagicMock()
        mock_run.status = status
        mock_run.task.team_id = 1
        mock_run.task_id = 10
        mock_run.id = "run-1"
        mock_run.output = {}
        mock_run.state = {}
        for k, v in kwargs.items():
            setattr(mock_run, k, v)
        return mock_run

    @patch.object(SlackThreadHandler, "post_completion")
    @patch.object(SlackThreadHandler, "update_reaction")
    @patch.object(SlackThreadHandler, "__init__", return_value=None)
    @patch("products.tasks.backend.models.TaskRun")
    def test_completed_run_updates_reaction_to_hedgehog(
        self, mock_task_run_class, mock_handler_init, mock_update_reaction, mock_post_completion
    ):
        mock_run = self._make_mock_run(
            mock_task_run_class.Status.COMPLETED,
            output={"pr_url": "https://github.com/org/repo/pull/1"},
        )
        mock_task_run_class.objects.select_related.return_value.get.return_value = mock_run

        post_slack_update(PostSlackUpdateInput(run_id="run-1", slack_thread_context=self.slack_thread_context))

        mock_update_reaction.assert_called_once_with("hedgehog")
        mock_post_completion.assert_called_once()

    @patch.object(SlackThreadHandler, "post_error")
    @patch.object(SlackThreadHandler, "update_reaction")
    @patch.object(SlackThreadHandler, "__init__", return_value=None)
    @patch("products.tasks.backend.models.TaskRun")
    def test_failed_run_updates_reaction_to_x(
        self, mock_task_run_class, mock_handler_init, mock_update_reaction, mock_post_error
    ):
        mock_run = self._make_mock_run(
            mock_task_run_class.Status.FAILED,
            error_message="Something went wrong",
        )
        mock_task_run_class.objects.select_related.return_value.get.return_value = mock_run

        post_slack_update(PostSlackUpdateInput(run_id="run-1", slack_thread_context=self.slack_thread_context))

        mock_update_reaction.assert_called_once_with("x")
        mock_post_error.assert_called_once()

    @patch.object(SlackThreadHandler, "post_cancelled")
    @patch.object(SlackThreadHandler, "update_reaction")
    @patch.object(SlackThreadHandler, "__init__", return_value=None)
    @patch("products.tasks.backend.models.TaskRun")
    def test_cancelled_run_posts_cancelled_message(
        self, mock_task_run_class, mock_handler_init, mock_update_reaction, mock_post_cancelled
    ):
        mock_run = self._make_mock_run(mock_task_run_class.Status.CANCELLED)
        mock_task_run_class.objects.select_related.return_value.get.return_value = mock_run

        post_slack_update(PostSlackUpdateInput(run_id="run-1", slack_thread_context=self.slack_thread_context))

        mock_update_reaction.assert_called_once_with("hedgehog")
        mock_post_cancelled.assert_called_once()

    @patch.object(SlackThreadHandler, "post_or_update_progress")
    @patch.object(SlackThreadHandler, "__init__", return_value=None)
    @patch("products.tasks.backend.models.TaskRun")
    def test_in_progress_run_posts_stage(self, mock_task_run_class, mock_handler_init, mock_post_progress):
        mock_run = self._make_mock_run(
            mock_task_run_class.Status.IN_PROGRESS,
            stage="Cloning repository",
        )
        mock_task_run_class.objects.select_related.return_value.get.return_value = mock_run

        post_slack_update(PostSlackUpdateInput(run_id="run-1", slack_thread_context=self.slack_thread_context))

        mock_post_progress.assert_called_once()
        assert mock_post_progress.call_args[0][0] == "Cloning repository"

    @patch.object(SlackThreadHandler, "delete_progress")
    @patch.object(SlackThreadHandler, "update_reaction")
    @patch.object(SlackThreadHandler, "post_or_update_progress")
    @patch.object(SlackThreadHandler, "post_pr_opened")
    @patch.object(SlackThreadHandler, "__init__", return_value=None)
    @patch("products.tasks.backend.models.TaskRun")
    def test_in_progress_with_pr_keeps_eyes_reaction_and_deletes_progress(
        self,
        mock_task_run_class,
        mock_handler_init,
        _mock_post_pr_opened,
        mock_post_progress,
        mock_update_reaction,
        mock_delete_progress,
    ):
        mock_run = self._make_mock_run(
            mock_task_run_class.Status.IN_PROGRESS,
            stage="Building",
            output={"pr_url": "https://github.com/org/repo/pull/1"},
        )
        mock_task_run_class.objects.select_related.return_value.get.return_value = mock_run

        post_slack_update(PostSlackUpdateInput(run_id="run-1", slack_thread_context=self.slack_thread_context))

        mock_post_progress.assert_not_called()
        # Task is still running (PR opened mid-run) — reaction stays :eyes:, not :hedgehog:.
        mock_update_reaction.assert_called_once_with("eyes")
        mock_delete_progress.assert_called_once()

    @patch("products.slack_app.backend.models.SlackThreadTaskMapping")
    @patch.object(SlackThreadHandler, "delete_progress")
    @patch.object(SlackThreadHandler, "update_reaction")
    @patch.object(SlackThreadHandler, "post_or_update_progress")
    @patch.object(SlackThreadHandler, "post_pr_opened")
    @patch.object(SlackThreadHandler, "__init__", return_value=None)
    @patch("products.tasks.backend.models.TaskRun")
    def test_in_progress_with_pr_posts_notification_once(
        self,
        mock_task_run_class,
        mock_handler_init,
        mock_post_pr_opened,
        mock_post_progress,
        mock_update_reaction,
        mock_delete_progress,
        mock_mapping_class,
    ):
        mock_run = self._make_mock_run(
            mock_task_run_class.Status.IN_PROGRESS,
            stage="Building",
            output={"pr_url": "https://github.com/org/repo/pull/1"},
            state={},
        )
        mock_task_run_class.objects.select_related.return_value.get.return_value = mock_run
        # Reply target now resolves from the live mapping, not the workflow context.
        mock_mapping = MagicMock()
        mock_mapping.latest_actor_slack_user_id = "U123"
        mock_mapping.mentioning_slack_user_id = "U_ORIG"
        mock_mapping_class.objects.filter.return_value.first.return_value = mock_mapping

        post_slack_update(
            PostSlackUpdateInput(
                run_id="run-1",
                slack_thread_context={
                    **self.slack_thread_context,
                    "mentioning_slack_user_id": "U_ORIG",
                },
            )
        )

        mock_post_pr_opened.assert_called_once_with(
            "https://github.com/org/repo/pull/1",
            "http://localhost:8000/project/1/tasks/10?runId=run-1",
            reply_target_slack_user_id="U123",
        )
        mock_update_reaction.assert_called_once_with("eyes")
        mock_delete_progress.assert_called_once()
        mock_post_progress.assert_not_called()
        mock_task_run_class.update_state_atomic.assert_called_once_with(
            "run-1",
            updates={
                "slack_pr_opened_notified": True,
                "slack_notified_pr_url": "https://github.com/org/repo/pull/1",
            },
        )
        mock_run.save.assert_not_called()

    @patch.object(SlackThreadHandler, "post_completion")
    @patch.object(SlackThreadHandler, "delete_progress")
    @patch.object(SlackThreadHandler, "update_reaction")
    @patch.object(SlackThreadHandler, "__init__", return_value=None)
    @patch("products.tasks.backend.models.TaskRun")
    def test_timed_out_run_silently_deletes_progress(
        self, mock_task_run_class, mock_handler_init, mock_update_reaction, mock_delete_progress, mock_post_completion
    ):
        mock_run = self._make_mock_run(
            mock_task_run_class.Status.COMPLETED,
            error_message="Run timed out due to inactivity",
            output={},
        )
        mock_task_run_class.objects.select_related.return_value.get.return_value = mock_run

        post_slack_update(PostSlackUpdateInput(run_id="run-1", slack_thread_context=self.slack_thread_context))

        mock_update_reaction.assert_called_once_with("hedgehog")
        mock_delete_progress.assert_called_once()
        mock_post_completion.assert_not_called()

    @patch.object(SlackThreadHandler, "post_pr_opened_sandbox_cleaned")
    @patch.object(SlackThreadHandler, "delete_progress")
    @patch.object(SlackThreadHandler, "update_reaction")
    @patch.object(SlackThreadHandler, "__init__", return_value=None)
    @patch("products.tasks.backend.models.TaskRun")
    def test_completed_pr_run_after_cleanup_posts_cleaned_message(
        self,
        mock_task_run_class,
        mock_handler_init,
        mock_update_reaction,
        mock_delete_progress,
        mock_post_pr_opened_sandbox_cleaned,
    ):
        mock_run = self._make_mock_run(
            mock_task_run_class.Status.COMPLETED,
            output={"pr_url": "https://github.com/org/repo/pull/1"},
            state={},
        )
        mock_task_run_class.objects.select_related.return_value.get.return_value = mock_run

        post_slack_update(
            PostSlackUpdateInput(
                run_id="run-1",
                slack_thread_context=self.slack_thread_context,
                sandbox_cleaned=True,
            )
        )

        mock_update_reaction.assert_called_once_with("hedgehog")
        mock_delete_progress.assert_not_called()
        mock_post_pr_opened_sandbox_cleaned.assert_called_once_with(
            "https://github.com/org/repo/pull/1",
            "http://localhost:8000/project/1/tasks/10?runId=run-1",
        )

    @patch.object(SlackThreadHandler, "post_pr_opened_sandbox_cleaned")
    @patch.object(SlackThreadHandler, "delete_progress")
    @patch.object(SlackThreadHandler, "update_reaction")
    @patch.object(SlackThreadHandler, "__init__", return_value=None)
    @patch("products.tasks.backend.models.TaskRun")
    def test_completed_pr_run_after_cleanup_does_not_repost_if_already_notified(
        self,
        mock_task_run_class,
        mock_handler_init,
        mock_update_reaction,
        mock_delete_progress,
        mock_post_pr_opened_sandbox_cleaned,
    ):
        mock_run = self._make_mock_run(
            mock_task_run_class.Status.COMPLETED,
            output={"pr_url": "https://github.com/org/repo/pull/1"},
            state={"slack_pr_opened_notified": True},
        )
        mock_task_run_class.objects.select_related.return_value.get.return_value = mock_run

        post_slack_update(
            PostSlackUpdateInput(
                run_id="run-1",
                slack_thread_context=self.slack_thread_context,
                sandbox_cleaned=True,
            )
        )

        mock_update_reaction.assert_called_once_with("hedgehog")
        mock_delete_progress.assert_called_once()
        mock_post_pr_opened_sandbox_cleaned.assert_not_called()

    @patch.object(SlackThreadHandler, "post_pr_opened_sandbox_cleaned")
    @patch.object(SlackThreadHandler, "delete_progress")
    @patch.object(SlackThreadHandler, "update_reaction")
    @patch.object(SlackThreadHandler, "__init__", return_value=None)
    @patch("products.tasks.backend.models.TaskRun")
    def test_same_pr_url_with_notified_url_in_state_does_not_repost(
        self,
        mock_task_run_class,
        mock_handler_init,
        mock_update_reaction,
        mock_delete_progress,
        mock_post_pr_opened_sandbox_cleaned,
    ):
        mock_run = self._make_mock_run(
            mock_task_run_class.Status.COMPLETED,
            output={"pr_url": "https://github.com/org/repo/pull/1"},
            state={
                "slack_pr_opened_notified": True,
                "slack_notified_pr_url": "https://github.com/org/repo/pull/1",
            },
        )
        mock_task_run_class.objects.select_related.return_value.get.return_value = mock_run

        post_slack_update(
            PostSlackUpdateInput(
                run_id="run-1",
                slack_thread_context=self.slack_thread_context,
                sandbox_cleaned=True,
            )
        )

        mock_update_reaction.assert_called_once_with("hedgehog")
        mock_delete_progress.assert_called_once()
        mock_post_pr_opened_sandbox_cleaned.assert_not_called()

    @patch.object(SlackThreadHandler, "post_pr_opened_sandbox_cleaned")
    @patch.object(SlackThreadHandler, "update_reaction")
    @patch.object(SlackThreadHandler, "__init__", return_value=None)
    @patch("products.tasks.backend.models.TaskRun")
    def test_different_pr_url_from_notified_url_posts_once(
        self,
        mock_task_run_class,
        mock_handler_init,
        mock_update_reaction,
        mock_post_pr_opened_sandbox_cleaned,
    ):
        mock_run = self._make_mock_run(
            mock_task_run_class.Status.COMPLETED,
            output={"pr_url": "https://github.com/org/repo/pull/2"},
            state={
                "slack_pr_opened_notified": True,
                "slack_notified_pr_url": "https://github.com/org/repo/pull/1",
            },
        )
        mock_task_run_class.objects.select_related.return_value.get.return_value = mock_run

        post_slack_update(
            PostSlackUpdateInput(
                run_id="run-1",
                slack_thread_context=self.slack_thread_context,
                sandbox_cleaned=True,
            )
        )

        mock_update_reaction.assert_called_once_with("hedgehog")
        mock_post_pr_opened_sandbox_cleaned.assert_called_once_with(
            "https://github.com/org/repo/pull/2",
            "http://localhost:8000/project/1/tasks/10?runId=run-1",
        )

    @patch.object(SlackThreadHandler, "post_completion")
    @patch.object(SlackThreadHandler, "post_or_update_progress")
    @patch.object(SlackThreadHandler, "post_error")
    @patch.object(SlackThreadHandler, "post_cancelled")
    @patch.object(SlackThreadHandler, "post_pr_opened_sandbox_cleaned")
    @patch.object(SlackThreadHandler, "post_pr_opened")
    @patch.object(SlackThreadHandler, "update_reaction")
    @patch.object(SlackThreadHandler, "__init__", return_value=None)
    @patch("products.tasks.backend.models.TaskRun")
    def test_user_without_posthog_code_access_omits_task_url(
        self,
        mock_task_run_class,
        _mock_handler_init,
        _mock_update_reaction,
        mock_post_pr_opened,
        mock_post_pr_opened_sandbox_cleaned,
        mock_post_cancelled,
        mock_post_error,
        mock_post_progress,
        mock_post_completion,
    ):
        # When the task creator is not a PostHog Code user, every handler call
        # receives ``task_url=None`` (and the progress handler receives
        # ``logs_deeplink=None``) so the deep-link / web buttons are skipped.
        self._access_patcher.stop()
        deny_patcher = patch(
            "products.tasks.backend.temporal.process_task.activities.post_slack_update.has_tasks_access",
            return_value=False,
        )
        deny_patcher.start()
        self.addCleanup(deny_patcher.stop)

        scenarios: list[tuple[MagicMock, MagicMock]] = []

        completed = self._make_mock_run(
            mock_task_run_class.Status.COMPLETED, output={"pr_url": "https://github.com/org/repo/pull/1"}
        )
        scenarios.append((completed, mock_post_completion))

        failed = self._make_mock_run(mock_task_run_class.Status.FAILED, error_message="boom")
        scenarios.append((failed, mock_post_error))

        cancelled = self._make_mock_run(mock_task_run_class.Status.CANCELLED)
        scenarios.append((cancelled, mock_post_cancelled))

        in_progress = self._make_mock_run(mock_task_run_class.Status.IN_PROGRESS, stage="Building")
        scenarios.append((in_progress, mock_post_progress))

        in_progress_with_pr = self._make_mock_run(
            mock_task_run_class.Status.IN_PROGRESS,
            stage="Opening PR",
            output={"pr_url": "https://github.com/org/repo/pull/2"},
            state={},
        )
        scenarios.append((in_progress_with_pr, mock_post_pr_opened))

        cleaned_with_pr = self._make_mock_run(
            mock_task_run_class.Status.COMPLETED,
            output={"pr_url": "https://github.com/org/repo/pull/3"},
            state={},
        )

        for run, handler_mock in scenarios:
            handler_mock.reset_mock()
            mock_task_run_class.objects.select_related.return_value.get.return_value = run
            post_slack_update(PostSlackUpdateInput(run_id="run-1", slack_thread_context=self.slack_thread_context))
            handler_mock.assert_called_once()
            # ``task_url`` is always the trailing positional argument on every
            # handler signature; passing ``None`` is the contract for "no access".
            assert handler_mock.call_args.args[-1] is None

        mock_post_pr_opened_sandbox_cleaned.reset_mock()
        mock_task_run_class.objects.select_related.return_value.get.return_value = cleaned_with_pr
        post_slack_update(
            PostSlackUpdateInput(
                run_id="run-1",
                slack_thread_context=self.slack_thread_context,
                sandbox_cleaned=True,
            )
        )
        mock_post_pr_opened_sandbox_cleaned.assert_called_once()
        assert mock_post_pr_opened_sandbox_cleaned.call_args.args[-1] is None

    @patch.object(SlackThreadHandler, "post_completion")
    @patch.object(SlackThreadHandler, "update_reaction")
    @patch.object(SlackThreadHandler, "__init__", return_value=None)
    @patch("products.tasks.backend.models.TaskRun")
    def test_missing_created_by_omits_task_url(
        self,
        mock_task_run_class,
        _mock_handler_init,
        _mock_update_reaction,
        mock_post_completion,
    ):
        # ``has_tasks_access`` is never reached when the run has no creator —
        # a None viewer short-circuits to "no access" without consulting the
        # flag service.
        self._access_patcher.stop()

        sentinel = MagicMock(name="should_not_be_called")
        sentinel_patcher = patch(
            "products.tasks.backend.temporal.process_task.activities.post_slack_update.has_tasks_access",
            sentinel,
        )
        sentinel_patcher.start()
        self.addCleanup(sentinel_patcher.stop)

        run = self._make_mock_run(
            mock_task_run_class.Status.COMPLETED, output={"pr_url": "https://github.com/org/repo/pull/1"}
        )
        run.task.created_by = None
        mock_task_run_class.objects.select_related.return_value.get.return_value = run

        post_slack_update(PostSlackUpdateInput(run_id="run-1", slack_thread_context=self.slack_thread_context))

        sentinel.assert_not_called()
        mock_post_completion.assert_called_once_with("https://github.com/org/repo/pull/1", None)

    @patch.object(SlackThreadHandler, "post_completion")
    @patch.object(SlackThreadHandler, "update_reaction")
    @patch.object(SlackThreadHandler, "__init__", return_value=None)
    @patch("products.tasks.backend.models.TaskRun")
    def test_access_check_exception_fails_closed(
        self,
        mock_task_run_class,
        _mock_handler_init,
        _mock_update_reaction,
        mock_post_completion,
    ):
        # A flag-service blip must not surface the link to a user we can't
        # confirm has access — and must not break the surrounding update.
        self._access_patcher.stop()
        boom_patcher = patch(
            "products.tasks.backend.temporal.process_task.activities.post_slack_update.has_tasks_access",
            side_effect=RuntimeError("flag service down"),
        )
        boom_patcher.start()
        self.addCleanup(boom_patcher.stop)

        run = self._make_mock_run(
            mock_task_run_class.Status.COMPLETED, output={"pr_url": "https://github.com/org/repo/pull/1"}
        )
        mock_task_run_class.objects.select_related.return_value.get.return_value = run

        post_slack_update(PostSlackUpdateInput(run_id="run-1", slack_thread_context=self.slack_thread_context))

        mock_post_completion.assert_called_once_with("https://github.com/org/repo/pull/1", None)

    @patch.object(SlackThreadHandler, "post_pr_opened_sandbox_cleaned")
    @patch.object(SlackThreadHandler, "update_reaction")
    @patch.object(SlackThreadHandler, "__init__", return_value=None)
    @patch("products.tasks.backend.models.TaskRun")
    def test_cancelled_pr_run_after_cleanup_posts_cleaned_message(
        self,
        mock_task_run_class,
        mock_handler_init,
        mock_update_reaction,
        mock_post_pr_opened_sandbox_cleaned,
    ):
        mock_run = self._make_mock_run(
            mock_task_run_class.Status.CANCELLED,
            output={"pr_url": "https://github.com/org/repo/pull/2"},
        )
        mock_task_run_class.objects.select_related.return_value.get.return_value = mock_run

        post_slack_update(
            PostSlackUpdateInput(
                run_id="run-1",
                slack_thread_context=self.slack_thread_context,
                sandbox_cleaned=True,
            )
        )

        mock_update_reaction.assert_called_once_with("hedgehog")
        mock_post_pr_opened_sandbox_cleaned.assert_called_once_with(
            "https://github.com/org/repo/pull/2",
            "http://localhost:8000/project/1/tasks/10?runId=run-1",
        )
