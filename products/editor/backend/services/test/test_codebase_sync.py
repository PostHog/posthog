from posthog.test.base import BaseTest, ClickhouseTestMixin
from products.editor.backend.models.codebase import Codebase
from products.editor.backend.test import EditorTestQueryHelpersMixin

from ..codebase_sync import ArtifactNode, CodebaseSyncService, SerializedArtifact


class TestArtifactNode(BaseTest):
    def test_build_tree_nodes(self):
        tree = [
            {"id": "root", "type": "dir", "parent_id": None},
            {"id": "file_1", "type": "file", "parent_id": "root"},
            {"id": "file_2", "type": "file", "parent_id": "root"},
        ]
        node = ArtifactNode.build_tree(tree)
        self.assertEqual(node.hash, "root")
        self.assertEqual(node.children[0].hash, "file_1")
        self.assertEqual(node.children[1].hash, "file_2")
        self.assertEqual(node.children[0].children, [])
        self.assertEqual(node.children[1].children, [])

    def test_build_tree_with_disjoint_trees(self):
        """Must prioritize the most recent node."""
        tree = [
            {"id": "root", "type": "dir", "parent_id": None},
            {"id": "dir", "type": "dir", "parent_id": "root"},
            {"id": "root_new", "type": "dir", "parent_id": None},
            {"id": "dir_new", "type": "dir", "parent_id": "root_new"},
        ]
        node = ArtifactNode.build_tree(tree)
        self.assertEqual(node.hash, "root_new")

    def test_build_tree_raises_without_root(self):
        """Must have a root node."""
        tree = [
            {"id": "dir", "type": "dir", "parent_id": "root"},
        ]
        with self.assertRaises(ValueError):
            ArtifactNode.build_tree(tree)

    def test_build_tree_raises_on_corrupt_tree(self):
        """Must raise if a node is missing."""
        tree = [
            {"id": "root", "type": "dir", "parent_id": None},
            {"id": "dir_new", "type": "dir", "parent_id": "root_new"},
        ]
        with self.assertRaises(ValueError):
            ArtifactNode.build_tree(tree)

    def test_compare_same_hashes(self):
        """Test when hashes are the same, nothing should be returned."""
        server_tree = [
            {"id": "same", "type": "dir", "parent_id": None},
        ]
        server_node = ArtifactNode.build_tree(server_tree)

        client_tree = [
            {"id": "same", "type": "dir", "parent_id": None},
        ]
        client_node = ArtifactNode.build_tree(client_tree)

        added, deleted = ArtifactNode.compare(server_node, client_node)

        self.assertEqual(added, set())
        self.assertEqual(deleted, set())

    def test_compare_single_node_different_hashes(self):
        """Test when a single node has different hashes, should return both added and deleted with the respective hashes."""
        server_tree = [
            {"id": "server", "type": "dir", "parent_id": None},
        ]
        server_node = ArtifactNode.build_tree(server_tree)

        client_tree = [
            {"id": "client", "type": "dir", "parent_id": None},
        ]
        client_node = ArtifactNode.build_tree(client_tree)

        added, deleted = ArtifactNode.compare(server_node, client_node)

        self.assertEqual(added, {"client"})
        self.assertEqual(deleted, {"server"})

    def test_compare_different_root_same_leaves(self):
        """
        Test when root hash is different but leaf hashes are the same.
        Should return all nodes in added and deleted to relink parent ids.
        """
        # Create server tree: root_s -> [file1, file2]
        server_tree = [
            {"id": "root_s", "type": "dir", "parent_id": None},
            {"id": "file1", "type": "file", "parent_id": "root_s"},
            {"id": "file2", "type": "file", "parent_id": "root_s"},
        ]
        server_root = ArtifactNode.build_tree(server_tree)

        # Create client tree: root_c -> [file1, file2]
        client_tree = [
            {"id": "root_c", "type": "dir", "parent_id": None},
            {"id": "file1", "type": "file", "parent_id": "root_c"},
            {"id": "file2", "type": "file", "parent_id": "root_c"},
        ]
        client_root = ArtifactNode.build_tree(client_tree)

        added, deleted = ArtifactNode.compare(server_root, client_root)

        # When the root changes but leaf nodes have same hashes:
        # 1. All nodes should be in added set (to relink parent_id)
        # 2. All nodes should be in deleted set (to relink parent_id)
        self.assertEqual(added, {"root_c", "file1", "file2"})
        self.assertEqual(deleted, {"root_s", "file1", "file2"})

    def test_compare_subtree_removed(self):
        """
        Test when a subtree is completely removed.
        All deleted nodes must be in the deleted set but not in the added set.
        """
        # Create server tree: root -> [dir1 -> [file1, file2]]
        server_tree = [
            {"id": "root", "type": "dir", "parent_id": None},
            {"id": "dir1", "type": "dir", "parent_id": "root"},
            {"id": "file1", "type": "file", "parent_id": "dir1"},
            {"id": "file2", "type": "file", "parent_id": "dir1"},
        ]
        server_node = ArtifactNode.build_tree(server_tree)

        # Create client tree: root_new -> [dir1]
        client_tree = [
            {"id": "root_new", "type": "dir", "parent_id": None},
            {"id": "dir2", "type": "dir", "parent_id": "root_new"},
        ]
        client_node = ArtifactNode.build_tree(client_tree)

        added, deleted = ArtifactNode.compare(server_node, client_node)

        # Root nodes have the same hash, so they should not be in added/deleted
        # The deleted subtree should be in the deleted set
        self.assertEqual(added, {"root_new", "dir2"})
        self.assertEqual(deleted, {"root", "dir1", "file1", "file2"})

    def test_compare_subtree_added(self):
        """
        Test when a new subtree is completely added.
        All new nodes must be in the added set but not in the deleted set.
        """
        # Create server tree: root -> []
        server_tree = [
            {"id": "root_old", "type": "dir", "parent_id": None},
            {"id": "dir1_old", "type": "dir", "parent_id": "root_old"},
        ]
        server_node = ArtifactNode.build_tree(server_tree)

        # Create client tree: root -> [dir1 -> [file1, file2]]
        client_tree = [
            {"id": "root", "type": "dir", "parent_id": None},
            {"id": "dir1", "type": "dir", "parent_id": "root"},
            {"id": "file1", "type": "file", "parent_id": "dir1"},
            {"id": "file2", "type": "file", "parent_id": "dir1"},
        ]
        client_node = ArtifactNode.build_tree(client_tree)

        added, deleted = ArtifactNode.compare(server_node, client_node)

        # Root nodes have the same hash, so they should not be marked as deleted
        # The new subtree should be in the added set
        self.assertEqual(added, {"root", "dir1", "file1", "file2"})
        self.assertEqual(deleted, {"root_old", "dir1_old"})

    def test_compare_subtree_modified(self):
        """
        Test when one subtree is removed and another is added simultaneously.
        All deleted nodes must only be in deleted set, all added nodes must only be in the added set.
        """
        # Create server tree: root -> [dir1 -> [file1, file2]]
        server_tree = [
            {"id": "root", "type": "dir", "parent_id": None},
            {"id": "dir1", "type": "dir", "parent_id": "root"},
            {"id": "file1", "type": "file", "parent_id": "dir1"},
            {"id": "file2", "type": "file", "parent_id": "dir1"},
        ]
        server_node = ArtifactNode.build_tree(server_tree)

        # Create client tree: root_new -> [dir2 -> [file3, file4]]
        client_tree = [
            {"id": "root_new", "type": "dir", "parent_id": None},
            {"id": "dir2", "type": "dir", "parent_id": "root_new"},
            {"id": "file3", "type": "file", "parent_id": "dir2"},
            {"id": "file4", "type": "file", "parent_id": "dir2"},
        ]
        client_node = ArtifactNode.build_tree(client_tree)

        added, deleted = ArtifactNode.compare(server_node, client_node)

        # Root appears in both sets for relinking
        # The removed dir1 subtree should be in deleted set
        # The added dir2 subtree should be in added set
        self.assertEqual(added, {"root_new", "dir2", "file3", "file4"})
        self.assertEqual(deleted, {"root", "dir1", "file1", "file2"})


