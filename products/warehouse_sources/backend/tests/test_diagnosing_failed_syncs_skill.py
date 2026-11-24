import re
from pathlib import Path

import pytest

from products.warehouse_sources.backend.presentation.views.external_data_source.job_runs import (
    ExternalDataJobSerializers,
)

SKILL_PATH = Path(__file__).parents[2] / "skills" / "diagnosing-failed-warehouse-syncs" / "SKILL.md"
JOBS_TOOL = "external-data-sources-jobs"


def skill_section(start: str, end: str) -> str:
    text = SKILL_PATH.read_text()
    assert start in text, f"section start not found: {start!r}"
    return text.split(start, 1)[1].split(end, 1)[0]


RUNNING_GUIDANCE = {
    "step 2": ("### Step 2", "### Step 3"),
    "recovery F": ("**F. Sync is stuck in `Running` for hours**", "**G."),
    "important notes": ("- **`Running` isn't always healthy", "\n- **"),
}


@pytest.mark.parametrize("name", RUNNING_GUIDANCE)
def test_running_guidance_judges_the_current_job_not_last_synced_at(name: str) -> None:
    section = skill_section(*RUNNING_GUIDANCE[name])
    assert f"`{JOBS_TOOL}`" in section
    assert "`created_at`" in section
    for sentence in re.split(r"(?<=[.:])\s", section):
        if "last_synced_at" in sentence and re.search(r"\b(stuck|orphaned)\b", sentence):
            assert re.search(r"\b(not|doesn't|don't)\b", sentence), sentence


def test_recovery_f_reads_job_history_before_cancelling() -> None:
    section = skill_section(*RUNNING_GUIDANCE["recovery F"])
    assert section.index(f"`{JOBS_TOOL}`") < section.index("`external-data-schemas-cancel`")


def test_skill_lists_the_jobs_tool() -> None:
    tools = skill_section("## Available tools", "## Workflow")
    assert re.search(rf"^\| `{JOBS_TOOL}`\s+\|", tools, flags=re.MULTILINE)


def test_job_fields_named_in_running_guidance_exist_on_the_jobs_api() -> None:
    guidance = "".join(skill_section(*bounds) for bounds in RUNNING_GUIDANCE.values())
    named = set(re.findall(r"`([a-z]+(?:_[a-z]+)+)`", guidance)) - {"last_synced_at", "schema_id", "job_id"}
    assert {"created_at", "finished_at", "rows_synced"} <= named
    assert named <= set(ExternalDataJobSerializers.Meta.fields)
