from __future__ import annotations

import json

import pytest

import click
from hogli_commands.service.scaffold import TEMPLATE_ROOT, bootstrap_service


def create_repo_files(tmp_path) -> None:
    (tmp_path / "services").mkdir()
    (tmp_path / "pnpm-workspace.yaml").write_text("packages:\n    - services/mcp\n    - services/stripe-app\n")
    (tmp_path / ".dockerignore").write_text("*\n!services\n!services/mcp\n")


class TestBootstrapService:
    def test_generates_service_and_registers_workspace_boundaries(self, tmp_path) -> None:
        create_repo_files(tmp_path)

        bootstrap_service(
            name="example-worker",
            dry_run=False,
            force=False,
            repo_root=tmp_path,
            template_root=TEMPLATE_ROOT,
        )

        service_directory = tmp_path / "services" / "example-worker"
        package = json.loads((service_directory / "package.json").read_text())
        assert package["name"] == "@posthog/example-worker"
        assert (service_directory / "src" / "features" / "hello" / "greeting.test.ts").exists()
        assert (service_directory / "tests" / "integration" / "app.integration.test.ts").exists()
        assert (service_directory / "tests" / "e2e" / "service.e2e.test.ts").exists()
        assert (service_directory / "CLAUDE.md").is_symlink()
        assert (service_directory / "CLAUDE.md").readlink().as_posix() == "AGENTS.md"
        assert "    - services/example-worker\n" in (tmp_path / "pnpm-workspace.yaml").read_text()
        assert "!services/example-worker\n" in (tmp_path / ".dockerignore").read_text()

    @pytest.mark.parametrize("name", ["Uppercase", "has_spaces", "-leading", "trailing-"])
    def test_rejects_names_that_cannot_be_package_and_directory_names(self, tmp_path, name) -> None:
        create_repo_files(tmp_path)

        with pytest.raises(click.ClickException, match="Invalid service name"):
            bootstrap_service(
                name=name,
                dry_run=False,
                force=False,
                repo_root=tmp_path,
                template_root=TEMPLATE_ROOT,
            )
