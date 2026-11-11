"""Project and personal agent instructions, written into cloud runs as each agent's user-level AGENTS.md.

Stored apart from PostHog AI memory.
"""

import structlog

from posthog.models.scoping import get_current_team_id
from posthog.models.scoping.manager import resolve_effective_team_id
from posthog.models.team.extensions import get_or_create_team_extension
from posthog.models.team.team import Team
from posthog.models.user import User

from products.signals.backend.facade.agent_instructions import get_agent_instructions
from products.tasks.backend.constants import AGENT_INSTRUCTIONS_STATE_KEY
from products.tasks.backend.models import Task, TaskRun, TeamTasksConfig, UserTasksConfig

logger = structlog.get_logger(__name__)

# Signals uses internal tasks to hide pipeline runs, not to isolate them from project instructions.
SIGNALS_ORIGINS = frozenset(
    {
        Task.OriginProduct.SIGNAL_REPORT,
        Task.OriginProduct.SIGNALS_SCOUT,
        Task.OriginProduct.SIGNALS_SCOUT_SUGGESTIONS,
        Task.OriginProduct.SIGNALS_CHAT,
    }
)

# Runs nobody is driving. They act for the project, so they get the project instructions but
# never their creator's personal ones, which describe how that person likes to work.
PERSONLESS_ORIGINS = frozenset(
    {
        Task.OriginProduct.SIGNAL_REPORT,
        Task.OriginProduct.SIGNALS_SCOUT,
        Task.OriginProduct.SIGNALS_SCOUT_SUGGESTIONS,
        Task.OriginProduct.WORKFLOW,
        Task.OriginProduct.LOOP,
        Task.OriginProduct.SUPPORT_REPLY,
        Task.OriginProduct.REVIEW_HOG,
    }
)

# Infrastructure agents with fixed prompts that user-written instructions must not steer.
EXCLUDED_ORIGINS = frozenset(
    {
        Task.OriginProduct.BUSINESS_KNOWLEDGE,
        Task.OriginProduct.IMAGE_BUILDER,
        Task.OriginProduct.TASK_ANALYSIS,
    }
)

PROJECT_HEADING = "# Project instructions"
PERSONAL_HEADING = "# Personal instructions"


def _canonical_team_id(team_id: int) -> int:
    # Same normalization as ai_run_defaults, which this module can't import: it pulls in the
    # Temporal package, and run-context resolution there imports this module.
    if get_current_team_id() == team_id:
        return team_id
    return resolve_effective_team_id(team_id)


class AgentInstructionsStore:
    def get_project(self, team_id: int) -> str:
        value = (
            TeamTasksConfig.objects.filter(team_id=_canonical_team_id(team_id))
            .values_list("agent_instructions", flat=True)
            .first()
        )
        return value or ""

    def set_project(self, team_id: int, instructions: str) -> str:
        team = Team.objects.get(id=_canonical_team_id(team_id))
        config = get_or_create_team_extension(team, TeamTasksConfig)
        config.agent_instructions = instructions
        config.save(update_fields=["agent_instructions", "updated_at"])
        return instructions

    def get_personal(self, team_id: int, user_id: int) -> str:
        canonical_team_id = _canonical_team_id(team_id)
        value = (
            UserTasksConfig.objects.for_team(canonical_team_id, canonical=True)
            .filter(user_id=user_id)
            .values_list("agent_instructions", flat=True)
            .first()
        )
        return value or ""

    def set_personal(self, team_id: int, user_id: int, instructions: str) -> str:
        canonical_team_id = _canonical_team_id(team_id)
        # team_id repeated in the lookup kwargs: for_team() only filters reads, creation needs it explicitly.
        UserTasksConfig.objects.for_team(canonical_team_id, canonical=True).update_or_create(
            team_id=canonical_team_id,
            user_id=user_id,
            defaults={"agent_instructions": instructions},
        )
        return instructions


class AgentInstructionsResolver:
    def __init__(self, store: AgentInstructionsStore | None = None) -> None:
        self._store = store or AgentInstructionsStore()

    def resolve(self, task: Task, actor_user: User | None, *, ai_stage: str | None = None) -> str | None:
        if task.origin_product in EXCLUDED_ORIGINS or (task.internal and task.origin_product not in SIGNALS_ORIGINS):
            return None
        project = self._store.get_project(task.team_id).strip()
        personal = ""
        if not task.internal and task.origin_product not in PERSONLESS_ORIGINS:
            user_id = actor_user.id if actor_user is not None else task.created_by_id
            if user_id is not None:
                personal = self._store.get_personal(task.team_id, user_id).strip()
        steering = (
            get_agent_instructions(
                team_id=_canonical_team_id(task.team_id), origin_product=task.origin_product, ai_stage=ai_stage
            )
            if task.origin_product in SIGNALS_ORIGINS
            else ""
        )
        return self.render(project, personal, steering)

    @staticmethod
    def render(project: str, personal: str, steering: str = "") -> str | None:
        sections: list[str] = []
        if project:
            sections.append(f"{PROJECT_HEADING}\n\n{project}")
        if steering:
            sections.append(steering)
        if personal:
            sections.append(f"{PERSONAL_HEADING}\n\n{personal}")
        return "\n\n".join(sections) or None


def agent_instructions_state_update(
    task: Task, actor_user: User | None, *, ai_stage: str | None = None
) -> tuple[dict[str, str], list[str]]:
    """The run-state `(updates, remove_keys)` that stamp the resolved instructions on a run.

    An empty result removes the key, so a resumed run never keeps text the user has since cleared.
    """
    instructions = AgentInstructionsResolver().resolve(task, actor_user, ai_stage=ai_stage)
    if instructions is None:
        return {}, [AGENT_INSTRUCTIONS_STATE_KEY]
    return {AGENT_INSTRUCTIONS_STATE_KEY: instructions}, []


def refresh_agent_instructions_state(task_run: TaskRun, user: User, *, reason: str) -> None:
    """Restamp the instructions for `user` on a run that already has a session.

    Best-effort: a failure leaves the run with what it had. The sandbox re-reads the run after
    the transition and rewrites its instruction files.
    """
    run_id = str(task_run.id)
    try:
        updates, remove_keys = agent_instructions_state_update(
            task_run.task, user, ai_stage=(task_run.state or {}).get("ai_stage")
        )
        TaskRun.update_state_atomic(task_run.id, updates=updates, remove_keys=remove_keys)
    except Exception:
        logger.warning("agent_instructions_refresh_failed", run_id=run_id, reason=reason, exc_info=True)
        return
    logger.info("agent_instructions_refreshed", run_id=run_id, reason=reason, present=bool(updates))
