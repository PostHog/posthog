from collections import defaultdict
from collections.abc import Sequence

from django.forms import ValidationError

from posthog.clickhouse.client import sync_execute
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.models import Team, User
from posthog.schema import CachedCodebaseTreeQueryResponse, CodebaseTreeQuery, CodebaseTreeResponseItem
from products.editor.backend.models.catalog_tree import ArtifactNode, SerializedArtifact
from products.editor.backend.models.codebase import Codebase
from products.editor.backend.queries.codebase_tree import CodebaseTreeQueryRunner


class CodebaseSyncService:
    def __init__(self, team: Team, user: User, codebase: Codebase, branch: str | None):
        self.team = team
        self.user = user
        self.codebase = codebase
        # Empty string as the schema for this field is non-nullable.
        self.branch = branch or ""

    def sync(self, tree: list[ArtifactNode]) -> list[str]:
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
        self, tree: list[SerializedArtifact], server_tree: list[CodebaseTreeResponseItem]
    ) -> list[str]:
        client_nodes: dict[str, SerializedArtifact] = {node["id"]: node for node in tree}
        server_nodes: dict[str, SerializedArtifact] = {
            server_node.id: server_node.model_dump() for server_node in server_tree
        }

        client_tree = ArtifactNode.build_tree(tree)
        server_tree = ArtifactNode.build_tree(server_nodes.values())

        added, deleted = ArtifactNode.compare(server_tree, client_tree)

        nodes_by_type: dict[str, list[str]] = defaultdict(list)
        for node in added:
            nodes_by_type[client_nodes[node]["type"]].append(node)

        # Delete unused nodes
        self._insert_artifacts(deleted, server_nodes, delete=True)

        # Create new directories
        self._insert_artifacts(nodes_by_type["dir"], client_nodes, delete=False)

        return nodes_by_type["file"]

    def _sync_new_tree(self, tree: list[SerializedArtifact]) -> list[str]:
        client_nodes: dict[str, SerializedArtifact] = {node["id"]: node for node in tree}
        nodes_by_type: dict[str, list[str]] = defaultdict(list)

        for node_id, node in client_nodes.items():
            nodes_by_type[node["type"]].append(node_id)

        # Create new directories
        self._insert_artifacts(nodes_by_type["dir"], client_nodes, delete=False)

        return nodes_by_type["file"]

    def _insert_artifacts(
        self, nodes: Sequence[str], mapping: dict[str, SerializedArtifact], delete: bool | None = None
    ):
        query = "INSERT INTO codebase_catalog (team_id, user_id, codebase_id, branch, artifact_id, parent_artifact_id, type, is_deleted) VALUES"
        rows: list[str] = []
        args = {
            "team_id": self.team.id,
            "user_id": self.user.id,
            "codebase_id": self.codebase.id,
            "branch": self.branch,
        }
        for i, node_id in enumerate(nodes):
            artifact = mapping[node_id]
            args.update(
                {
                    f"artifact_id_{i}": artifact["id"],
                    f"parent_artifact_id_{i}": artifact["parent_id"] if "parent_id" in artifact else None,
                    f"is_deleted_{i}": delete or False,
                    f"type_{i}": artifact["type"],
                }
            )
            rows.append(
                f"(%(team_id)s, %(user_id)s, %(codebase_id)s, %(branch)s, %(artifact_id_{i})s, %(parent_artifact_id_{i})s, %(type_{i})s, %(is_deleted_{i})s)"
            )
        prepared_query = query + ", ".join(rows)
        sync_execute(prepared_query, args, team_id=self.team.id)
