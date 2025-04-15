from datetime import datetime

from posthog.schema import SyncedArtifactsQuery, SyncedArtifactsResponseItem
from posthog.test.base import BaseTest, ClickhouseTestMixin, snapshot_clickhouse_queries
from products.editor.backend.models.codebase import Codebase
from products.editor.backend.test.base import EditorTestQueryHelpersMixin

from ..synced_artifacts import SyncedArtifactsQueryRunner


class TestSyncedArtifacts(EditorTestQueryHelpersMixin, ClickhouseTestMixin, BaseTest):
    def setUp(self):
        super().setUp()
        self.codebase = Codebase.objects.create(
            team=self.team, user=self.user, id="019634cb-5198-0000-ab58-7ba5d8855147"
        )

    @snapshot_clickhouse_queries
    def test_synced_artifacts(self):
        """Must return a single artifact."""
        self._create_artifacts([{"id": "file1", "type": "file", "parent_id": "root"}], user_id=self.stable_user_id)

        response = SyncedArtifactsQueryRunner(
            SyncedArtifactsQuery(userId=self.stable_user_id, codebaseId=str(self.codebase.id), artifactIds=["file1"]),
            self.team,
        ).run()
        self.assertCountEqual(response.results, [SyncedArtifactsResponseItem(id="file1")])

    @snapshot_clickhouse_queries
    def test_artifacts_from_the_list_are_returned(self):
        """Artifacts can be filtered by a list of artifact IDs."""
        self._create_artifacts(
            [
                {"id": "file1", "type": "file", "parent_id": "root"},
                {"id": "file2", "type": "file", "parent_id": "root"},
            ],
            user_id=self.stable_user_id,
        )

        response = SyncedArtifactsQueryRunner(
            SyncedArtifactsQuery(userId=self.stable_user_id, codebaseId=str(self.codebase.id), artifactIds=["file2"]),
            self.team,
        ).run()
        self.assertCountEqual(response.results, [SyncedArtifactsResponseItem(id="file2")])

    def test_handles_multiple_users(self):
        """Artifacts must be scoped to a user."""
        self._create_artifacts(
            [
                {"id": "file1", "type": "file", "parent_id": "root"},
            ],
            user_id=self.stable_user_id,
        )
        self._create_artifacts(
            [
                {"id": "file2", "type": "file", "parent_id": "root"},
            ],
            user_id=100000,
        )

        response = SyncedArtifactsQueryRunner(
            SyncedArtifactsQuery(
                userId=self.stable_user_id, codebaseId=str(self.codebase.id), artifactIds=["file1", "file2"]
            ),
            self.team,
        ).run()
        self.assertCountEqual(response.results, [SyncedArtifactsResponseItem(id="file1")])

        response = SyncedArtifactsQueryRunner(
            SyncedArtifactsQuery(userId=100000, codebaseId=str(self.codebase.id), artifactIds=["file1", "file2"]),
            self.team,
        ).run()
        self.assertCountEqual(response.results, [SyncedArtifactsResponseItem(id="file2")])

    def test_handles_multiple_codebases(self):
        """Artifacts can be filtered by a list of artifact IDs."""
        self._create_artifacts(
            [
                {"id": "file1", "type": "file", "parent_id": "root"},
                {"id": "file2", "type": "file", "parent_id": "root"},
            ],
            user_id=self.stable_user_id,
        )

        another_codebase = "019634cb-5198-0000-ab58-7ba5d8855148"
        self._create_artifacts(
            [
                {"id": "file1", "type": "file", "parent_id": "root"},
            ],
            user_id=self.stable_user_id,
            codebase_id=another_codebase,
        )

        response = SyncedArtifactsQueryRunner(
            SyncedArtifactsQuery(
                userId=self.stable_user_id, codebaseId=str(self.codebase.id), artifactIds=["file1", "file2"]
            ),
            self.team,
        ).run()
        self.assertCountEqual(
            response.results, [SyncedArtifactsResponseItem(id="file1"), SyncedArtifactsResponseItem(id="file2")]
        )

        response = SyncedArtifactsQueryRunner(
            SyncedArtifactsQuery(
                userId=self.stable_user_id, codebaseId=another_codebase, artifactIds=["file1", "file2"]
            ),
            self.team,
        ).run()
        self.assertCountEqual(response.results, [SyncedArtifactsResponseItem(id="file1")])

    def test_returns_distinct_artifacts(self):
        """Must return a single artifact across multiple chunks."""
        self._create_artifacts(
            [
                {"id": "file1", "type": "file", "parent_id": "root", "chunk_id": 0},
                {"id": "file1", "type": "file", "parent_id": "root", "chunk_id": 1},
            ],
            user_id=self.stable_user_id,
        )

        response = SyncedArtifactsQueryRunner(
            SyncedArtifactsQuery(userId=self.stable_user_id, codebaseId=str(self.codebase.id), artifactIds=["file1"]),
            self.team,
        ).run()
        self.assertCountEqual(response.results, [SyncedArtifactsResponseItem(id="file1")])

    def test_omits_deleted_artifacts(self):
        """Must omit deleted artifacts."""
        ts = datetime.now()
        self._create_artifacts(
            [
                {"id": "file1", "type": "file", "parent_id": "root", "is_deleted": 1, "timestamp": ts},
            ],
            user_id=self.stable_user_id,
        )

        response = SyncedArtifactsQueryRunner(
            SyncedArtifactsQuery(userId=self.stable_user_id, codebaseId=str(self.codebase.id), artifactIds=["file1"]),
            self.team,
        ).run()
        self.assertCountEqual(response.results, [])

    def test_omits_deleted_rows_based_on_the_last_timestamp(self):
        """Must return the latest artifact."""
        ts = datetime.now()
        self._create_artifacts(
            [
                {"id": "file1", "type": "file", "parent_id": "root", "is_deleted": 0, "timestamp": ts},
                {"id": "file1", "type": "file", "parent_id": "root", "is_deleted": 1, "timestamp": ts},
            ],
            user_id=self.stable_user_id,
        )

        response = SyncedArtifactsQueryRunner(
            SyncedArtifactsQuery(userId=self.stable_user_id, codebaseId=str(self.codebase.id), artifactIds=["file1"]),
            self.team,
        ).run()
        self.assertCountEqual(response.results, [])
