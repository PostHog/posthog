from collections.abc import Sequence

from attr import dataclass
from django.forms import ValidationError

from posthog.clickhouse.client import sync_execute
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.models import Team, User
from posthog.schema import CachedCodebaseTreeQueryResponse, CodebaseTreeQuery, CodebaseTreeResponseItem
from products.editor.backend.models.catalog_tree import ArtifactNode, SerializedArtifact
from products.editor.backend.models.codebase import Codebase
from products.editor.backend.queries.codebase_tree import CodebaseTreeQueryRunner


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
        )
        response = query_runner.run(ExecutionMode.CALCULATE_BLOCKING_ALWAYS)
        if not isinstance(response, CachedCodebaseTreeQueryResponse):
            raise ValidationError("Failed to load the tree.")

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

        result = ArtifactNode.compare(server_tree, client_tree)
        added, deleted = result["added"], result["deleted"]

        nodes: dict[str, SerializedArtifact] = {}
        for node in client_tree_nodes:
            nodes[node["id"]] = node
        for node in server_tree_nodes:
            nodes[node["id"]] = node

        self._insert_catalog_nodes(added, deleted, nodes)

        return added

    def _sync_new_tree(self, client_tree_nodes: list[SerializedArtifact]) -> list[str]:
        client_nodes: dict[str, SerializedArtifact] = {node["id"]: node for node in client_tree_nodes}
        added = [node["id"] for node in client_tree_nodes]
        self._insert_catalog_nodes(added, [], client_nodes)
        # check integrity
        return added

    def _insert_catalog_nodes(
        self,
        new_nodes: Sequence[str],
        deleted_nodes: Sequence[str],
        mapping: dict[str, SerializedArtifact],
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

        def insert_node(i: int, node_id: str, is_deleted: bool):
            artifact = mapping[node_id]
            args.update(
                {
                    f"artifact_id_{i}": artifact["id"],
                    f"parent_artifact_id_{i}": artifact["parent_id"] if "parent_id" in artifact else "",
                    f"is_deleted_{i}": is_deleted,
                    f"type_{i}": artifact["type"],
                }
            )
            rows.append(
                f"(%(team_id)s, %(user_id)s, %(codebase_id)s, %(branch)s, %(artifact_id_{i})s, %(parent_artifact_id_{i})s, %(type_{i})s, %(is_deleted_{i})s)"
            )

        for i, node_id in enumerate(new_nodes):
            insert_node(i, node_id, False)

        for i, node_id in enumerate(deleted_nodes):
            insert_node(len(new_nodes) + i, node_id, True)

        prepared_query = query + ", ".join(rows)
        sync_execute(prepared_query, args, team_id=self.team.id)
