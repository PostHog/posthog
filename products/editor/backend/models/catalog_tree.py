from collections.abc import Generator
from typing import Literal, TypedDict

ArtifactType = Literal["file", "dir"]


class SerializedArtifact(TypedDict):
    id: str
    type: ArtifactType
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
            child_result = ArtifactNode.compare(server_children_map[hash], client_children_map[hash])
            added_set.update(child_result["added"])
            deleted_set.update(child_result["deleted"])

        return added_set, deleted_set

    def traverse(self) -> Generator[str, None, None]:
        """Get all nested hashes."""

        def dfs(node: "ArtifactNode"):
            yield node.hash
            for child in node.children:
                yield from dfs(child)

        yield from dfs(self)
