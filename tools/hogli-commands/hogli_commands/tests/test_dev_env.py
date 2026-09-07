from __future__ import annotations

import pytest

from hogli_commands import dev_env


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("POSTHOG_DEV_ENV", raising=False)
    monkeypatch.delenv("DEVENV_ROOT", raising=False)


class TestDevEnvKind:
    @pytest.mark.parametrize(
        "forced,devenv_on_path,devenv_root,expected",
        [
            ("flox", True, "/repo", "flox"),
            ("devenv", False, None, "devenv"),
            (None, True, None, "devenv"),
            (None, False, "/repo", "devenv"),
            (None, False, None, "flox"),
            ("nonsense", False, None, "flox"),
        ],
    )
    def test_selection(self, monkeypatch, forced, devenv_on_path, devenv_root, expected):
        if forced is not None:
            monkeypatch.setenv("POSTHOG_DEV_ENV", forced)
        if devenv_root is not None:
            monkeypatch.setenv("DEVENV_ROOT", devenv_root)
        monkeypatch.setattr(dev_env.shutil, "which", lambda _name: "/usr/bin/devenv" if devenv_on_path else None)

        assert dev_env.dev_env_kind() == expected


class TestIsDevenvActive:
    def test_true_inside_a_devenv_shell(self, monkeypatch):
        monkeypatch.setenv("DEVENV_ROOT", "/repo")
        assert dev_env.is_devenv_active() is True

    def test_false_when_only_the_binary_is_installed(self, monkeypatch):
        monkeypatch.setattr(dev_env.shutil, "which", lambda _name: "/usr/bin/devenv")
        assert dev_env.is_devenv_active() is False