class TestCodebaseSync(ClickhouseTestMixin, EditorTestQueryHelpersMixin, BaseTest):
    def setUp(self):
        super().setUp()
        self.branch = "main"
        self.codebase = Codebase.objects.create(team=self.team, user=self.user)
        self.service = CodebaseSyncService(self.team, self.user, self.codebase, self.branch)

    def _create_tree(self, server_tree: list[SerializedArtifact], create_artifacts: bool | None = True):
        if create_artifacts:
            self._create_artifacts(server_tree)
        return self.service.sync(server_tree)

    def _query_server_tree(self):
        response = self.service._retrieve_server_tree()
        nodes = [
            {"id": item.id, "type": item.type, "parent_id": item.parentId, "synced": item.synced} for item in response
        ]
        return nodes

    def test_sync_new_codebase(self):
        client_tree = [
            {"id": "root", "type": "dir", "parent_id": None, "synced": True},
            {"id": "dir", "type": "dir", "parent_id": "root", "synced": True},
            {"id": "file_1", "type": "file", "parent_id": "dir", "synced": False},
        ]
        diverging_nodes = self.service.sync(client_tree)
        self.assertEqual(diverging_nodes, ["file_1"])
        self.assertCountEqual(self._query_server_tree(), client_tree)

    def test_sync_new_codebase_with_existing_artifacts(self):
        """
        Root
            dir_1
                dir_2
                    dir_3
                    file_1
                    file_2
            dir_4
                file_3
                file_4
            file_5
        """
        server_tree: list[SerializedArtifact] = [
            {"id": "root", "type": "dir", "parent_id": None},
            {"id": "dir_1", "type": "dir", "parent_id": "root"},
            {"id": "dir_2", "type": "dir", "parent_id": "dir_1"},
            {"id": "dir_3", "type": "dir", "parent_id": "dir_2"},
            {"id": "file_1", "type": "file", "parent_id": "dir_2"},
            {"id": "file_2", "type": "file", "parent_id": "dir_2"},
            {"id": "dir_4", "type": "dir", "parent_id": "root"},
            {"id": "file_3", "type": "file", "parent_id": "dir_4"},
            {"id": "file_4", "type": "file", "parent_id": "dir_4"},
            {"id": "file_5", "type": "file", "parent_id": "root"},
        ]

        client_tree = [
            {"id": "root", "type": "dir", "parent_id": None, "synced": True},
            {"id": "dir", "type": "dir", "parent_id": "root", "synced": True},
            {"id": "file_1", "type": "file", "parent_id": "dir", "synced": True},
        ]
        self._create_artifacts(server_tree)
        diverging_nodes = self.service.sync(client_tree)
        self.assertEqual(diverging_nodes, [])
        self.assertCountEqual(self._query_server_tree(), client_tree)

    def test_sync_new_codebase_verifies_tree(self):
        """Broken tree should raise an error."""
        client_tree = [
            {"id": "root", "type": "dir", "parent_id": None},
            {"id": "dir", "type": "dir", "parent_id": "root2"},
        ]
        with self.assertRaises(ValueError):
            self.service.sync(client_tree)

    def test_sync_replaces_leaf_node(self):
        """
        Re-link the leaf nodes to a new parent tree.

        Root
            dir_1
                file_1
                file_2 - R
                file_3 - A
        """
        self._create_tree(
            [
                {"id": "root", "type": "dir", "parent_id": None},
                {"id": "dir", "type": "dir", "parent_id": "root"},
                {"id": "file_1", "type": "file", "parent_id": "dir"},
                {"id": "file_2", "type": "file", "parent_id": "dir"},
            ]
        )

        client_tree = [
            {"id": "root_new", "type": "dir", "parent_id": None, "synced": True},
            {"id": "dir_new", "type": "dir", "parent_id": "root_new", "synced": True},
            {"id": "file_1", "type": "file", "parent_id": "dir_new", "synced": True},
            {"id": "file_3", "type": "file", "parent_id": "dir_new", "synced": False},
        ]

        diverging_nodes = self.service.sync(client_tree)
        self.assertEqual(diverging_nodes, ["file_3"])
        self.assertCountEqual(self._query_server_tree(), client_tree)

    def test_sync_finds_missing_leaf_nodes(self):
        """
        Leaf node hashes don't differ since files are the same.
        However, if the file hasn't been uploaded yet, we should return it.

        Root
            dir_1
                file_1
        """
        self._create_tree(
            [
                {"id": "root", "type": "dir", "parent_id": None},
                {"id": "dir", "type": "dir", "parent_id": "root"},
                {"id": "file_1", "type": "file", "parent_id": "dir"},
            ],
            create_artifacts=False,
        )

        client_tree = [
            {"id": "root_new", "type": "dir", "parent_id": None, "synced": True},
            {"id": "dir_new", "type": "dir", "parent_id": "root_new", "synced": True},
            {"id": "file_1", "type": "file", "parent_id": "dir_new", "synced": False},
        ]

        diverging_nodes = self.service.sync(client_tree)
        self.assertEqual(diverging_nodes, ["file_1"])
        self.assertCountEqual(self._query_server_tree(), client_tree)

    def test_sync_ignores_synced_leaf_nodes(self):
        """
        Leaf node hashes are the same, but parent id is different.
        If the file is already synced, we should ignore it and only re-link the parent.

        Root
            dir_1
                file_1
        """
        self._create_tree(
            [
                {"id": "root", "type": "dir", "parent_id": None},
                {"id": "dir", "type": "dir", "parent_id": "root"},
                {"id": "file_1", "type": "file", "parent_id": "dir"},
            ],
        )

        client_tree = [
            {"id": "root_new", "type": "dir", "parent_id": None, "synced": True},
            {"id": "dir_new", "type": "dir", "parent_id": "root_new", "synced": True},
            {"id": "file_1", "type": "file", "parent_id": "dir_new", "synced": True},
        ]

        diverging_nodes = self.service.sync(client_tree)
        self.assertEqual(diverging_nodes, [])
        self.assertCountEqual(self._query_server_tree(), client_tree)

    def test_sync_ignores_tree_if_root_is_the_same(self):
        """
        Ignore all nodes if the root hash is the same.

        Root
            dir_1
                file_1
        """
        server_tree = [
            {"id": "root", "type": "dir", "parent_id": None, "synced": True},
            {"id": "dir", "type": "dir", "parent_id": "root", "synced": True},
            {"id": "file_1", "type": "file", "parent_id": "dir", "synced": True},
        ]
        self._create_tree(server_tree)

        diverging_nodes = self.service.sync(server_tree)
        self.assertEqual(diverging_nodes, [])
        self.assertCountEqual(self._query_server_tree(), server_tree)

    def test_sync_handles_new_branch(self):
        """
        Leaf nodes can stay the same while new branches are added,
        so we don't return them.

        Root
            dir_1
                file_1
            dir_2
                file_2
        """
        tree = [
            {"id": "root", "type": "dir", "parent_id": None, "synced": True},
            {"id": "dir_1", "type": "dir", "parent_id": "root", "synced": True},
            {"id": "file_1", "type": "file", "parent_id": "dir_1", "synced": True},
            {"id": "dir_2", "type": "dir", "parent_id": "root", "synced": True},
            {"id": "file_2", "type": "file", "parent_id": "dir_2", "synced": True},
        ]
        self._create_tree(tree)

        diverging_nodes = CodebaseSyncService(self.team, self.user, self.codebase, "new-branch").sync(tree)
        self.assertEqual(diverging_nodes, [])
        self.assertCountEqual(self._query_server_tree(), tree)
