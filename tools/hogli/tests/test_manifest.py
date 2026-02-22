"""Tests for manifest loading and extends resolution."""

from __future__ import annotations

from unittest.mock import patch

from hogli.manifest import Manifest


class TestExtendsResolution:
    """Test extends: inheritance pattern."""

    def test_resolve_extends_merges_base_config(self) -> None:
        """Child command inherits all fields from parent."""
        test_data = {
            "commands": {
                "test:parent": {
                    "description": "Parent command",
                    "cmd": "echo parent",
                    "services": ["postgres"],
                },
                "test:parent:child": {
                    "extends": "test:parent",
                    "cmd": "echo child",
                },
            }
        }

        with patch.object(Manifest, "_load", return_value={}):
            manifest = Manifest()
            manifest._data = test_data
            manifest._resolve_extends(test_data)

        parent = manifest.get_command_config("test:parent")
        child = manifest.get_command_config("test:parent:child")

        assert parent is not None
        assert child is not None
        # Child inherits description
        assert child.get("description") == parent.get("description")
        # Child inherits services
        assert child.get("services") == parent.get("services")
        # Child has its own cmd
        assert "child" in child.get("cmd", "")
        assert "child" not in parent.get("cmd", "")

    def test_resolve_extends_preserves_extends_key(self) -> None:
        """Extends key is preserved for tree display."""
        test_data = {
            "commands": {
                "test:parent": {"cmd": "echo parent"},
                "test:parent:child": {"extends": "test:parent", "cmd": "echo child"},
            }
        }

        with patch.object(Manifest, "_load", return_value={}):
            manifest = Manifest()
            manifest._data = test_data
            manifest._resolve_extends(test_data)

        child = manifest.get_command_config("test:parent:child")

        assert child is not None
        assert child.get("extends") == "test:parent"

    def test_resolve_extends_child_overrides_parent(self) -> None:
        """Child fields override parent fields."""
        test_data = {
            "commands": {
                "test:parent": {"cmd": "echo parent", "description": "Base"},
                "test:parent:child": {"extends": "test:parent", "cmd": "echo child"},
            }
        }

        with patch.object(Manifest, "_load", return_value={}):
            manifest = Manifest()
            manifest._data = test_data
            manifest._resolve_extends(test_data)

        parent = manifest.get_command_config("test:parent")
        child = manifest.get_command_config("test:parent:child")

        assert parent is not None
        assert child is not None
        # Commands are different
        assert parent.get("cmd") != child.get("cmd")
        assert "parent" in parent.get("cmd", "")
        assert "child" in child.get("cmd", "")


class TestGetChildrenForCommand:
    """Test children lookup."""

    def test_returns_children_for_parent(self) -> None:
        """Returns list of commands that extend the parent."""
        test_data = {
            "commands": {
                "test:parent": {"cmd": "echo parent"},
                "test:parent:child": {"extends": "test:parent", "cmd": "echo child"},
            }
        }

        with patch.object(Manifest, "_load", return_value={}):
            manifest = Manifest()
            manifest._data = test_data
            manifest._resolve_extends(test_data)

        children = manifest.get_children_for_command("test:parent")

        assert "test:parent:child" in children

    def test_returns_empty_for_leaf_command(self) -> None:
        """Returns empty list for commands with no children."""
        test_data = {
            "commands": {
                "test:parent": {"cmd": "echo parent"},
                "test:parent:child": {"extends": "test:parent", "cmd": "echo child"},
            }
        }

        with patch.object(Manifest, "_load", return_value={}):
            manifest = Manifest()
            manifest._data = test_data
            manifest._resolve_extends(test_data)

        children = manifest.get_children_for_command("test:parent:child")

        assert children == []

    def test_returns_empty_for_nonexistent_command(self) -> None:
        """Returns empty list for unknown commands."""
        with patch.object(Manifest, "_load", return_value={}):
            manifest = Manifest()

        children = manifest.get_children_for_command("nonexistent:command")

        assert children == []

    def test_children_are_sorted(self) -> None:
        """Children are returned in sorted order."""
        test_data = {
            "commands": {
                "test:parent": {"cmd": "echo parent"},
                "test:parent:zebra": {"extends": "test:parent", "cmd": "echo z"},
                "test:parent:alpha": {"extends": "test:parent", "cmd": "echo a"},
            }
        }

        with patch.object(Manifest, "_load", return_value={}):
            manifest = Manifest()
            manifest._data = test_data
            manifest._resolve_extends(test_data)

        children = manifest.get_children_for_command("test:parent")

        assert children == sorted(children)
        assert children == ["test:parent:alpha", "test:parent:zebra"]


class TestManifestCommandEnumeration:
    """Test command enumeration excludes non-command sections."""

    def test_get_all_commands_excludes_config_section(self) -> None:
        """Config keys should not be returned as commands."""
        test_data = {
            "config": {"commands_dir": "common/posthog_hogli"},
            "core": {
                "dev:setup": None,
                "dev:reset": {"cmd": "echo reset"},
            },
        }

        with patch.object(Manifest, "_load", return_value={}):
            manifest = Manifest()
            manifest._data = test_data

        commands = manifest.get_all_commands()

        assert "dev:setup" in commands
        assert "dev:reset" in commands
        assert "commands_dir" not in commands

    def test_get_command_config_returns_none_for_non_dict_command(self) -> None:
        """Commands with null config should return None."""
        test_data = {
            "core": {
                "dev:setup": None,
                "dev:reset": {"cmd": "echo reset"},
            },
        }

        with patch.object(Manifest, "_load", return_value={}):
            manifest = Manifest()
            manifest._data = test_data

        assert manifest.get_command_config("dev:setup") is None
        assert manifest.get_command_config("dev:reset") == {"cmd": "echo reset"}
