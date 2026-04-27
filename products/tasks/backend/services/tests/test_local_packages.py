from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from unittest.mock import patch

from products.tasks.backend.services.local_packages import (
    BUILD_OUTPUT_SUBDIR,
    PACKAGE_NAMES,
    get_local_posthog_code_packages,
)


def _populate_monorepo(root: Path, *, with_dist: bool = True, package_names: tuple[str, ...] = PACKAGE_NAMES) -> Path:
    for name in package_names:
        pkg = root / "packages" / name
        target = pkg / BUILD_OUTPUT_SUBDIR if with_dist else pkg
        target.mkdir(parents=True)
        if with_dist:
            (target / "index.js").write_text(f"console.log('{name}');\n")
    return root


@contextmanager
def _env(*, debug: bool, monorepo_root: str | None) -> Iterator[None]:
    with patch("products.tasks.backend.services.local_packages.settings") as s:
        s.DEBUG = debug
        env = {"LOCAL_POSTHOG_CODE_MONOREPO_ROOT": monorepo_root or "", "LOCAL_TWIG_MONOREPO_ROOT": ""}
        with patch.dict("os.environ", env):
            yield


@pytest.fixture
def fake_monorepo(tmp_path: Path) -> Path:
    return _populate_monorepo(tmp_path)


class TestGetLocalPosthogCodePackages:
    def test_returns_none_when_not_debug(self, fake_monorepo: Path) -> None:
        with _env(debug=False, monorepo_root=str(fake_monorepo)):
            assert get_local_posthog_code_packages() is None

    def test_returns_none_when_env_var_unset(self) -> None:
        with _env(debug=True, monorepo_root=None):
            assert get_local_posthog_code_packages() is None

    def test_returns_none_when_env_var_points_to_nonexistent_dir(self, tmp_path: Path) -> None:
        with _env(debug=True, monorepo_root=str(tmp_path / "nope")):
            assert get_local_posthog_code_packages() is None

    def test_returns_none_when_source_dirs_missing(self, tmp_path: Path) -> None:
        _populate_monorepo(tmp_path, package_names=("agent",))
        with _env(debug=True, monorepo_root=str(tmp_path)):
            assert get_local_posthog_code_packages() is None

    def test_returns_none_when_dist_missing(self, tmp_path: Path) -> None:
        _populate_monorepo(tmp_path, with_dist=False)
        with _env(debug=True, monorepo_root=str(tmp_path)):
            assert get_local_posthog_code_packages() is None

    def test_returns_packages_when_everything_present(self, fake_monorepo: Path) -> None:
        with _env(debug=True, monorepo_root=str(fake_monorepo)):
            packages = get_local_posthog_code_packages()
        assert packages is not None
        assert [p.name for p in packages] == list(PACKAGE_NAMES)
        assert packages[0].sandbox_install_path == "/scripts/node_modules/@posthog/agent"
        assert packages[0].sandbox_build_output_path == "/scripts/node_modules/@posthog/agent/dist"
        assert packages[0].build_output_path == fake_monorepo / "packages" / "agent" / "dist"
