from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

import pytest

from products.feature_flags.evals.eval_instrument_flags import SKILL_NAME, require_instrument_skill

if TYPE_CHECKING:
    from products.tasks.backend.facade.agents import CustomPromptSandboxContext


def _context(runtime_adapter: str | None) -> CustomPromptSandboxContext:
    # The guard reads only runtime_adapter; a namespace stands in for the real
    # sandbox context here.
    return cast(
        "CustomPromptSandboxContext",
        SimpleNamespace(team_id=1, user_id=1, runtime_adapter=runtime_adapter),
    )


def _install_skill(base_dir, name: str = SKILL_NAME) -> None:
    skill_file = base_dir / "products" / "posthog_ai" / "dist" / "skills" / name / "SKILL.md"
    skill_file.parent.mkdir(parents=True)
    skill_file.write_text(f"---\nname: {name}\ndescription: Stand-in\n---\nBody\n")


def test_guard_refuses_codex_before_looking_for_the_skill(tmp_path, settings) -> None:
    settings.BASE_DIR = tmp_path
    _install_skill(tmp_path)

    with pytest.raises(RuntimeError, match="claude runtime only"):
        require_instrument_skill(_context("codex"))


@pytest.mark.parametrize("runtime_adapter", [None, "claude"])
def test_guard_refuses_when_the_graded_skill_is_absent(tmp_path, settings, runtime_adapter: str | None) -> None:
    settings.BASE_DIR = tmp_path

    with pytest.raises(RuntimeError, match="is not in products/posthog_ai/dist/skills"):
        require_instrument_skill(_context(runtime_adapter))


@pytest.mark.parametrize("runtime_adapter", [None, "claude"])
def test_guard_returns_the_overlay_path_when_the_skill_is_present(
    tmp_path, settings, runtime_adapter: str | None
) -> None:
    settings.BASE_DIR = tmp_path
    _install_skill(tmp_path)

    seed = require_instrument_skill(_context(runtime_adapter))

    assert seed["skill_source"] == "context-mill overlay"
    assert seed["skill_file"].endswith(f"{SKILL_NAME}/SKILL.md")
