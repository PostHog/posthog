from typing import Any
from uuid import UUID, uuid4

from django.db import transaction
from django.utils import timezone

from rest_framework.exceptions import ValidationError

from posthog.models import Team, User

from products.meep.backend.models import ChatTurn, CommandReceipt, Topic
from products.meep.backend.task_profiles import MEEP, MEEP_MCP_SCOPES
from products.tasks.backend.facade import access, api, usage
from products.tasks.backend.facade.profiles import TaskRunOptions


def check_access(team: Team, owner: User) -> None:
    if not team.organization.is_ai_data_processing_approved:
        raise ValidationError("Enable AI data processing to use topic chat.")
    if not access.get_desktop_access_decision(owner, team.organization).allowed:
        raise ValidationError("PostHog Code access is required for topic chat.")
    if usage.task_run_usage_limited(owner, team.pk):
        raise ValidationError("The project has reached its PostHog Code usage limit.")


def environment(team_id: int) -> UUID:
    return api.upsert_internal_sandbox_env(
        team_id,
        "MEEP",
        api.SandboxNetworkAccessLevel(MEEP.network.levels[0]),
        allowed_domains=list(MEEP.network.allowed_domains),
        include_default_domains=MEEP.network.include_default_domains,
    )


def start_turn(topic: Topic, owner: User, message_id: UUID, text: str) -> bool:
    check_access(topic.team, owner)
    previous = topic.turns.last()
    if previous and not previous.finished_at:
        return False
    if topic.conversation_id is None:
        created = api.create_and_run_task(
            team=topic.team,
            user_id=owner.pk,
            profile=MEEP,
            title=topic.title,
            create_pr=False,
            sandbox_environment_id=str(environment(topic.team_id)),
            description=(
                f"Use the working-with-meep skill. Your private topic in project {topic.team_id} is {topic.pk}. "
                "Use PostHog MCP to read the topic and research its mission. Return the answer in the reply field.\n\n"
                f"Mission: {topic.mission}\n\n{text}"
            ),
            options=TaskRunOptions(
                model=topic.chat_model or None,
                mcp_scopes=MEEP_MCP_SCOPES,
                output_schema={
                    "type": "object",
                    "properties": {"reply": {"type": "string"}},
                    "required": ["reply"],
                    "additionalProperties": False,
                },
            ),
            extra_run_state={"meep_topic_id": str(topic.pk)},
        )
        if created.latest_run is None:
            raise ValidationError("PostHog Tasks did not create a run.")
        topic.conversation_id = created.task_id
        topic.save(update_fields=["conversation_id"])
        run_id = created.latest_run.id
    else:
        if previous:
            resume_id = previous.run_id
        else:
            linked = api.get_task_detail(topic.conversation_id, topic.team_id, owner.pk)
            if linked is None or linked.latest_run is None:
                raise ValidationError("The linked conversation has no run to resume.")
            resume_id = linked.latest_run.id
        result = api.run_task(
            topic.conversation_id,
            topic.team_id,
            owner.pk,
            validated_data={
                **({"model": topic.chat_model} if topic.chat_model else {}),
                "resume_from_run_id": str(resume_id),
                "pending_user_message": text,
                "mode": "background",
            },
        )
        if result is None or result.run_id is None:
            raise ValidationError("PostHog Tasks could not resume the conversation.")
        run_id = result.run_id
    ChatTurn.objects.create(topic=topic, message_id=message_id, text=text, run_id=run_id)
    return True


def finish_turn(run_id: UUID, team_id: int) -> None:
    turn = (
        ChatTurn.objects.select_related("topic").filter(run_id=run_id, topic__team_id=team_id, finished_at=None).first()
    )
    if turn is None:
        return
    run = api.get_task_run(run_id, team_id)
    if run is None or not run.is_terminal or run.task_id != turn.topic.conversation_id:
        return
    output = run.output if isinstance(run.output, dict) else {}
    reply = output.get("reply") or run.error_message or f"Run {run.status} without a reply."
    with transaction.atomic():
        User.objects.select_for_update().only("pk").get(pk=turn.topic.owner_id)
        if ChatTurn.objects.filter(pk=turn.pk, finished_at=None).update(reply=str(reply), finished_at=timezone.now()):
            topic = Topic.objects.for_team(team_id).select_for_update().get(pk=turn.topic_id)
            topic.revision += 1
            for thread in topic.state.get("threads", []):
                if thread["id"] == str(turn.message_id):
                    thread["state"] = "Handled"
                    thread.setdefault("outcomes", []).append({"Reply": {"to": "User", "text": str(reply)}})
                    break
            topic.save(update_fields=["revision", "state"])
            CommandReceipt.objects.create(command_id=uuid4(), topic=topic, revision=topic.revision)


def run_saved(sender: Any, instance: Any, created: bool, **kwargs: Any) -> None:
    if created or not instance.is_terminal:
        return
    if isinstance(instance.state, dict) and instance.state.get("meep_view_id"):
        from products.meep.backend.authoring import finish_view  # noqa: PLC0415

        transaction.on_commit(lambda: finish_view(instance.id, instance.team_id), robust=True)
        return
    # Check the durable run binding in finish_turn. The sandbox can edit run state.
    if isinstance(instance.state, dict) and (
        instance.state.get("meep_topic_id") or instance.state.get("resume_from_run_id")
    ):
        transaction.on_commit(lambda: finish_turn(instance.id, instance.team_id), robust=True)
