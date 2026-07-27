"""Tests for manifest loading and extends resolution."""

from __future__ import annotations

from pathlib import Path

import pytest
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
            "config": {"commands_dir": "tools/hogli-commands/hogli_commands"},
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


class TestCommandsDir:
    """Test local command package resolution."""

    def test_commands_dir_is_explicit(self, tmp_path: Path) -> None:
        (tmp_path / "hogli").mkdir()

        with (
            patch.object(Manifest, "_load", return_value={"config": {}}),
            patch("hogli.manifest.REPO_ROOT", tmp_path),
            patch("hogli.manifest.MANIFEST_FILE", tmp_path / "hogli.yaml"),
        ):
            manifest = Manifest()
            assert manifest.commands_dir is None

    def test_commands_dir_resolves_configured_path(self, tmp_path: Path) -> None:
        commands_dir = tmp_path / "tools" / "hogli-commands" / "hogli_commands"
        commands_dir.mkdir(parents=True)

        with (
            patch.object(
                Manifest,
                "_load",
                return_value={"config": {"commands_dir": "tools/hogli-commands/hogli_commands"}},
            ),
            patch("hogli.manifest.REPO_ROOT", tmp_path),
            patch("hogli.manifest.MANIFEST_FILE", tmp_path / "hogli.yaml"),
        ):
            manifest = Manifest()
            assert manifest.commands_dir == commands_dir.resolve()

    def test_commands_dir_rejects_missing_configured_path(self, tmp_path: Path) -> None:
        with (
            patch.object(
                Manifest,
                "_load",
                return_value={"config": {"commands_dir": "tools/missing_commands"}},
            ),
            patch("hogli.manifest.REPO_ROOT", tmp_path),
            patch("hogli.manifest.MANIFEST_FILE", tmp_path / "hogli.yaml"),
        ):
            manifest = Manifest()
            with pytest.raises(ValueError, match="does not exist"):
                _ = manifest.commands_dir

    def test_commands_dir_rejects_absolute_path(self, tmp_path: Path) -> None:
        commands_dir = tmp_path / "tools" / "hogli-commands" / "hogli_commands"
        commands_dir.mkdir(parents=True)

        with (
            patch.object(
                Manifest,
                "_load",
                return_value={"config": {"commands_dir": str(commands_dir)}},
            ),
            patch("hogli.manifest.REPO_ROOT", tmp_path),
            patch("hogli.manifest.MANIFEST_FILE", tmp_path / "hogli.yaml"),
        ):
            manifest = Manifest()
            with pytest.raises(ValueError, match="must be relative"):
                _ = manifest.commands_dir


class TestEnvConfig:
    """Test `config.env` schema parsing.

    Uses monkeypatch (not `with patch(...)`) so the module-level REPO_ROOT
    swap survives the assertions — the existing TestCommandsDir style of
    asserting inside a `with patch` block doesn't compose with `pytest.raises`
    or with multi-assertion tests.
    """

    @pytest.fixture
    def manifest_at(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """Factory: build a Manifest rooted at tmp_path with the given config."""
        # Resolve through symlinks once so equality checks work on macOS where
        # /var/folders -> /private/var/folders.
        repo = tmp_path.resolve()

        def _build(config: dict) -> Manifest:
            monkeypatch.setattr("hogli.manifest.REPO_ROOT", repo)
            monkeypatch.setattr("hogli.manifest.MANIFEST_FILE", repo / "hogli.yaml")
            monkeypatch.setattr(Manifest, "_load", lambda self: {"config": config})
            return Manifest()

        return _build

    def test_unset_returns_empty_and_none(self, manifest_at) -> None:
        """Without `config.env`, both accessors stay quiet — generic hogli is transparent."""
        manifest = manifest_at({})
        assert manifest.env_files == []
        assert manifest.secrets_config is None

    def test_env_files_resolves_repo_relative_paths(self, tmp_path: Path, manifest_at) -> None:
        manifest = manifest_at({"env": {"files": [".env.development", ".env.services"]}})
        repo = tmp_path.resolve()
        assert manifest.env_files == [repo / ".env.development", repo / ".env.services"]

    def test_env_files_rejects_absolute_path(self, tmp_path: Path, manifest_at) -> None:
        manifest = manifest_at({"env": {"files": [str(tmp_path / ".env")]}})
        with pytest.raises(ValueError, match="must be relative"):
            _ = manifest.env_files

    def test_env_files_rejects_escape_outside_repo(self, manifest_at) -> None:
        manifest = manifest_at({"env": {"files": ["../etc/passwd"]}})
        with pytest.raises(ValueError, match="outside the repo root"):
            _ = manifest.env_files

    def test_env_files_rejects_non_list(self, manifest_at) -> None:
        manifest = manifest_at({"env": {"files": ".env"}})
        with pytest.raises(ValueError, match="must be a list"):
            _ = manifest.env_files

    def test_env_files_rejects_non_string_entry(self, manifest_at) -> None:
        """YAML can drop a number or mapping into the list — reject explicitly so
        we don't silently `str()`-coerce it into a surprise path like `.` or `42`."""
        manifest = manifest_at({"env": {"files": [".env.development", 42]}})
        with pytest.raises(ValueError, match="non-empty strings"):
            _ = manifest.env_files

    def test_secrets_config_full(self, tmp_path: Path, manifest_at) -> None:
        manifest = manifest_at(
            {
                "env": {
                    "secrets": {
                        "file": ".env.local",
                        "marker": "op://",
                        "wrap": ["op", "run", "--env-file", "{file}", "--"],
                    }
                }
            }
        )
        cfg = manifest.secrets_config
        assert cfg is not None
        assert cfg["file"] == tmp_path.resolve() / ".env.local"
        assert cfg["marker"] == "op://"
        assert cfg["wrap"] == ["op", "run", "--env-file", "{file}", "--"]

    def test_secrets_config_requires_file(self, manifest_at) -> None:
        manifest = manifest_at({"env": {"secrets": {"marker": "op://", "wrap": ["op", "run", "--"]}}})
        with pytest.raises(ValueError, match="file is required"):
            _ = manifest.secrets_config

    def test_secrets_config_requires_marker(self, manifest_at) -> None:
        """Marker must be set + non-empty: 'always wrap' would force a process
        exec on every invocation, and an empty string is too ambiguous to
        deserve a behavior."""
        manifest = manifest_at({"env": {"secrets": {"file": ".env.local", "wrap": ["op", "run", "--"]}}})
        with pytest.raises(ValueError, match="marker is required"):
            _ = manifest.secrets_config

    def test_secrets_config_rejects_empty_marker(self, manifest_at) -> None:
        manifest = manifest_at({"env": {"secrets": {"file": ".env.local", "marker": "", "wrap": ["op"]}}})
        with pytest.raises(ValueError, match="marker is required"):
            _ = manifest.secrets_config

    def test_secrets_config_rejects_empty_wrap(self, manifest_at) -> None:
        manifest = manifest_at({"env": {"secrets": {"file": ".env.local", "marker": "op://", "wrap": []}}})
        with pytest.raises(ValueError, match="must not be empty"):
            _ = manifest.secrets_config

    def test_secrets_config_rejects_non_string_wrap_items(self, manifest_at) -> None:
        manifest = manifest_at(
            {"env": {"secrets": {"file": ".env.local", "marker": "op://", "wrap": ["op", 42, "--"]}}}
        )
        with pytest.raises(ValueError, match="list of strings"):
            _ = manifest.secrets_config
