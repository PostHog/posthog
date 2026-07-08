import importlib

from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings

from parameterized import parameterized

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
        # Default the task-level dedupe to unset so the comparison is real, not a
        # truthy MagicMock; skip-path tests override it.
        mock_run.task.slack_notified_pr_url = None
        for k, v in kwargs.items():
            setattr(mock_run, k, v)
        return mock_run

    @patch.object(SlackThreadHandler, "post_pr_opened")
    @patch.object(SlackThreadHandler, "update_reaction")
    @patch.object(SlackThreadHandler, "__init__", return_value=None)
    @patch("products.tasks.backend.models.TaskRun")
    def test_completed_run_with_pr_routes_through_post_pr_opened(
        self, mock_task_run_class, mock_handler_init, mock_update_reaction, mock_post_pr_opened
    ):
        # Completed runs with a PR funnel through the single ``post_pr_opened``
        # template via the dedupe helper. ``post_completion`` is reserved for
        # the no-PR terminal state only.
        mock_run = self._make_mock_run(
            mock_task_run_class.Status.COMPLETED,
            output={"pr_url": "https://github.com/org/repo/pull/1"},
        )
        mock_task_run_class.objects.select_related.return_value.get.return_value = mock_run

        post_slack_update(PostSlackUpdateInput(run_id="run-1", slack_thread_context=self.slack_thread_context))

        mock_update_reaction.assert_called_once_with("hedgehog")
        mock_post_pr_opened.assert_called_once()
        mock_run.task.mark_slack_pr_notified.assert_called_once_with("https://github.com/org/repo/pull/1")

    @patch.object(SlackThreadHandler, "post_completion")
    @patch.object(SlackThreadHandler, "update_reaction")
    @patch.object(SlackThreadHandler, "__init__", return_value=None)
    @patch("products.tasks.backend.models.TaskRun")
    def test_completed_run_without_pr_posts_task_completed(
        self, mock_task_run_class, mock_handler_init, mock_update_reaction, mock_post_completion
    ):
        # ``post_completion`` is the no-PR terminal-state card.
        mock_run = self._make_mock_run(mock_task_run_class.Status.COMPLETED, output={})
        mock_task_run_class.objects.select_related.return_value.get.return_value = mock_run

        post_slack_update(PostSlackUpdateInput(run_id="run-1", slack_thread_context=self.slack_thread_context))

        mock_update_reaction.assert_called_once_with("hedgehog")
        mock_post_completion.assert_called_once_with("http://localhost:8000/project/1/tasks/10?runId=run-1")

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
        # The "View agent logs" button links to the cloud task page (works on
        # mobile) rather than a desktop-only ``posthog-code://`` deep link.
        assert mock_post_progress.call_args[0][1] == "http://localhost:8000/project/1/tasks/10?runId=run-1"

    @patch.object(SlackThreadHandler, "update_reaction")
    @patch.object(SlackThreadHandler, "post_or_update_progress")
    @patch.object(SlackThreadHandler, "post_pr_opened")
    @patch.object(SlackThreadHandler, "__init__", return_value=None)
    @patch("products.tasks.backend.models.TaskRun")
    def test_in_progress_with_pr_keeps_eyes_reaction(
        self,
        mock_task_run_class,
        mock_handler_init,
        _mock_post_pr_opened,
        mock_post_progress,
        mock_update_reaction,
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

    @patch("products.slack_app.backend.models.SlackThreadTaskMapping")
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
        mock_mapping_class,
    ):
        mock_run = self._make_mock_run(
            mock_task_run_class.Status.IN_PROGRESS,
            stage="Building",
            output={"pr_url": "https://github.com/org/repo/pull/1"},
            state={},
        )
        mock_task_run_class.objects.select_related.return_value.get.return_value = mock_run
        # This milestone ping tags the task starter, not whoever last touched the
        # thread: latest_actor is a casual joiner here, and this update can fire long
        # after the PR opened (once the CI follow-up loop settles), so tagging them
        # would spam the wrong person.
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
            reply_target_slack_user_id="U_ORIG",
        )
        mock_update_reaction.assert_called_once_with("eyes")
        mock_post_progress.assert_not_called()
        mock_run.task.mark_slack_pr_notified.assert_called_once_with("https://github.com/org/repo/pull/1")
        mock_run.save.assert_not_called()

    @parameterized.expand(
        [
            ("inactivity", "Run timed out due to inactivity"),
            ("max_duration", "Run timed out after exceeding the maximum run duration"),
        ]
    )
    @patch.object(SlackThreadHandler, "post_error")
    @patch.object(SlackThreadHandler, "post_completion")
    @patch.object(SlackThreadHandler, "delete_progress")
    @patch.object(SlackThreadHandler, "update_reaction")
    @patch.object(SlackThreadHandler, "__init__", return_value=None)
    @patch("products.tasks.backend.models.TaskRun")
    def test_timed_out_run_silently_deletes_progress(
        self,
        _name,
        error_message,
        mock_task_run_class,
        mock_handler_init,
        mock_update_reaction,
        mock_delete_progress,
        mock_post_completion,
        mock_post_error,
    ):
        # Timeouts are now recorded as FAILED (a distinct terminal state), but Slack still stays
        # quiet on them — no loud error card, just clear the progress marker.
        mock_run = self._make_mock_run(
            mock_task_run_class.Status.FAILED,
            error_message=error_message,
            output={},
        )
        mock_task_run_class.objects.select_related.return_value.get.return_value = mock_run

        post_slack_update(PostSlackUpdateInput(run_id="run-1", slack_thread_context=self.slack_thread_context))

        mock_update_reaction.assert_called_once_with("hedgehog")
        mock_delete_progress.assert_called_once()
        mock_post_completion.assert_not_called()
        mock_post_error.assert_not_called()

    @patch.object(SlackThreadHandler, "post_pr_opened")
    @patch.object(SlackThreadHandler, "update_reaction")
    @patch.object(SlackThreadHandler, "__init__", return_value=None)
    @patch("products.tasks.backend.models.TaskRun")
    def test_completed_pr_run_after_cleanup_posts_pr_opened_card(
        self,
        mock_task_run_class,
        mock_handler_init,
        mock_update_reaction,
        mock_post_pr_opened,
    ):
        # The sandbox-cleaned branch funnels through ``post_pr_opened`` — same
        # single template every PR lifecycle moment uses.
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
        mock_post_pr_opened.assert_called_once_with(
            "https://github.com/org/repo/pull/1",
            "http://localhost:8000/project/1/tasks/10?runId=run-1",
            reply_target_slack_user_id=None,
        )

    @patch.object(SlackThreadHandler, "delete_progress")
    @patch.object(SlackThreadHandler, "post_pr_opened")
    @patch.object(SlackThreadHandler, "update_reaction")
    @patch.object(SlackThreadHandler, "__init__", return_value=None)
    @patch("products.tasks.backend.models.TaskRun")
    def test_completed_run_does_not_repost_pr_when_already_announced(
        self,
        mock_task_run_class,
        mock_handler_init,
        mock_update_reaction,
        mock_post_pr_opened,
        mock_delete_progress,
    ):
        # Regression: when the same ``pr_url`` was already announced mid-run,
        # the COMPLETED-state Slack update must not fire a second card. The
        # follow-up loop can keep the workflow alive long after the user's
        # conversation ended, and a fresh card hours later reads as a
        # duplicate of the original. The dedupe-skip path must still clear
        # any lingering progress marker so the thread doesn't keep a stale
        # "Working on task..." card next to the already-posted PR card.
        mock_run = self._make_mock_run(
            mock_task_run_class.Status.COMPLETED,
            output={"pr_url": "https://github.com/org/repo/pull/1"},
            state={
                "slack_pr_opened_notified": True,
                "slack_notified_pr_url": "https://github.com/org/repo/pull/1",
            },
        )
        mock_task_run_class.objects.select_related.return_value.get.return_value = mock_run

        post_slack_update(PostSlackUpdateInput(run_id="run-1", slack_thread_context=self.slack_thread_context))

        mock_update_reaction.assert_called_once_with("hedgehog")
        mock_post_pr_opened.assert_not_called()
        mock_delete_progress.assert_called_once()

    @patch.object(SlackThreadHandler, "delete_progress")
    @patch.object(SlackThreadHandler, "post_pr_opened")
    @patch.object(SlackThreadHandler, "update_reaction")
    @patch.object(SlackThreadHandler, "__init__", return_value=None)
    @patch("products.tasks.backend.models.TaskRun")
    def test_run_does_not_repost_pr_a_sibling_run_already_announced(
        self,
        mock_task_run_class,
        mock_handler_init,
        mock_update_reaction,
        mock_post_pr_opened,
        mock_delete_progress,
    ):
        # Regression: a fresh run (empty per-run state) must not re-announce a PR a
        # sibling run already recorded on the shared Task.
        mock_run = self._make_mock_run(
            mock_task_run_class.Status.COMPLETED,
            output={"pr_url": "https://github.com/org/repo/pull/1"},
            state={},
        )
        mock_run.task.slack_notified_pr_url = "https://github.com/org/repo/pull/1"
        mock_task_run_class.objects.select_related.return_value.get.return_value = mock_run

        post_slack_update(PostSlackUpdateInput(run_id="run-1", slack_thread_context=self.slack_thread_context))

        mock_post_pr_opened.assert_not_called()
        mock_delete_progress.assert_called_once()
        mock_run.task.mark_slack_pr_notified.assert_not_called()

    @patch.object(SlackThreadHandler, "post_pr_opened")
    @patch.object(SlackThreadHandler, "update_reaction")
    @patch.object(SlackThreadHandler, "__init__", return_value=None)
    @patch("products.tasks.backend.models.TaskRun")
    def test_completed_run_with_new_pr_url_posts_card_even_if_old_url_notified(
        self,
        mock_task_run_class,
        mock_handler_init,
        mock_update_reaction,
        mock_post_pr_opened,
    ):
        # An older URL having been announced doesn't suppress the card for a
        # different URL. The dedupe is per-URL, not per-run.
        mock_run = self._make_mock_run(
            mock_task_run_class.Status.COMPLETED,
            output={"pr_url": "https://github.com/org/repo/pull/2"},
            state={
                "slack_pr_opened_notified": True,
                "slack_notified_pr_url": "https://github.com/org/repo/pull/1",
            },
        )
        mock_task_run_class.objects.select_related.return_value.get.return_value = mock_run

        post_slack_update(PostSlackUpdateInput(run_id="run-1", slack_thread_context=self.slack_thread_context))

        mock_post_pr_opened.assert_called_once_with(
            "https://github.com/org/repo/pull/2",
            "http://localhost:8000/project/1/tasks/10?runId=run-1",
            reply_target_slack_user_id=None,
        )
        mock_run.task.mark_slack_pr_notified.assert_called_once_with("https://github.com/org/repo/pull/2")

    @patch.object(SlackThreadHandler, "delete_progress")
    @patch.object(SlackThreadHandler, "post_pr_opened")
    @patch.object(SlackThreadHandler, "update_reaction")
    @patch.object(SlackThreadHandler, "__init__", return_value=None)
    @patch("products.tasks.backend.models.TaskRun")
    def test_completed_pr_run_after_cleanup_does_not_repost_if_already_notified(
        self,
        mock_task_run_class,
        mock_handler_init,
        mock_update_reaction,
        mock_post_pr_opened,
        mock_delete_progress,
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
        mock_post_pr_opened.assert_not_called()
        mock_delete_progress.assert_called_once()

    @patch.object(SlackThreadHandler, "delete_progress")
    @patch.object(SlackThreadHandler, "post_pr_opened")
    @patch.object(SlackThreadHandler, "update_reaction")
    @patch.object(SlackThreadHandler, "__init__", return_value=None)
    @patch("products.tasks.backend.models.TaskRun")
    def test_same_pr_url_with_notified_url_in_state_does_not_repost(
        self,
        mock_task_run_class,
        mock_handler_init,
        mock_update_reaction,
        mock_post_pr_opened,
        mock_delete_progress,
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
        mock_post_pr_opened.assert_not_called()
        mock_delete_progress.assert_called_once()

    @patch.object(SlackThreadHandler, "post_pr_opened")
    @patch.object(SlackThreadHandler, "update_reaction")
    @patch.object(SlackThreadHandler, "__init__", return_value=None)
    @patch("products.tasks.backend.models.TaskRun")
    def test_different_pr_url_from_notified_url_posts_once(
        self,
        mock_task_run_class,
        mock_handler_init,
        mock_update_reaction,
        mock_post_pr_opened,
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
        mock_post_pr_opened.assert_called_once_with(
            "https://github.com/org/repo/pull/2",
            "http://localhost:8000/project/1/tasks/10?runId=run-1",
            reply_target_slack_user_id=None,
        )

    @patch.object(SlackThreadHandler, "post_completion")
    @patch.object(SlackThreadHandler, "post_or_update_progress")
    @patch.object(SlackThreadHandler, "post_error")
    @patch.object(SlackThreadHandler, "post_cancelled")
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
        mock_post_cancelled,
        mock_post_error,
        mock_post_progress,
        mock_post_completion,
    ):
        # When the task creator is not a PostHog Code user, every handler call
        # (including the progress handler) receives ``task_url=None`` so the
        # web buttons are skipped.
        self._access_patcher.stop()
        deny_patcher = patch(
            "products.tasks.backend.temporal.process_task.activities.post_slack_update.has_tasks_access",
            return_value=False,
        )
        deny_patcher.start()
        self.addCleanup(deny_patcher.stop)

        scenarios: list[tuple[MagicMock, MagicMock]] = []

        completed_no_pr = self._make_mock_run(mock_task_run_class.Status.COMPLETED, output={})
        scenarios.append((completed_no_pr, mock_post_completion))

        completed_with_pr = self._make_mock_run(
            mock_task_run_class.Status.COMPLETED, output={"pr_url": "https://github.com/org/repo/pull/1"}, state={}
        )
        scenarios.append((completed_with_pr, mock_post_pr_opened))

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

        for run, handler_mock in scenarios:
            handler_mock.reset_mock()
            mock_task_run_class.objects.select_related.return_value.get.return_value = run
            post_slack_update(PostSlackUpdateInput(run_id="run-1", slack_thread_context=self.slack_thread_context))
            handler_mock.assert_called_once()
            # ``task_url`` is the second positional argument on ``post_pr_opened``
            # and the trailing positional argument on every other handler — the
            # contract is "no access ⇒ this argument is ``None``".
            task_url_arg = (
                handler_mock.call_args.args[1]
                if handler_mock is mock_post_pr_opened
                else handler_mock.call_args.args[-1]
            )
            assert task_url_arg is None

        mock_post_pr_opened.reset_mock()
        cleaned_with_pr = self._make_mock_run(
            mock_task_run_class.Status.COMPLETED,
            output={"pr_url": "https://github.com/org/repo/pull/3"},
            state={},
        )
        mock_task_run_class.objects.select_related.return_value.get.return_value = cleaned_with_pr
        post_slack_update(
            PostSlackUpdateInput(
                run_id="run-1",
                slack_thread_context=self.slack_thread_context,
                sandbox_cleaned=True,
            )
        )
        mock_post_pr_opened.assert_called_once()
        # task_url is the second positional argument on post_pr_opened.
        assert mock_post_pr_opened.call_args.args[1] is None

    @patch.object(SlackThreadHandler, "post_pr_opened")
    @patch.object(SlackThreadHandler, "update_reaction")
    @patch.object(SlackThreadHandler, "__init__", return_value=None)
    @patch("products.tasks.backend.models.TaskRun")
    def test_missing_created_by_omits_task_url(
        self,
        mock_task_run_class,
        _mock_handler_init,
        _mock_update_reaction,
        mock_post_pr_opened,
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
        mock_post_pr_opened.assert_called_once_with(
            "https://github.com/org/repo/pull/1", None, reply_target_slack_user_id=None
        )

    @patch.object(SlackThreadHandler, "post_pr_opened")
    @patch.object(SlackThreadHandler, "update_reaction")
    @patch.object(SlackThreadHandler, "__init__", return_value=None)
    @patch("products.tasks.backend.models.TaskRun")
    def test_access_check_exception_fails_closed(
        self,
        mock_task_run_class,
        _mock_handler_init,
        _mock_update_reaction,
        mock_post_pr_opened,
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

        mock_post_pr_opened.assert_called_once_with(
            "https://github.com/org/repo/pull/1", None, reply_target_slack_user_id=None
        )

    @patch.object(SlackThreadHandler, "post_pr_opened")
    @patch.object(SlackThreadHandler, "update_reaction")
    @patch.object(SlackThreadHandler, "__init__", return_value=None)
    @patch("products.tasks.backend.models.TaskRun")
    def test_cancelled_pr_run_after_cleanup_posts_pr_opened_card(
        self,
        mock_task_run_class,
        mock_handler_init,
        mock_update_reaction,
        mock_post_pr_opened,
    ):
        # A cancelled run that still produced a PR funnels through the same
        # single template — the cancellation card only fires when no PR was
        # opened.
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
        mock_post_pr_opened.assert_called_once_with(
            "https://github.com/org/repo/pull/2",
            "http://localhost:8000/project/1/tasks/10?runId=run-1",
            reply_target_slack_user_id=None,
        )
