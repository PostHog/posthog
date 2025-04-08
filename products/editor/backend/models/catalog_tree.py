from typing import Literal, TypedDict


class SerializedArtifact(TypedDict):
    artifact_id: str
    artifact_type: Literal["file", "dir"]
    children: list["SerializedArtifact"]


class ArtifactNode:
    def __init__(self, hash: str, type: Literal["file", "dir"], children: list["ArtifactNode"]):
        self.hash = hash
        self.type = type
        self.children = children

    @staticmethod
    def build_tree(files: list[SerializedArtifact]) -> "ArtifactNode":
        nodes = {}
        for file in files:
            nodes[file["artifact_id"]] = ArtifactNode(file["artifact_id"], file["artifact_type"], [])

        for file in files:
            nodes[file["artifact_id"]].children = [nodes[child["artifact_id"]] for child in file["children"]]

        return nodes[files[0]["artifact_id"]]

    @staticmethod
    def compare(server: "ArtifactNode", client: "ArtifactNode") -> dict[str, list[tuple[str, Literal["file", "dir"]]]]:
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
            result["deleted"].append((server.hash, server.type))
            result["added"].append((client.hash, client.type))
            return result

        # For files, if hashes differ, it's a deletion and addition
        if server.type == "file" and server.hash != client.hash:
            result["deleted"].append((server.hash, server.type))
            result["added"].append((client.hash, client.type))
            return result

        # For directories, recursively compare children
        if server.type == "dir":
            server_children_map = {child.hash: child for child in server.children}
            client_children_map = {child.hash: child for child in client.children}

            # Find deleted nodes (in server but not in client)
            for hash, node in server_children_map.items():
                if hash not in client_children_map:
                    result["deleted"].append((hash, node.type))

            # Find added nodes (in client but not in server)
            for hash, node in client_children_map.items():
                if hash not in server_children_map:
                    result["added"].append((hash, node.type))

            # For nodes that exist in both, compare recursively
            for hash in set(server_children_map.keys()) & set(client_children_map.keys()):
                if hash in server_children_map and hash in client_children_map:
                    child_result = ArtifactNode.compare(server_children_map[hash], client_children_map[hash])
                    result["added"].extend(child_result["added"])
                    result["deleted"].extend(child_result["deleted"])

        return result["added"], result["deleted"]
