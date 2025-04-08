from collections.abc import Sequence
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
    def build_tree(files: Sequence[SerializedArtifact]) -> "ArtifactNode":
        nodes = {}
        for file in files:
            nodes[file["id"]] = ArtifactNode(file["id"], file["type"], [])

        # Build parent-child relationships
        for file in files:
            if file["parent_id"] is not None:
                nodes[file["parent_id"]].children.append(nodes[file["id"]])

        return nodes[files[0]["id"]]

    @staticmethod
    def compare(server: "ArtifactNode", client: "ArtifactNode") -> tuple[list[str], list[str]]:
        """
        Compare server and client nodes recursively and return added/deleted nodes.

        Returns:
            Dictionary with keys 'added' and 'deleted', each containing a list of
            (hash, type) tuples representing nodes that were added or deleted.
        """
        result = {"added": [], "deleted": []}

        # Base case: hashes are the same, no changes
        if server.hash == client.hash:
            return result

        # If node types are different, consider it a deletion and addition
        if server.type != client.type:
            result["deleted"].append(server.hash)
            result["added"].append(client.hash)
            return result

        # For files, if hashes differ, it's a deletion and addition
        if server.type == "file" and server.hash != client.hash:
            result["deleted"].append(server.hash)
            result["added"].append(client.hash)
            return result

        # For directories, recursively compare children
        if server.type == "dir":
            server_children_map = {child.hash: child for child in server.children}
            client_children_map = {child.hash: child for child in client.children}

            # Find deleted nodes (in server but not in client)
            for hash in server_children_map.keys():
                if hash not in client_children_map:
                    result["deleted"].append(hash)

            # Find added nodes (in client but not in server)
            for hash in client_children_map.keys():
                if hash not in server_children_map:
                    result["added"].append(hash)

            # For nodes that exist in both, compare recursively
            for hash in set(server_children_map.keys()) & set(client_children_map.keys()):
                if hash in server_children_map and hash in client_children_map:
                    child_result = ArtifactNode.compare(server_children_map[hash], client_children_map[hash])
                    result["added"].extend(child_result["added"])
                    result["deleted"].extend(child_result["deleted"])

        return result["added"], result["deleted"]
