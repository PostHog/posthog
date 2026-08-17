from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase

from parameterized import parameterized

from posthog.models import Comment, Organization, OrganizationMembership, Team, User
from posthog.models.scoping import team_scope

from products.tasks.backend.facade.api import (
    list_mentions,
    list_thread_messages,
    post_artifact_thread_update,
    post_canvas_created_thread_update,
    post_commits_pushed_thread_update,
    post_pr_created_thread_update,
    record_comment_activity,
    set_task_run_output,
    update_task_run,
)
from products.tasks.backend.models import Channel, Task, TaskRun, TaskThreadMessage, TaskThreadMessageMention

_FLAG_TARGET = "products.tasks.backend.facade.api.posthoganalytics.feature_enabled"


class TestAgentThreadUpdates(TestCase):
    def setUp(self) -> None:
        cache.clear()
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")
        self.user = User.objects.create_user(
            email="creator@example.com", first_name="Casey", last_name="Creator", password="password"
        )
        OrganizationMembership.objects.create(user=self.user, organization=self.organization)
        # Direct instantiation sidesteps the fail-closed TeamScopedManager so
        # setUp doesn't need a team_scope wrapper (see test_channels_api.py).
        self.channel = Channel(team=self.team, name="general")
        self.channel.save()
        self.task = Task.objects.create(
            team=self.team,
            title="Build canvas",
            description="",
            origin_product=Task.OriginProduct.USER_CREATED,
            created_by=self.user,
            channel=self.channel,
        )
        self.task_run = TaskRun.objects.create(task=self.task, team=self.team)

    def _messages(self, task: Task) -> list[TaskThreadMessage]:
        return list(TaskThreadMessage.objects.for_team(self.team.id).filter(task=task).order_by("created_at"))

    @patch(_FLAG_TARGET, return_value=True)
    def test_pr_created_posts_authorless_artifact_message(self, _flag) -> None:
        post_pr_created_thread_update(self.task_run, "https://github.com/posthog/posthog/pull/123")

        messages = self._messages(self.task)
        self.assertEqual(len(messages), 1)
        self.assertIsNone(messages[0].author_id)
        self.assertEqual(messages[0].author_kind, TaskThreadMessage.AuthorKind.AGENT)
        self.assertEqual(messages[0].event, "pr_created")
        self.assertEqual(messages[0].payload, {"pr_url": "https://github.com/posthog/posthog/pull/123"})
        self.assertEqual(
            messages[0].content,
            "[posthog/posthog#123](https://github.com/posthog/posthog/pull/123) has been opened",
        )

    @parameterized.expand(
        [
            ("non_github", "https://example.com/pr/9"),
            ("github_in_path", "https://evil.example/github.com/posthog/posthog/pull/123"),
        ]
    )
    @patch(_FLAG_TARGET, return_value=True)
    def test_pr_created_falls_back_to_url_label_for_non_github_urls(self, _name, pr_url, _flag) -> None:
        post_pr_created_thread_update(self.task_run, pr_url)

        messages = self._messages(self.task)
        self.assertEqual(len(messages), 1)
        self.assertEqual(
            messages[0].content,
            f"[{pr_url}]({pr_url}) has been opened",
        )

    @patch(_FLAG_TARGET, return_value=True)
    def test_pr_created_dedupes_per_pr_url(self, _flag) -> None:
        # Both the agent-output path and the GitHub webhook backstop can announce
        # the same PR; only one artifact row must land in the thread.
        post_pr_created_thread_update(self.task_run, "https://github.com/posthog/posthog/pull/123")
        post_pr_created_thread_update(self.task_run, "https://github.com/posthog/posthog/pull/123")

        self.assertEqual(len(self._messages(self.task)), 1)

    @patch(_FLAG_TARGET, return_value=True)
    def test_pr_created_posts_separate_messages_for_distinct_prs(self, _flag) -> None:
        post_pr_created_thread_update(self.task_run, "https://github.com/posthog/posthog/pull/1")
        post_pr_created_thread_update(self.task_run, "https://github.com/posthog/posthog/pull/2")

        self.assertEqual(len(self._messages(self.task)), 2)

    @parameterized.expand(
        [
            ("javascript_scheme", "javascript:alert(1)"),
            ("markdown_breakout_paren", "https://example.com/pr)+[click](https://evil.example)"),
            ("embedded_newline", "https://example.com/pr\n![tracker](https://evil.example/p.png)"),
            ("embedded_bracket", "https://github.com/own]er/repo/pull/1"),
            ("no_host", "https:///pull/1"),
        ]
    )
    @patch(_FLAG_TARGET, return_value=True)
    def test_pr_created_skips_unsafe_urls(self, _name, pr_url, _flag) -> None:
        # pr_url flows from task-run output into a markdown [label](url) token in a
        # shared thread; anything that can't be a plain http(s) URL is dropped.
        post_pr_created_thread_update(self.task_run, pr_url)

        self.assertEqual(self._messages(self.task), [])

    @parameterized.expand(
        [
            ("flag_off", False, True),
            ("no_creator", True, False),
        ]
    )
    @patch(_FLAG_TARGET)
    def test_pr_created_skips(self, _name, flag_on, has_creator, flag_mock) -> None:
        flag_mock.return_value = flag_on
        task = Task.objects.create(
            team=self.team,
            title="Other task",
            description="",
            origin_product=Task.OriginProduct.USER_CREATED,
            created_by=self.user if has_creator else None,
            channel=self.channel,
        )
        run = TaskRun.objects.create(task=task, team=self.team)

        post_pr_created_thread_update(run, "https://github.com/posthog/posthog/pull/123")

        self.assertEqual(self._messages(task), [])

    @patch(_FLAG_TARGET, return_value=True)
    def test_pr_created_posts_when_run_patch_records_pr_url(self, _flag) -> None:
        # The agent attaches a PR by PATCHing the run's output — the path the
        # desktop/cloud agent actually uses (attachPullRequestToTask).
        with team_scope(self.team.id):
            update_task_run(
                self.task_run.id,
                self.task.id,
                self.team.id,
                validated_data={"output": {"pr_url": "https://github.com/posthog/posthog/pull/321"}},
            )

        messages = self._messages(self.task)
        self.assertEqual([message.event for message in messages], ["pr_created"])
        self.assertEqual(messages[0].payload, {"pr_url": "https://github.com/posthog/posthog/pull/321"})

    @patch(_FLAG_TARGET, return_value=True)
    def test_artifact_events_post_once_per_version(self, _flag) -> None:
        artifact = {"id": "art-1", "name": "report.md", "artifact_type": "document", "current_version": 1}

        post_artifact_thread_update(self.task_run, artifact, revised=False)
        post_artifact_thread_update(self.task_run, artifact, revised=False)
        post_artifact_thread_update(self.task_run, {**artifact, "current_version": 2}, revised=True)

        messages = self._messages(self.task)
        self.assertEqual([message.event for message in messages], ["artifact_created", "artifact_revised"])
        self.assertEqual(
            messages[0].payload,
            {
                "run_id": str(self.task_run.id),
                "artifact_id": "art-1",
                "name": "report.md",
                "artifact_type": "document",
                "version": 1,
            },
        )
        self.assertEqual(messages[1].payload["version"], 2)

    @patch(_FLAG_TARGET, return_value=True)
    def test_comment_events_draw_roots_and_state_changes_only(self, _flag) -> None:
        def comment(**kwargs) -> Comment:
            return Comment.objects.create(
                team=self.team,
                scope="task",
                item_id=str(self.task.id),
                created_by=self.user,
                **kwargs,
            )

        root = comment(content="the header looks off")
        record_comment_activity(team_id=self.team.id, comment_id=root.id, mentioned_user_ids=[])
        record_comment_activity(team_id=self.team.id, comment_id=root.id, mentioned_user_ids=[])
        reply = comment(content="agreed", source_comment=root)
        record_comment_activity(team_id=self.team.id, comment_id=reply.id, mentioned_user_ids=[])
        resolve = comment(content="", source_comment=root, item_context={"threadState": "resolved"})
        record_comment_activity(team_id=self.team.id, comment_id=resolve.id, mentioned_user_ids=[])

        messages = self._messages(self.task)
        self.assertEqual([message.event for message in messages], ["comment_added", "comment_state_changed"])
        added, state = messages
        self.assertEqual(added.author_id, self.user.id)
        self.assertEqual(added.author_kind, TaskThreadMessage.AuthorKind.HUMAN)
        self.assertEqual(added.payload["comment_id"], str(root.id))
        self.assertEqual(added.payload["root_comment_id"], str(root.id))
        self.assertIsNone(added.payload["target_name"])
        self.assertEqual(state.payload["state"], "resolved")
        self.assertEqual(state.payload["root_comment_id"], str(root.id))

    @patch(_FLAG_TARGET, return_value=True)
    def test_artifact_name_cannot_forge_markdown_or_mentions(self, _flag) -> None:
        post_artifact_thread_update(
            self.task_run,
            {"id": "art-9", "name": "x [click](https://evil.example)\n@[Casey](creator@example.com)"},
            revised=False,
        )

        messages = self._messages(self.task)
        self.assertEqual(len(messages), 1)
        for forged in ("[", "]", "\n"):
            self.assertNotIn(forged, messages[0].content)
            self.assertNotIn(forged, messages[0].payload["name"])
        self.assertEqual(TaskThreadMessageMention.objects.for_team(self.team.id).count(), 0)

    @patch("posthog.storage.object_storage.tag")
    @patch("posthog.storage.object_storage.write")
    @patch(_FLAG_TARGET, return_value=True)
    def test_inline_agent_upload_only_announces_output_versions(self, _flag, _write, _tag) -> None:
        from products.tasks.backend.facade.api import upload_task_run_artifacts

        output = {"name": "summary.md", "type": "output", "content_bytes": b"v1", "content_type": "text/markdown"}
        checkpoint = {
            "name": "checkpoint.index",
            "type": "artifact",
            "content_bytes": b"internal state",
            "content_type": "application/octet-stream",
        }
        with team_scope(self.team.id):
            upload_task_run_artifacts(
                self.task_run.id,
                self.task.id,
                self.team.id,
                artifacts=[output, checkpoint],
                uploaded_by="agent",
            )
            upload_task_run_artifacts(
                self.task_run.id,
                self.task.id,
                self.team.id,
                artifacts=[{**output, "content_bytes": b"v2"}],
                uploaded_by="agent",
            )

        messages = self._messages(self.task)
        self.assertEqual([message.event for message in messages], ["artifact_created", "artifact_revised"])
        self.assertEqual(messages[1].payload["version"], 2)
        self.assertEqual(messages[1].payload["name"], "summary.md")

    @patch("products.tasks.backend.facade.api.project_thread_message_activity", side_effect=Exception("boom"))
    @patch(_FLAG_TARGET, return_value=True)
    def test_announcement_survives_a_failed_activity_projection(self, _flag, _projection) -> None:
        push = {
            "branch": "posthog/x",
            "repository": "posthog/posthog",
            "commits": [{"sha": "fadedfacade", "subject": "feat: x", "url": "https://github.com/x"}],
        }

        post_commits_pushed_thread_update(self.task_run, push)

        self.assertEqual([message.event for message in self._messages(self.task)], ["commits_pushed"])

    @patch(_FLAG_TARGET, return_value=True)
    def test_artifact_comment_names_its_target(self, _flag) -> None:
        self.task_run.artifacts = [{"id": "artifact-1", "name": "report.md", "type": "output"}]
        self.task_run.save(update_fields=["artifacts"])
        comment = Comment.objects.create(
            team=self.team,
            scope="task_artifact",
            item_id="artifact-1",
            item_context={"taskId": str(self.task.id)},
            content="nice summary",
            created_by=self.user,
        )

        record_comment_activity(team_id=self.team.id, comment_id=comment.id, mentioned_user_ids=[])

        messages = self._messages(self.task)
        self.assertEqual([message.event for message in messages], ["comment_added"])
        self.assertEqual(messages[0].payload["target_name"], "report.md")

    @patch(_FLAG_TARGET, return_value=True)
    def test_commit_push_posts_once_when_run_patch_is_retried(self, _flag) -> None:
        output = {
            "commit_push": {
                "branch": "posthog/task-timeline-commits",
                "repository": "posthog/posthog",
                "commits": [
                    {
                        "sha": "abc123",
                        "subject": "feat(desktop): show commits",
                        "url": "https://github.com/posthog/posthog/commit/abc123",
                    }
                ],
            }
        }
        with team_scope(self.team.id):
            update_task_run(
                self.task_run.id,
                self.task.id,
                self.team.id,
                validated_data={"output": output},
                caller_is_agent=True,
            )
            update_task_run(
                self.task_run.id,
                self.task.id,
                self.team.id,
                validated_data={"output": output},
                caller_is_agent=True,
            )

        messages = self._messages(self.task)
        self.assertEqual([message.event for message in messages], ["commits_pushed"])
        self.assertEqual(messages[0].payload["head_sha"], "abc123")
        self.assertEqual(messages[0].payload["total"], 1)

    @patch(_FLAG_TARGET, return_value=True)
    def test_commit_push_from_a_human_caller_does_not_forge_an_agent_row(self, _flag) -> None:
        output = {
            "commit_push": {
                "branch": "posthog/x",
                "repository": "posthog/posthog",
                "commits": [{"sha": "beadedcafe", "subject": "feat: x", "url": "https://github.com/x"}],
            }
        }
        with team_scope(self.team.id):
            update_task_run(
                self.task_run.id,
                self.task.id,
                self.team.id,
                validated_data={"output": output},
            )

        self.assertEqual(self._messages(self.task), [])

    @patch(_FLAG_TARGET, return_value=True)
    def test_commit_push_sanitizes_untrusted_branch(self, _flag) -> None:
        # The branch is caller-controlled and lands in rendered markdown content
        # and the mention scanner. A crafted value must not forge a markdown link
        # or an @[name](email) mention of a real org member in the agent row.
        post_commits_pushed_thread_update(
            self.task_run,
            {
                "branch": "@[Casey Creator](creator@example.com)",
                "repository": "posthog/posthog",
                "commits": [
                    {
                        "sha": "abc123",
                        "subject": "feat(desktop): show commits",
                        "url": "https://github.com/posthog/posthog/commit/abc123",
                    }
                ],
            },
        )

        messages = self._messages(self.task)
        self.assertEqual([message.event for message in messages], ["commits_pushed"])
        self.assertEqual(messages[0].content, "1 commit pushed to @ Casey Creator (creator@example.com)")
        self.assertEqual(
            list(TaskThreadMessageMention.objects.for_team(self.team.id).filter(task=self.task)),
            [],
        )

    @patch(_FLAG_TARGET, return_value=True)
    def test_pr_created_posts_when_set_output_records_pr_url(self, _flag) -> None:
        with team_scope(self.team.id):
            set_task_run_output(
                self.task_run.id,
                self.task.id,
                self.team.id,
                output={"pr_url": "https://github.com/posthog/posthog/pull/654"},
            )

        messages = self._messages(self.task)
        self.assertEqual([message.event for message in messages], ["pr_created"])

    @patch(_FLAG_TARGET, return_value=True)
    def test_pr_created_posts_for_channel_less_tasks(self, _flag) -> None:
        # Threads exist per-task, not only per-channel: a task filed outside a
        # channel still has a thread panel, and its PR artifact must land there
        # (canvas_created behaves the same way).
        task = Task.objects.create(
            team=self.team,
            title="Channel-less task",
            description="",
            origin_product=Task.OriginProduct.USER_CREATED,
            created_by=self.user,
            channel=None,
        )
        run = TaskRun.objects.create(task=task, team=self.team)

        post_pr_created_thread_update(run, "https://github.com/posthog/posthog/pull/123")

        messages = self._messages(task)
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].event, "pr_created")

    @parameterized.expand(
        [
            (
                "with_link",
                "Signups overview",
                "https://us.posthog.com/code/canvas/c/d",
                "[Signups overview](https://us.posthog.com/code/canvas/c/d) has been created",
            ),
            (
                "name_sanitized_for_link_token",
                "[Q3] KPIs",
                "https://us.posthog.com/code/canvas/c/d",
                "[Q3  KPIs](https://us.posthog.com/code/canvas/c/d) has been created",
            ),
            ("without_link", "Signups overview", None, "Signups overview has been created"),
        ]
    )
    @patch(_FLAG_TARGET, return_value=True)
    def test_canvas_created_message_content(self, _name, canvas_name, canvas_url, expected, _flag) -> None:
        post_canvas_created_thread_update(
            self.task.id, self.team.id, acting_user_id=self.user.id, canvas_name=canvas_name, canvas_url=canvas_url
        )

        messages = self._messages(self.task)
        self.assertEqual(len(messages), 1)
        self.assertIsNone(messages[0].author_id)
        self.assertEqual(messages[0].author_kind, TaskThreadMessage.AuthorKind.AGENT)
        self.assertEqual(messages[0].event, "canvas_created")
        self.assertEqual(messages[0].content, expected)

    @patch(_FLAG_TARGET, return_value=True)
    def test_canvas_created_requires_creator_match(self, _flag) -> None:
        other = User.objects.create_user(email="other@example.com", first_name="Other", password="password")

        post_canvas_created_thread_update(
            self.task.id, self.team.id, acting_user_id=other.id, canvas_name="Canvas", canvas_url=None
        )

        self.assertEqual(self._messages(self.task), [])

    @patch(_FLAG_TARGET, return_value=False)
    def test_canvas_created_skips_when_flag_off(self, _flag) -> None:
        post_canvas_created_thread_update(
            self.task.id, self.team.id, acting_user_id=self.user.id, canvas_name="Canvas", canvas_url=None
        )

        self.assertEqual(self._messages(self.task), [])

    def test_list_thread_messages_excludes_legacy_turn_complete_rows(self) -> None:
        # The thread is human-to-human plus artifacts: rows written back when the
        # agent finished a turn (before that writeback was removed) must not
        # resurface in the listing.
        TaskThreadMessage.objects.for_team(self.team.id).create(
            team=self.team, task=self.task, author=self.user, content="Kicking this off"
        )
        TaskThreadMessage.objects.for_team(self.team.id).create(
            team=self.team,
            task=self.task,
            author_kind=TaskThreadMessage.AuthorKind.AGENT,
            event="turn_complete",
            payload={"run_id": str(self.task_run.id)},
            content="@[Casey Creator](creator@example.com) Turn complete.",
        )
        TaskThreadMessage.objects.for_team(self.team.id).create(
            team=self.team,
            task=self.task,
            author_kind=TaskThreadMessage.AuthorKind.AGENT,
            event="canvas_created",
            payload={"canvas_name": "Signups", "canvas_url": None},
            content="Signups has been created",
        )

        with team_scope(self.team.id):
            messages = list_thread_messages(self.task.id, self.team.id, self.user.id)

        assert messages is not None
        self.assertEqual([message.event for message in messages], ["", "canvas_created"])

    def test_list_mentions_excludes_legacy_turn_complete_mentions(self) -> None:
        # turn_complete messages @-mentioned the task creator and indexed that
        # mention; with the messages hidden from threads, their mention rows must
        # not surface notifications pointing at rows the thread no longer shows.
        human_message = TaskThreadMessage.objects.for_team(self.team.id).create(
            team=self.team,
            task=self.task,
            author=self.user,
            content="@[Casey Creator](creator@example.com) thoughts?",
        )
        turn_message = TaskThreadMessage.objects.for_team(self.team.id).create(
            team=self.team,
            task=self.task,
            author_kind=TaskThreadMessage.AuthorKind.AGENT,
            event="turn_complete",
            payload={"run_id": str(self.task_run.id)},
            content="@[Casey Creator](creator@example.com) Turn complete.",
        )
        for message in (human_message, turn_message):
            TaskThreadMessageMention.objects.for_team(self.team.id).create(
                team=self.team,
                message=message,
                task=self.task,
                mentioned_user=self.user,
                created_at=message.created_at,
            )

        with team_scope(self.team.id):
            mentions = list_mentions(self.team.id, self.user.id)

        self.assertEqual([mention.message_id for mention in mentions], [human_message.id])
