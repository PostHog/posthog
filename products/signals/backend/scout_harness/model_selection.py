"""Resolve which LLM the scout agent runs on, gated by the `scouts-glm` flag.

Default posture: leave the agent model unset (`None`) so the sandbox agent server uses its
built-in default. When `scouts-glm` is enabled for a team, scouts run on glm-5.2 instead, so an
open-weights model can be compared against the default on the real scout workload with no deploy —
flip the flag and the next dispatched run picks it up. The resolved string is passed straight
through `CustomPromptSandboxContext.model` → `Task.create_and_run` → the agent server.

This is a separate, boolean per-team gate from the `signals-scout` enrollment/limits payload flag
in `team_limits.py` — that one decides *whether* a team runs scouts; this one decides *on which
model*.
"""

from __future__ import annotations

import structlog
import posthoganalytics

from posthog.exceptions_capture import capture_exception
from posthog.models.team.team import Team

logger = structlog.get_logger(__name__)

# Boolean gate: when enabled for a team, its scouts run on glm-5.2.
SCOUTS_GLM_FLAG = "scouts-glm"

# glm-5.2 as the gateway routes it: the Cloudflare-provider model id, reachable over the Anthropic
# Messages path the sandbox agent speaks (see services/llm-gateway). Passed verbatim as the agent
# model override — the gateway maps it to its Cloudflare backend.
GLM_MODEL = "@cf/zai-org/glm-5.2"


def resolve_scout_model(team: Team) -> str | None:
    """The agent-model override for a team's scout runs, or `None` to keep the agent-server default.

    Returns `GLM_MODEL` when `scouts-glm` is enabled for the team, else `None`. Evaluated against
    the team's organization + project groups so the rollout can be targeted either way in the flag
    UI (or ramped by percentage on the stable per-team distinct_id). A flag-read failure is
    swallowed and falls back to the default model — gating the model must never be able to fail a
    scout run.
    """
    try:
        enabled = posthoganalytics.feature_enabled(
            SCOUTS_GLM_FLAG,
            distinct_id=str(team.uuid),
            groups={"organization": str(team.organization_id), "project": str(team.id)},
            group_properties={
                "organization": {"id": str(team.organization_id)},
                "project": {"id": str(team.id)},
            },
            only_evaluate_locally=False,
            send_feature_flag_events=False,
        )
    except Exception as error:
        capture_exception(error)
        return None
    return GLM_MODEL if enabled else None
