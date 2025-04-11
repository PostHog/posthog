from collections.abc import Generator, Sequence
from typing import Literal, TypedDict

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
from products.editor.backend.models.catalog import CodebaseCatalogType
from products.editor.backend.models.codebase import Codebase
from products.editor.backend.queries.codebase_tree import CodebaseTreeQueryRunner
from products.editor.backend.queries.synced_artifacts import SyncedArtifactsQueryRunner


class SerializedArtifact(TypedDict):
    id: str
    type: CodebaseCatalogType
    parent_id: str | None


class ArtifactNode:
    def __init__(self, hash: str, type: Literal["file", "dir"], children: list["ArtifactNode"]):
        self.hash = hash
        self.type = type
        self.children = children

    @staticmethod
    def build_tree(nodes: list[SerializedArtifact]) -> "ArtifactNode":
        if not nodes:
            raise ValueError("Tree must have at least one node.")
        try:
            tree: dict[str, ArtifactNode] = {}
            for node in nodes:
                tree[node["id"]] = ArtifactNode(node["id"], node["type"], [])

            # Build parent-child relationships and find the root node
            root = None
            for node in nodes:
                if node["parent_id"]:
                    tree[node["parent_id"]].children.append(tree[node["id"]])
                elif root is None:
                    root = tree[node["id"]]
        except KeyError:
            raise ValueError("Tree is corrupt.")
        if not root:
            raise ValueError("Tree must have a root node.")
        return root

    @staticmethod
    def compare(server: "ArtifactNode", client: "ArtifactNode") -> tuple[set[str], set[str]]:
        """
        Compare server and client nodes recursively and return added/deleted nodes.

        Returns:
            Tuple of two sets: first set containing hashes of nodes that were added,
            second set containing hashes of nodes that were deleted.
        """
        added_set: set[str] = set()
        deleted_set: set[str] = set()

        # Base case: hashes are the same, no changes
        if server.hash == client.hash:
            return added_set, deleted_set
        else:
            # Hashes don't match, update the state
            added_set.add(client.hash)
            deleted_set.add(server.hash)

        server_children_map = {child.hash: child for child in server.children}
        client_children_map = {child.hash: child for child in client.children}

        server_hashes = set(server_children_map.keys())
        client_hashes = set(client_children_map.keys())

        # Find deleted nodes (in server but not in client)
        for hash in server_hashes - client_hashes:
            deleted_set.update(server_children_map[hash].traverse())

        # Find added nodes (in client but not in server)
        for hash in client_hashes - server_hashes:
            added_set.update(client_children_map[hash].traverse())

        # For nodes that exist in both, compare recursively
        for hash in server_hashes & client_hashes:
            # Relink parent_ids
            added_set.add(hash)

            # Compare children
            child_added, child_deleted = ArtifactNode.compare(server_children_map[hash], client_children_map[hash])
            added_set.update(child_added)
            deleted_set.update(child_deleted)

        return added_set, deleted_set

    def traverse(self) -> Generator[str, None, None]:
        """Get all nested hashes."""

        # Using a set avoids yielding duplicates if a hash appears multiple times
        # (though in a content-addressed Merkle tree this shouldn't happen unless
        # identical files/dirs exist at different paths, which is valid)
        visited_hashes: set[str] = set()

        def dfs(node: "ArtifactNode"):
            if node.hash not in visited_hashes:
                visited_hashes.add(node.hash)
                yield node.hash
                for child in node.children:
                    yield from dfs(child)

        yield from dfs(self)


class CodebaseSyncService:
    def __init__(self, team: Team, user: User, codebase: Codebase, branch: str | None):
        self.team = team
        self.user = user
        self.codebase = codebase
        # Empty string as the schema for this field is non-nullable.
        self.branch = branch or ""

    def sync(self, client_tree: list[ArtifactNode]) -> list[str]:
        """
        Sync the server tree with the client tree.

        Returns:
            List of artifact ids (file hashes) that were diverging.
        """
        if not client_tree:
            return []

        server_tree = self._retrieve_server_tree()

        # handle new codebase
        if not server_tree:
            return self._sync_new_tree(client_tree)
        else:
            return self._sync_existing_tree(client_tree, server_tree)

    def _retrieve_server_tree(self) -> list[CodebaseTreeResponseItem]:
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
        return response.results

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
        # Verify tree first
        ArtifactNode.build_tree(client_tree_nodes)

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
