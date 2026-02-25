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

    def _make_mock_run(self, status: str, **kwargs):
        mock_run = MagicMock()
        mock_run.status = status
        mock_run.task.team_id = 1
        mock_run.task_id = 10
        mock_run.id = "run-1"
        for k, v in kwargs.items():
            setattr(mock_run, k, v)
        return mock_run

    @patch.object(SlackThreadHandler, "post_completion")
    @patch.object(SlackThreadHandler, "update_reaction")
    @patch.object(SlackThreadHandler, "__init__", return_value=None)
    @patch("products.tasks.backend.models.TaskRun")
    def test_completed_run_updates_reaction_to_white_check_mark(
        self, mock_task_run_class, mock_handler_init, mock_update_reaction, mock_post_completion
    ):
        mock_run = self._make_mock_run(
            mock_task_run_class.Status.COMPLETED,
            output={"pr_url": "https://github.com/org/repo/pull/1"},
        )
        mock_task_run_class.objects.select_related.return_value.get.return_value = mock_run

        post_slack_update(PostSlackUpdateInput(run_id="run-1", slack_thread_context=self.slack_thread_context))

        mock_update_reaction.assert_called_once_with("white_check_mark")
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

        mock_update_reaction.assert_called_once_with("white_check_mark")
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

    @patch.object(SlackThreadHandler, "post_or_update_progress")
    @patch.object(SlackThreadHandler, "__init__", return_value=None)
    @patch("products.tasks.backend.models.TaskRun")
    def test_in_progress_with_pr_shows_sandbox_still_running(
        self, mock_task_run_class, mock_handler_init, mock_post_progress
    ):
        mock_run = self._make_mock_run(
            mock_task_run_class.Status.IN_PROGRESS,
            stage="Building",
            output={"pr_url": "https://github.com/org/repo/pull/1"},
        )
        mock_task_run_class.objects.select_related.return_value.get.return_value = mock_run

        post_slack_update(PostSlackUpdateInput(run_id="run-1", slack_thread_context=self.slack_thread_context))

        mock_post_progress.assert_called_once_with(
            "Building",
            "http://localhost:8000/project/1/tasks/10?runId=run-1",
            run_id="run-1",
            pr_url="https://github.com/org/repo/pull/1",
        )

    @patch.object(SlackThreadHandler, "post_or_update_progress")
    @patch.object(SlackThreadHandler, "post_thread_message")
    @patch.object(SlackThreadHandler, "__init__", return_value=None)
    @patch("products.tasks.backend.models.TaskRun")
    def test_in_progress_with_pr_posts_notification_once(
        self,
        mock_task_run_class,
        mock_handler_init,
        mock_post_thread_message,
        mock_post_progress,
    ):
        mock_run = self._make_mock_run(
            mock_task_run_class.Status.IN_PROGRESS,
            stage="Building",
            output={"pr_url": "https://github.com/org/repo/pull/1"},
            state={},
        )
        mock_task_run_class.objects.select_related.return_value.get.return_value = mock_run

        post_slack_update(
            PostSlackUpdateInput(
                run_id="run-1",
                slack_thread_context={
                    **self.slack_thread_context,
                    "mentioning_slack_user_id": "U123",
                },
            )
        )

        mock_post_thread_message.assert_called_once_with("<@U123> Pull request opened. Sandbox still running.")
        mock_run.save.assert_called_once()

    @patch.object(SlackThreadHandler, "post_pr_opened_sandbox_cleaned")
    @patch.object(SlackThreadHandler, "update_reaction")
    @patch.object(SlackThreadHandler, "__init__", return_value=None)
    @patch("products.tasks.backend.models.TaskRun")
    def test_completed_pr_run_after_cleanup_posts_cleaned_message(
        self,
        mock_task_run_class,
        mock_handler_init,
        mock_update_reaction,
        mock_post_pr_opened_sandbox_cleaned,
    ):
        mock_run = self._make_mock_run(
            mock_task_run_class.Status.COMPLETED,
            output={"pr_url": "https://github.com/org/repo/pull/1"},
        )
        mock_task_run_class.objects.select_related.return_value.get.return_value = mock_run

        post_slack_update(
            PostSlackUpdateInput(
                run_id="run-1",
                slack_thread_context=self.slack_thread_context,
                sandbox_cleaned=True,
            )
        )

        mock_update_reaction.assert_called_once_with("white_check_mark")
        mock_post_pr_opened_sandbox_cleaned.assert_called_once_with(
            "https://github.com/org/repo/pull/1",
            "http://localhost:8000/project/1/tasks/10?runId=run-1",
        )

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

        mock_update_reaction.assert_called_once_with("white_check_mark")
        mock_post_pr_opened_sandbox_cleaned.assert_called_once_with(
            "https://github.com/org/repo/pull/2",
            "http://localhost:8000/project/1/tasks/10?runId=run-1",
        )
