from collections.abc import Sequence

from attr import dataclass

from posthog.clickhouse.client import sync_execute
from posthog.hogql.constants import LimitContext
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.models import Team, User
from posthog.schema import (
    CachedCodebaseTreeQueryResponse,
    CachedSyncedArtifactsQueryResponse,
    CodebaseTreeQuery,
    CodebaseTreeResponseItem,
    SyncedArtifactsQuery,
)
from products.editor.backend.models.catalog_tree import ArtifactNode, SerializedArtifact
from products.editor.backend.models.codebase import Codebase
from products.editor.backend.queries.codebase_tree import CodebaseTreeQueryRunner
from products.editor.backend.queries.synced_artifacts import SyncedArtifactsQueryRunner


@dataclass
class CodebaseSyncStatus:
    pass


class CodebaseSyncService:
    def __init__(self, team: Team, user: User, codebase: Codebase, branch: str | None):
        self.team = team
        self.user = user
        self.codebase = codebase
        # Empty string as the schema for this field is non-nullable.
        self.branch = branch or ""

    def sync(self, tree: list[ArtifactNode]) -> list[str]:
        if not tree:
            return []

        query_runner = CodebaseTreeQueryRunner(
            query=CodebaseTreeQuery(
                userId=self.user.id,
                codebaseId=str(self.codebase.id),
                branch=self.branch,
            ),
            team=self.team,
            limit_context=LimitContext.EDITOR,
        )
        response = query_runner.run(ExecutionMode.CALCULATE_BLOCKING_ALWAYS)
        if not isinstance(response, CachedCodebaseTreeQueryResponse):
            raise ValueError("Failed to load the synced tree.")

        # handle new codebase
        if not response.results:
            return self._sync_new_tree(tree)
        else:
            return self._sync_existing_tree(tree, response.results)

    def _sync_existing_tree(
        self, client_tree_nodes: list[SerializedArtifact], server_nodes: list[CodebaseTreeResponseItem]
    ) -> list[str]:
        server_tree_nodes = [
            {"id": server_node.id, "parent_id": server_node.parentId, "type": server_node.type}
            for server_node in server_nodes
        ]

        client_tree = ArtifactNode.build_tree(client_tree_nodes)
        server_tree = ArtifactNode.build_tree(server_tree_nodes)

        added, deleted = ArtifactNode.compare(server_tree, client_tree)

        client_nodes_mapping: dict[str, SerializedArtifact] = {node["id"]: node for node in client_tree_nodes}
        server_nodes_mapping: dict[str, SerializedArtifact] = {node["id"]: node for node in server_tree_nodes}

        self._insert_catalog_nodes(
            [client_nodes_mapping[client_node_id] for client_node_id in added],
            [server_nodes_mapping[server_node_id] for server_node_id in deleted],
        )

        # Find files to sync and check integrity
        files_to_sync: set[str] = set()

        # Tree comparison only finds new files.
        for client_node_id in added:
            if client_nodes_mapping[client_node_id]["type"] == "file":
                files_to_sync.add(client_node_id)

        # Find files we haven't synced yet.
        for server_node in server_nodes:
            if server_node.id not in deleted and not server_node.synced:
                files_to_sync.add(server_node.id)

        return list(files_to_sync)

    def _sync_new_tree(self, client_tree_nodes: list[SerializedArtifact]) -> list[str]:
        self._insert_catalog_nodes(client_tree_nodes, [])
        leaf_nodes = {node["id"] for node in client_tree_nodes if node["type"] == "file"}

        # Check integrity
        query_runner = SyncedArtifactsQueryRunner(
            query=SyncedArtifactsQuery(
                userId=self.user.id,
                codebaseId=str(self.codebase.id),
                artifactIds=list(leaf_nodes),
            ),
            team=self.team,
            limit_context=LimitContext.EDITOR,
        )
        response = query_runner.run(ExecutionMode.CALCULATE_BLOCKING_ALWAYS)
        if not isinstance(response, CachedSyncedArtifactsQueryResponse):
            raise ValueError("Failed to load synced artifacts.")

        # Remove synced artifacts from the leaf nodes.
        for synced_artifact in response.results:
            if synced_artifact.id in leaf_nodes:
                leaf_nodes.remove(synced_artifact.id)

        return list(leaf_nodes)

    def _insert_catalog_nodes(
        self, new_nodes: Sequence[SerializedArtifact], deleted_nodes: Sequence[SerializedArtifact]
    ):
        if not new_nodes and not deleted_nodes:
            return

        query = "INSERT INTO codebase_catalog (team_id, user_id, codebase_id, branch, artifact_id, parent_artifact_id, type, is_deleted) VALUES"
        rows: list[str] = []
        args = {
            "team_id": self.team.id,
            "user_id": self.user.id,
            "codebase_id": self.codebase.id,
            "branch": self.branch,
        }

        def insert_node(i: int, node: SerializedArtifact, is_deleted: bool):
            args.update(
                {
                    f"artifact_id_{i}": node["id"],
                    f"parent_artifact_id_{i}": node["parent_id"] if "parent_id" in node else "",
                    f"is_deleted_{i}": is_deleted,
                    f"type_{i}": node["type"],
                }
            )
            rows.append(
                f"(%(team_id)s, %(user_id)s, %(codebase_id)s, %(branch)s, %(artifact_id_{i})s, %(parent_artifact_id_{i})s, %(type_{i})s, %(is_deleted_{i})s)"
            )

        for i, node in enumerate(new_nodes):
            insert_node(i, node, False)

        for i, node in enumerate(deleted_nodes):
            insert_node(len(new_nodes) + i, node, True)

        prepared_query = query + ", ".join(rows)
        sync_execute(prepared_query, args, team_id=self.team.id)
