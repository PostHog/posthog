"""Which report-pipeline stage a sandbox request came from.

The pipeline's two agentic stages run in sandboxes that hold an OAuth token bound to their own
task (`sandbox_task_id`). Neither has a `SignalScoutRun` row, so a scratchpad entry they write
cannot name its author the way a scout's does. This module resolves that author from the token's
task instead of taking the agent's word for it.

`ai_stage` is the anchor: the pipeline stamps it once at run creation, server-side, and the
sandbox has no way to set or change it. So a stage read back off the task is provenance, not a
claim — an agent cannot present itself as the other stage, and no agent can present itself as a
scout, whose skill names live on a different column entirely.
"""

from uuid import UUID

from products.signals.backend.scout_harness.note_targets import (
    PIPELINE_AUDIENCE_IMPLEMENTATION,
    PIPELINE_AUDIENCE_REPORT_RESEARCH,
)
from products.tasks.backend.facade import api as tasks_facade

# The `ai_stage` each stage stamps on its task. Shared with the two call sites that write them
# (`report_generation/research.py`, `auto_start.py`) so the write and this read can't drift —
# a renamed stage would otherwise leave every pipeline entry silently unattributed.
AI_STAGE_RESEARCH = "research"
AI_STAGE_IMPLEMENTATION = "implementation"

# Stages that write memory. `repo_selection` is absent because it doesn't, and an unmapped stage
# resolves to no identity rather than a guessed one.
_STAGE_IDENTITIES: dict[str, str] = {
    AI_STAGE_RESEARCH: PIPELINE_AUDIENCE_REPORT_RESEARCH,
    AI_STAGE_IMPLEMENTATION: PIPELINE_AUDIENCE_IMPLEMENTATION,
}


def pipeline_writer_identity(*, task_id: UUID | None, team_id: int) -> str | None:
    """The `pipeline:*` identity behind a task-bound sandbox request, or None.

    None is the normal answer for a scout run, a human, and any other caller: their entries are
    attributed through `created_by_run` or left unattributed, exactly as before.
    """
    if task_id is None:
        return None
    stage = tasks_facade.signal_report_pipeline_stage(task_id, team_id)
    if stage is None:
        return None
    return _STAGE_IDENTITIES.get(stage)
