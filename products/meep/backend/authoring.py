from pathlib import Path
from uuid import UUID

from django.db import transaction

from rest_framework.exceptions import ValidationError

from posthog.models import User

from products.meep.backend.chat import check_access, environment
from products.meep.backend.domain import transition
from products.meep.backend.models import ViewJob, WorkspaceView
from products.meep.backend.task_profiles import MEEP
from products.tasks.backend.facade import api
from products.tasks.backend.facade.profiles import TaskRunOptions

_GUIDE = Path(__file__).resolve().parents[1] / "desktop/crates/meep-render/meep-script/agent/SCRIPT.md"
_OUTPUT = {
    "type": "object",
    "properties": {"source": {"type": "string"}, "reply": {"type": "string"}, "title": {"type": "string"}},
    "required": ["source", "reply", "title"],
    "additionalProperties": False,
}


def advance(view: WorkspaceView) -> None:
    if view.state["deleted"] or view.jobs.filter(finished=False).exists():
        return
    for turn in view.state["turns"]:
        if turn["stage"] != "Queued":
            continue
        try:
            check_access(view.team, view.owner)
            if turn.get("options", {}).get("files"):
                raise ValidationError("Remove attachments before asking the PostHog authoring worker.")
            latest = view.state["revisions"][-1] if view.state["revisions"] else None
            prompt = (
                "Build a Meep native script view. Use this SDK guide and return the complete JavaScript in source, "
                "a short pane title in title, and a message for the person in reply. "
                "Use topics with tasks, threads or facts as the source when the request identifies a topic.\n\n"
                + _GUIDE.read_text()
                + "\n\nCurrent source:\n"
                + (latest["source"] if latest else "")
                + "\n\nPerson's request:\n"
                + turn["prompt"]
            )
            created = api.create_and_run_task(
                team=view.team,
                user_id=view.owner_id,
                profile=MEEP,
                create_pr=False,
                title=view.state["title"],
                description=prompt,
                sandbox_environment_id=str(environment(view.team_id)),
                options=TaskRunOptions(
                    output_schema=_OUTPUT,
                    model=turn.get("options", {}).get("model"),
                    reasoning_effort=turn.get("options", {}).get("effort"),
                ),
                extra_run_state={"meep_view_id": str(view.pk)},
            )
            if created.latest_run is None:
                raise RuntimeError("View authoring task was created without a run.")
            ViewJob.objects.create(
                view=view,
                turn_id=turn["id"],
                session=turn["session"],
                generation=latest["number"] if latest else 0,
                task_id=created.task_id,
                run_id=created.latest_run.id,
            )
            turn["stage"] = {"Working": "Starting"}
        except ValidationError as error:
            turn["stage"] = {"Finished": str(error.detail)}
            continue
        break
    view.save(update_fields=["state"])


@transaction.atomic
def finish_view(run_id: UUID, team_id: int) -> None:
    job = ViewJob.objects.select_related("view").filter(run_id=run_id, view__team_id=team_id, finished=False).first()
    if not job:
        return
    run = api.get_task_run(run_id, team_id)
    if not run or not run.is_terminal or run.task_id != job.task_id:
        return
    User.objects.select_for_update().only("pk").get(pk=job.view.owner_id)
    if not ViewJob.objects.filter(pk=job.pk, finished=False).update(finished=True):
        return
    view = WorkspaceView.objects.for_team(team_id).select_for_update().get(pk=job.view_id)
    turn = next(t for t in view.state["turns"] if t["id"] == str(job.turn_id))
    output = run.output or {}
    message = run.error_message or f"Run {run.status}."
    if turn.get("stop") or view.state["deleted"]:
        message = "Stopped."
    elif run.status == "completed" and isinstance(output.get("source"), str):
        try:
            view.state = transition(
                "publish-view", view.state, {"source": output["source"], "expected": job.generation}
            )
            if isinstance(output.get("title"), str) and output["title"].strip():
                view.state["title"] = output["title"].strip()[:256]
            message = str(output.get("reply") or "View updated.")
        except ValidationError as error:
            message = f"View could not be published: {error.detail}"
    turn = next(t for t in view.state["turns"] if t["id"] == str(job.turn_id))
    turn["stage"] = {"Finished": message}
    view.save(update_fields=["state"])
    advance(view)
