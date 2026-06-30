from posthog.test.base import BaseTest
from unittest.mock import patch

from posthog.models import Team
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.comment import Comment

from products.notebooks.backend.markdown_conversion import (
    NotebookMarkdownConversionOptions,
    build_markdown_notebook_content,
    convert_notebook_content_to_markdown,
)
from products.notebooks.backend.markdown_migration import (
    get_markdown_notebook_migration_stats,
    migrate_notebooks_to_markdown,
)
from products.notebooks.backend.models import Notebook


class TestNotebookMarkdownConversion(BaseTest):
    def test_converts_rich_content_to_markdown_with_comments_mentions_and_widgets(self) -> None:
        content = {
            "type": "doc",
            "content": [
                {
                    "type": "heading",
                    "attrs": {"level": 1},
                    "content": [{"type": "text", "text": "Launch notes"}],
                },
                {
                    "type": "paragraph",
                    "content": [
                        {
                            "type": "text",
                            "text": "Ask ",
                        },
                        {
                            "type": "ph-mention",
                            "attrs": {"id": self.user.id},
                        },
                        {
                            "type": "text",
                            "text": " about activation",
                            "marks": [{"type": "bold"}, {"type": "comment", "attrs": {"id": "mark-1"}}],
                        },
                    ],
                },
                {
                    "type": "query",
                    "attrs": {"query": '{"kind":"HogQLQuery","query":"select 1"}', "view": True, "edit": False},
                },
            ],
        }

        markdown = convert_notebook_content_to_markdown(
            content,
            NotebookMarkdownConversionOptions(
                comment_replies_by_mark_id={},
                get_mention_label=lambda user_id: f"@user-{user_id}",
            ),
        )

        assert "# Launch notes" in markdown
        assert f'<mention id="{self.user.id}">@user-{self.user.id}</mention>' in markdown
        assert '<ref id="mark-1">** about activation**</ref>' in markdown
        assert '<Comment ref="mark-1" replies={[]} />' in markdown
        assert 'query={{"kind":"DataVisualizationNode","source":{"kind":"HogQLQuery","query":"select 1"}}}' in markdown
        assert "hideFilters" in markdown


class TestNotebookMarkdownMigration(BaseTest):
    def test_stats_count_all_notebooks_for_optional_team_scope(self) -> None:
        Notebook.objects.create(team=self.team, content={"type": "doc", "content": []})
        Notebook.objects.create(team=self.team, content=build_markdown_notebook_content("done"))
        other_team = Team.objects.create(organization=self.organization, name="other")
        Notebook.objects.create(team=other_team, content={"type": "doc", "content": []})

        all_stats = get_markdown_notebook_migration_stats()
        team_stats = get_markdown_notebook_migration_stats(self.team.id)

        assert all_stats.total == 3
        assert all_stats.converted == 1
        assert all_stats.pending == 2
        assert team_stats.total == 2
        assert team_stats.converted == 1
        assert team_stats.pending == 1

    def test_dry_run_does_not_mutate_or_log_activity(self) -> None:
        notebook = Notebook.objects.create(
            team=self.team,
            title="Dry run",
            content={"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "body"}]}]},
            version=3,
        )

        result = migrate_notebooks_to_markdown(user=self.user, team_id=self.team.id, dry_run=True)
        notebook.refresh_from_db()

        assert result.dry_run is True
        assert result.converted == 1
        assert notebook.version == 3
        assert notebook.content == {
            "type": "doc",
            "content": [{"type": "paragraph", "content": [{"type": "text", "text": "body"}]}],
        }
        assert not ActivityLog.objects.filter(scope="Notebook", item_id=notebook.short_id).exists()

    @patch("products.notebooks.backend.markdown_collab.publish_notebook_update")
    def test_apply_converts_team_notebooks_and_logs_before_after_history(self, mock_publish) -> None:
        rich_content = {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {
                            "type": "text",
                            "text": "Important",
                            "marks": [{"type": "comment", "attrs": {"id": "mark-1"}}],
                        }
                    ],
                }
            ],
        }
        notebook = Notebook.objects.create(team=self.team, title="Convert me", content=rich_content, version=7)
        Comment.objects.create(
            team=self.team,
            scope="Notebook",
            item_id=notebook.short_id,
            content="keep this",
            item_context={"type": "mark", "id": "mark-1"},
            created_by=self.user,
        )
        other_team = Team.objects.create(organization=self.organization, name="other")
        other_notebook = Notebook.objects.create(
            team=other_team,
            content={"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "other"}]}]},
        )

        with self.captureOnCommitCallbacks(execute=True):
            result = migrate_notebooks_to_markdown(user=self.user, team_id=self.team.id, dry_run=False)

        notebook.refresh_from_db()
        other_notebook.refresh_from_db()
        assert result.converted == 1
        assert notebook.version == 8
        assert notebook.text_content is not None
        assert "<Comment" in notebook.text_content
        assert "keep this" in notebook.text_content
        assert notebook.content == build_markdown_notebook_content(notebook.text_content)
        assert other_notebook.content["content"][0]["type"] == "paragraph"

        log = ActivityLog.objects.get(scope="Notebook", item_id=notebook.short_id, activity="updated")
        changes_by_field = {change["field"]: change for change in log.detail["changes"]}
        assert changes_by_field["content"]["before"] == rich_content
        assert changes_by_field["content"]["after"] == notebook.content
        assert changes_by_field["version"]["before"] == 7
        assert changes_by_field["version"]["after"] == 8
        mock_publish.assert_called_once_with(self.team.id, notebook.short_id, 8, diff=None)
