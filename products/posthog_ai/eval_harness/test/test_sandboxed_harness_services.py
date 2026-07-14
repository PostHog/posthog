from __future__ import annotations

import os
import zipfile
from pathlib import Path

import pytest
from unittest.mock import MagicMock, patch

from products.posthog_ai.eval_harness.harness.services import package_local_skills_archive, start_mcp_server


def test_package_local_skills_archive_is_deterministic_and_excludes_cache_markers(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    skill_dir = skills_dir / "sample"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("# Sample\n")
    (skills_dir / ".build-hash").write_text("cache")
    hidden_dir = skills_dir / ".cache"
    hidden_dir.mkdir()
    (hidden_dir / "state").write_text("cache")

    first = package_local_skills_archive(skills_dir, tmp_path / "first.zip")
    second = package_local_skills_archive(skills_dir, tmp_path / "second.zip")

    assert first.read_bytes() == second.read_bytes()
    with zipfile.ZipFile(first) as archive:
        assert archive.namelist() == ["sample/SKILL.md"]


@pytest.mark.parametrize(
    "exec_skills_enabled,skill_archive_url,expected_flag_value",
    [
        (True, "http://localhost:18788/skills.zip?v=abc", True),
        (False, None, False),
    ],
)
def test_start_mcp_server_isolates_the_selected_skill_delivery(
    tmp_path: Path,
    exec_skills_enabled: bool,
    skill_archive_url: str | None,
    expected_flag_value: bool,
) -> None:
    mcp_dir = tmp_path / "services" / "mcp"
    (mcp_dir / "node_modules").mkdir(parents=True)
    stop = MagicMock()

    with (
        patch.dict(os.environ, {"POSTHOG_MCP_SKILLS_URL": "https://stale.example/skills.zip"}),
        patch("products.posthog_ai.eval_harness.harness.services.settings.BASE_DIR", tmp_path),
        patch(
            "products.posthog_ai.eval_harness.harness.services.LONG_LIVED_SUBPROCESSES.start",
            return_value=(MagicMock(), stop),
        ) as start,
    ):
        result = start_mcp_server(
            "http://localhost:18000",
            skill_archive_url,
            exec_skills_enabled=exec_skills_enabled,
        )

    env = start.call_args.kwargs["env"]
    assert env["FEATURE_FLAG_OVERRIDES"] == f'{{"mcp-exec-skills": {str(expected_flag_value).lower()}}}'
    if skill_archive_url is None:
        assert "POSTHOG_MCP_SKILLS_URL" not in env
    else:
        assert env["POSTHOG_MCP_SKILLS_URL"] == skill_archive_url
    assert result is stop
