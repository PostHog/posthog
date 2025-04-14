from posthog.hogql.constants import LimitContext
from posthog.schema import CodebaseTreeQuery, CodebaseTreeResponseItem
from posthog.test.base import BaseTest, ClickhouseTestMixin, snapshot_clickhouse_queries
from products.editor.backend.models.codebase import Codebase
from products.editor.backend.test import CatalogEntry, EditorTestQueryHelpersMixin

from ..codebase_tree import CodebaseTreeQueryRunner


class TestCodebaseTree(EditorTestQueryHelpersMixin, ClickhouseTestMixin, BaseTest):
    def setUp(self):
        super().setUp()
        self.codebase = Codebase.objects.create(team=self.team, user=self.user)

    @snapshot_clickhouse_queries
    def test_returns_codebase_tree(self):
        self._create_codebase_catalog(
            [
                CatalogEntry(artifact_id="root", parent_artifact_id=None, branch="main"),
                CatalogEntry(artifact_id="dir", parent_artifact_id="root", branch="main"),
                CatalogEntry(artifact_id="file", parent_artifact_id="dir", type="file", branch="main"),
            ]
        )

        response = CodebaseTreeQueryRunner(
            CodebaseTreeQuery(userId=self.user.id, codebaseId=str(self.codebase.id), branch="main"), self.team
        ).run()

        expected_result = [
            CodebaseTreeResponseItem(id="root", parentId=None, synced=True, type="dir"),
            CodebaseTreeResponseItem(id="dir", parentId="root", synced=True, type="dir"),
            CodebaseTreeResponseItem(id="file", parentId="dir", synced=False, type="file"),
        ]

        self.assertCountEqual(expected_result, response.results)

    @snapshot_clickhouse_queries
    def test_handles_empty_branch(self):
        """`branch` is a required string. If it's not provided or none, it must use an empty string."""
        self._create_codebase_catalog([CatalogEntry(artifact_id="root")])
        expected_result = [CodebaseTreeResponseItem(id="root", parentId=None, synced=True, type="dir")]

        response = CodebaseTreeQueryRunner(
            CodebaseTreeQuery(userId=self.user.id, codebaseId=str(self.codebase.id)), self.team
        ).run()
        self.assertCountEqual(expected_result, response.results)

        response = CodebaseTreeQueryRunner(
            CodebaseTreeQuery(userId=self.user.id, codebaseId=str(self.codebase.id), branch=""), self.team
        ).run()
        self.assertCountEqual(expected_result, response.results)

    @snapshot_clickhouse_queries
    def test_applies_higher_row_limit(self):
        """The query must apply a higher row limit than the default of 50k."""
        with self.capture_select_queries() as queries:
            CodebaseTreeQueryRunner(
                CodebaseTreeQuery(userId=self.user.id, codebaseId=str(self.codebase.id)),
                self.team,
                limit_context=LimitContext.EDITOR,
            ).run()
            self.assertIn("LIMIT 1000000", queries[0])

    def test_synced_artifacts(self):
        """The response items must have synced=True if the artifact is synced."""
        self._create_codebase_catalog(
            [
                CatalogEntry(artifact_id="root"),
                CatalogEntry(artifact_id="file1", parent_artifact_id="root", type="file"),
                CatalogEntry(artifact_id="file2", parent_artifact_id="root", type="file"),
            ]
        )
        self._create_artifacts([{"id": "file1", "type": "file", "parent_id": "root"}])

        response = CodebaseTreeQueryRunner(
            CodebaseTreeQuery(userId=self.user.id, codebaseId=str(self.codebase.id)), self.team
        ).run()

        expected_result = [
            CodebaseTreeResponseItem(id="root", parentId=None, synced=True, type="dir"),
            CodebaseTreeResponseItem(id="file1", parentId="root", synced=True, type="file"),
            CodebaseTreeResponseItem(id="file2", parentId="root", synced=False, type="file"),
        ]
        self.assertCountEqual(expected_result, response.results)

    def test_multiple_users(self):
        """Test should return only artifacts for the specified user."""
        # First user (self.user) data
        self._create_codebase_catalog(
            [
                CatalogEntry(artifact_id="root", user_id=self.user.id),
                CatalogEntry(artifact_id="file1", parent_artifact_id="root", type="file", user_id=self.user.id),
            ]
        )

        # Second user data (static ID 999)
        other_user_id = 999
        self._create_codebase_catalog(
            [
                CatalogEntry(artifact_id="other-root", user_id=other_user_id),
                CatalogEntry(
                    artifact_id="other-file", parent_artifact_id="other-root", type="file", user_id=other_user_id
                ),
            ]
        )

        # Query for first user
        first_user_response = CodebaseTreeQueryRunner(
            CodebaseTreeQuery(userId=self.user.id, codebaseId=str(self.codebase.id)), self.team
        ).run()

        first_user_expected = [
            CodebaseTreeResponseItem(id="root", parentId=None, synced=True, type="dir"),
            CodebaseTreeResponseItem(id="file1", parentId="root", synced=False, type="file"),
        ]
        self.assertCountEqual(first_user_expected, first_user_response.results)

        # Query for second user
        second_user_response = CodebaseTreeQueryRunner(
            CodebaseTreeQuery(userId=other_user_id, codebaseId=str(self.codebase.id)), self.team
        ).run()

        second_user_expected = [
            CodebaseTreeResponseItem(id="other-root", parentId=None, synced=True, type="dir"),
            CodebaseTreeResponseItem(id="other-file", parentId="other-root", synced=False, type="file"),
        ]
        self.assertCountEqual(second_user_expected, second_user_response.results)

    def test_collapsed_sign_rows(self):
        """Test that rows with sign=1 and sign=-1 are properly collapsed."""
        from datetime import datetime

        now = datetime.now()

        # Create row with sign=1
        self._create_codebase_catalog(
            [
                CatalogEntry(artifact_id="item1", timestamp=now, sign=1),
                # Create exact same row but with sign=-1, should collapse
                CatalogEntry(artifact_id="item1", timestamp=now, sign=-1),
                # This should appear in results
                CatalogEntry(artifact_id="item2", timestamp=now, sign=1),
            ]
        )

        response = CodebaseTreeQueryRunner(
            CodebaseTreeQuery(userId=self.user.id, codebaseId=str(self.codebase.id)), self.team
        ).run()

        # Only item2 should remain as item1 had sign 1 and -1 canceling each other
        expected_result = [
            CodebaseTreeResponseItem(id="item2", parentId=None, synced=True, type="dir"),
        ]
        self.assertCountEqual(expected_result, response.results)

    def test_timestamp_priority(self):
        """Test that the latest row with sign=1 is prioritized over later rows with sign=-1."""
        from datetime import datetime, timedelta

        now = datetime.now()
        earlier = now - timedelta(hours=1)
        later = now + timedelta(hours=1)

        self._create_codebase_catalog(
            [
                # Create initial entry
                CatalogEntry(artifact_id="file", parent_artifact_id="dir1", type="file", timestamp=earlier, sign=1),
                # Create an update with different parent
                CatalogEntry(artifact_id="file", parent_artifact_id="dir2", type="file", timestamp=now, sign=1),
                # Create a delete entry with even later timestamp - should NOT take precedence
                CatalogEntry(artifact_id="file", parent_artifact_id="dir2", type="file", timestamp=later, sign=-1),
                # Add the parent directories
                CatalogEntry(artifact_id="dir1", timestamp=earlier, sign=1),
                CatalogEntry(artifact_id="dir2", timestamp=earlier, sign=1),
            ]
        )

        response = CodebaseTreeQueryRunner(
            CodebaseTreeQuery(userId=self.user.id, codebaseId=str(self.codebase.id)), self.team
        ).run()

        # The file should still appear with parent dir2, even though a later sign=-1 row exists
        expected_result = [
            CodebaseTreeResponseItem(id="dir1", parentId=None, synced=True, type="dir"),
            CodebaseTreeResponseItem(id="dir2", parentId=None, synced=True, type="dir"),
            CodebaseTreeResponseItem(id="file", parentId="dir2", synced=False, type="file"),
        ]
        self.assertCountEqual(expected_result, response.results)
