from typing import TYPE_CHECKING

from posthog.models.user import User

from products.tasks.backend.facade import api as tasks_facade

if TYPE_CHECKING:
    from products.signals.backend.artefact_attribution import ArtefactAttribution
    from products.signals.backend.models import SignalReport


_PHASE_NAMES = {
    "research": "Research agent",
    "implementation": "Implementation agent",
    "repo_selection": "Repository selection agent",
    "discussion": "Discussion agent",
    "scout": "Scout agent",
}
_CLIENT_NAMES = {"codex": "Codex", "claude-code": "Claude Code", "cursor": "Cursor"}


def claim_display_name(report: "SignalReport", actor: "ArtefactAttribution") -> str:
    if actor.task_id:
        phase = tasks_facade.signal_report_pipeline_stage(actor.task_id, report.team_id)
        if not phase:
            runs = report.associated_task_runs(report_id=str(report.id), team_id=report.team_id)
            phase = next((run.type for run in reversed(runs) if str(run.task_id) == actor.task_id), None)
        if phase and phase.startswith("scout:"):
            return f"Scout {phase.removeprefix('scout:')}"
        return _PHASE_NAMES.get(phase or "", "PostHog agent")
    if actor.user_id:
        user = User.objects.filter(id=actor.user_id).only("first_name").first()
        name = (user.first_name.strip() if user and user.first_name else "") or "User"
        if actor.kind == "agent":
            client = (actor.agent_name or "").strip()
            client = "agent" if client.lower() in {"", "mcp", "unknown"} else _CLIENT_NAMES.get(client.lower(), client)
            return f"{name}'s {client}"
        return name
    return "PostHog"
