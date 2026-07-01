from datetime import timedelta

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.utils import timezone

from posthog.models import Organization, Team, User
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
                    "attrs": {
                        "query": '{"kind":"HogQLQuery","query":"select 1"}',
                        "view": True,
                        "edit": False,
                        "chartSettings": {
                            "yAxis": [{"settings": {"formatting": {"decimalPlaces": 1.0, "threshold": 1.5}}}]
                        },
                    },
                },
                {
                    "type": "paragraph",
                    "content": [
                        {
                            "type": "text",
                            "text": "invalid link",
                            "marks": [{"type": "link", "attrs": {"href": "https://www.juheapi.com）：≈"}}],
                        }
                    ],
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
        assert '"decimalPlaces":1' in markdown
        assert '"decimalPlaces":1.0' not in markdown
        assert '"threshold":1.5' in markdown
        assert "invalid link" in markdown
        assert "juheapi" not in markdown
        assert "hideFilters" in markdown

    def test_converts_v1_widget_nodes_with_filters_closed_by_default(self) -> None:
        content = {
            "type": "doc",
            "content": [
                {
                    "type": "ph-query",
                    "attrs": {
                        "query": {"kind": "SavedInsightNode", "shortId": "ZcWG6625"},
                        "title": "Activation",
                    },
                },
                {
                    "type": "ph-recording",
                    "attrs": {
                        "id": "018b4205-f670-7fa8-928a-040abaaf596d",
                        "title": "Session replay",
                    },
                },
                {
                    "type": "ph-insight",
                    "attrs": {
                        "id": "legacyInsight",
                    },
                },
                {
                    "type": "ph-query",
                    "attrs": {
                        "query": {"kind": "SavedInsightNode", "shortId": "open"},
                        "edit": True,
                    },
                },
            ],
        }

        markdown = convert_notebook_content_to_markdown(content)

        assert (
            '<Query hideFilters query={{"kind":"SavedInsightNode","shortId":"ZcWG6625"}} title="Activation" />'
            in markdown
        )
        assert '<Recording hideFilters id="018b4205-f670-7fa8-928a-040abaaf596d" title="Session replay" />' in markdown
        assert '<Query hideFilters query={{"kind":"SavedInsightNode","shortId":"legacyInsight"}} />' in markdown
        assert '<Query query={{"kind":"SavedInsightNode","shortId":"open"}} />' in markdown

    def test_converts_legacy_markdown_ast_alias_nodes_without_losing_structure(self) -> None:
        content = {
            "type": "doc",
            "content": [
                {
                    "type": "bullet_list",
                    "content": [
                        {
                            "type": "list_item",
                            "content": [{"type": "paragraph", "content": [{"type": "text", "text": "first"}]}],
                        }
                    ],
                },
                {
                    "type": "ordered_list",
                    "content": [
                        {
                            "type": "list_item",
                            "content": [{"type": "paragraph", "content": [{"type": "text", "text": "step"}]}],
                        }
                    ],
                },
                {
                    "type": "code_block",
                    "attrs": {"language": "sql"},
                    "content": [
                        {"type": "text", "text": "select 1"},
                        {"type": "hardBreak"},
                        {"type": "text", "text": "select 2"},
                    ],
                },
                {
                    "type": "table",
                    "content": [
                        {
                            "type": "table_row",
                            "content": [
                                {
                                    "type": "table_header",
                                    "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Metric"}]}],
                                },
                                {
                                    "type": "table_cell",
                                    "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Value"}]}],
                                },
                            ],
                        }
                    ],
                },
                {
                    "type": "callout",
                    "attrs": {"emoji": "!"},
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [
                                {"type": "text", "text": "Heads", "marks": [{"type": "strong"}]},
                                {"type": "text", "text": " and "},
                                {"type": "text", "text": "note", "marks": [{"type": "em"}]},
                            ],
                        }
                    ],
                },
                {"type": "ph-link", "attrs": {"href": "https://app.posthog.com/cohorts/37958"}},
            ],
        }

        markdown = convert_notebook_content_to_markdown(content)

        assert "- first" in markdown
        assert "1. step" in markdown
        assert "```sql\nselect 1\nselect 2\n```" in markdown
        assert "| Metric | Value |" in markdown
        assert "| --- | --- |" in markdown
        assert "> ! **Heads** and *note*" in markdown
        assert "[https://app.posthog.com/cohorts/37958](https://app.posthog.com/cohorts/37958)" in markdown


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
    def test_batches_dry_run_and_apply_without_processing_every_pending_notebook(self, mock_publish) -> None:
        notebooks = [
            Notebook.objects.create(
                team=self.team,
                title=f"Batch {index}",
                content={
                    "type": "doc",
                    "content": [{"type": "paragraph", "content": [{"type": "text", "text": f"body {index}"}]}],
                },
            )
            for index in range(3)
        ]

        dry_run_result = migrate_notebooks_to_markdown(user=self.user, team_id=self.team.id, dry_run=True, batch_size=2)
        for notebook in notebooks:
            notebook.refresh_from_db()

        assert dry_run_result.converted == 2
        assert dry_run_result.batch_size == 2
        assert dry_run_result.pending_before == 3
        assert dry_run_result.pending_after == 3
        assert len(dry_run_result.previews) == 2
        assert all(notebook.content["content"][0]["type"] != "ph-markdown-notebook" for notebook in notebooks)

        with self.captureOnCommitCallbacks(execute=True):
            first_apply_result = migrate_notebooks_to_markdown(
                user=self.user, team_id=self.team.id, dry_run=False, batch_size=2
            )

        for notebook in notebooks:
            notebook.refresh_from_db()

        assert first_apply_result.converted == 2
        assert first_apply_result.pending_before == 3
        assert first_apply_result.pending_after == 1
        assert sum(notebook.content["content"][0]["type"] == "ph-markdown-notebook" for notebook in notebooks) == 2

        with self.captureOnCommitCallbacks(execute=True):
            second_apply_result = migrate_notebooks_to_markdown(
                user=self.user, team_id=self.team.id, dry_run=False, batch_size=2
            )

        for notebook in notebooks:
            notebook.refresh_from_db()

        assert second_apply_result.converted == 1
        assert second_apply_result.pending_before == 1
        assert second_apply_result.pending_after == 0
        assert all(notebook.content["content"][0]["type"] == "ph-markdown-notebook" for notebook in notebooks)
        assert mock_publish.call_count == 3

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
        original_modified_at = timezone.now() - timedelta(days=30)
        original_modifier = self._create_user("original@example.com")
        notebook = Notebook.objects.create(
            team=self.team,
            title="Convert me",
            content=rich_content,
            version=7,
            last_modified_at=original_modified_at,
            last_modified_by=original_modifier,
        )
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
        assert notebook.last_modified_at == original_modified_at
        assert notebook.last_modified_by_id == original_modifier.id
        assert notebook.text_content is not None
        assert "<Comment" in notebook.text_content
        assert "keep this" in notebook.text_content
        assert notebook.content == build_markdown_notebook_content(notebook.text_content)
        assert other_notebook.content["content"][0]["type"] == "paragraph"

        log = ActivityLog.objects.get(scope="Notebook", item_id=notebook.short_id, activity="updated")
        detail = log.detail
        assert isinstance(detail, dict)
        changes = detail["changes"]
        assert isinstance(changes, list)
        changes_by_field = {change["field"]: change for change in changes if isinstance(change, dict)}
        assert changes_by_field["content"]["before"] == rich_content
        assert changes_by_field["content"]["after"] == notebook.content
        assert changes_by_field["version"]["before"] == 7
        assert changes_by_field["version"]["after"] == 8
        assert "last_modified_at" not in changes_by_field
        assert "last_modified_by" not in changes_by_field
        assert log.user_id == original_modifier.id
        assert log.user_id != self.user.id
        assert log.created_at == original_modified_at + timedelta(seconds=1)
        mock_publish.assert_called_once_with(self.team.id, notebook.short_id, 8, diff=None)

    def test_apply_scopes_mention_label_lookup_to_notebook_organization(self) -> None:
        same_org_user = self._create_user("same@example.com", first_name="Same")
        outside_org = Organization.objects.create(name="Outside")
        outside_user = User.objects.create_and_join(outside_org, "leaked@example.com", None, "Leaked")
        notebook = Notebook.objects.create(
            team=self.team,
            title="Mentions",
            content={
                "type": "doc",
                "content": [
                    {
                        "type": "paragraph",
                        "content": [
                            {"type": "ph-mention", "attrs": {"id": same_org_user.id}},
                            {"type": "text", "text": " "},
                            {"type": "ph-mention", "attrs": {"id": outside_user.id}},
                        ],
                    }
                ],
            },
        )

        migrate_notebooks_to_markdown(user=self.user, team_id=self.team.id, dry_run=False)

        notebook.refresh_from_db()
        assert notebook.text_content is not None
        assert f'<mention id="{same_org_user.id}">@Same</mention>' in notebook.text_content
        assert f'<mention id="{outside_user.id}">@member</mention>' in notebook.text_content
        assert "Leaked" not in notebook.text_content
        assert "leaked@example.com" not in notebook.text_content
