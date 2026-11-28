import json
import hashlib
from collections import defaultdict
from typing import Any
from uuid import UUID, uuid4, uuid5

from django.conf import settings
from django.db import transaction
from django.shortcuts import get_object_or_404

from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.request import Request

from posthog.models import Team, User

from products.authorization.backend.facade import api as authorization
from products.authorization.backend.facade.contracts import Resource, Subject
from products.authorization.backend.facade.enums import Action, ResourceType
from products.meep.backend.models import CommandReceipt, Topic
from products.signals.backend.facade import api as signals
from products.signals.backend.facade.taxonomy import SignalSourceProduct
from products.tasks.backend.facade.api import task_control_runtime_and_origin

SOURCE = SignalSourceProduct.MEEP.value


def linked_scouts(topic: Topic) -> list[dict[str, Any]]:
    team_id = topic.team.parent_team_id or topic.team_id
    rows = signals.scouts_for_source(team_id, SOURCE, str(topic.pk))
    if not rows:
        return []
    reports: defaultdict[str, list[dict[str, str]]] = defaultdict(list)
    # Signals excludes deleted and suppressed reports, and only accepts runs that actually authored the report.
    for report in signals.scout_reports_for_source(team_id, SOURCE, str(topic.pk)):
        reports[report.skill_name].append(
            {
                "id": report.report_id,
                "title": report.title,
                "summary": report.summary,
                "filed_at": report.filed_at.isoformat(),
            }
        )
    return [
        {
            "id": row.config_id,
            "skill_name": row.skill_name,
            "name": row.display_name or row.skill_name,
            "enabled": row.enabled,
            "reports": reports[row.skill_name],
        }
        for row in rows
    ]


def _announce(topic: Topic, rows: list[dict[str, Any]]) -> None:
    digest = hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest() if rows else None
    if topic.scout_digest == digest:
        return
    topic.scout_digest = digest
    topic.revision += 1
    topic.save(update_fields=["scout_digest", "revision"])
    CommandReceipt.objects.create(topic=topic, revision=topic.revision, command_id=uuid4())


@transaction.atomic
def reconcile_scouts(team_id: int, owner_id: int) -> None:
    # Only topics that have created scouts need to inspect Signals. The caller already limits polling frequency.
    topics = Topic.objects.for_team(team_id).filter(
        owner_id=owner_id, archived=False, deleted=False, scout_digest__isnull=False
    )
    if not topics.exists():
        return
    # Every producer assigns receipts under the same owner lock. Otherwise a device can pass a still-uncommitted
    # receipt while consuming a newer one from another topic.
    User.objects.select_for_update().only("pk").get(pk=owner_id)
    for topic in topics.select_for_update(of=("self",)).select_related("team").order_by("pk"):
        rows = linked_scouts(topic)
        _announce(topic, rows)
        _open_reports(topic, rows)


def _open_reports(topic: Topic, rows: list[dict[str, Any]]) -> None:
    from products.meep.backend.replication import apply_command  # noqa: PLC0415

    for row in rows:
        for report in row["reports"]:
            # The same finding always gets the same command ID, so a repeat is a replay and opens nothing.
            apply_command(
                topic.team_id,
                topic.owner,
                uuid5(topic.pk, f"report-command:{report['id']}"),
                topic.pk,
                {
                    "kind": "ReceiveReport",
                    "thread": str(uuid5(topic.pk, f"report-thread:{report['id']}")),
                    "message": str(uuid5(topic.pk, f"report-message:{report['id']}")),
                    "report_id": str(report["id"]),
                    "title": report["title"],
                    "summary": report["summary"] or report["title"],
                    "url": f"{settings.SITE_URL}/project/{topic.team_id}/inbox/{report['id']}",
                    "at": report["filed_at"],
                },
            )


def pause_scouts(topic: Topic) -> None:
    if topic.scout_digest is None:
        return
    team_id = topic.team.parent_team_id or topic.team_id
    for row in signals.scouts_for_source(team_id, SOURCE, str(topic.pk)):
        if row.enabled:
            signals.update_scout_for_source(team_id, SOURCE, row.config_id, enabled=False)


def _bound_topic(team: Team, user: User, task_id: UUID, topic_id: UUID) -> Topic:
    if not authorization.check(
        resource=Resource(type=ResourceType.SIGNAL_SCOUT, project_id=team.parent_team_id or team.pk),
        action=Action.EDIT,
        subject=Subject(user_id=user.pk),
    ):
        raise PermissionDenied("Managing a topic scout requires scout editor access.")
    return bound_topic(team, user, task_id, topic_id)


def bound_topic(team: Team, user: User, task_id: UUID, topic_id: UUID) -> Topic:
    task = task_control_runtime_and_origin(task_id, team.pk, user.pk)
    if task is None or task.origin_product != "meep":
        raise PermissionDenied("A Meep task is required to change this topic.")
    User.objects.select_for_update().only("pk").get(pk=user.pk)
    topic = get_object_or_404(
        Topic.objects.for_team(team.pk).select_for_update(),
        owner_id=user.pk,
        pk=topic_id,
        archived=False,
        deleted=False,
    )
    if not (
        (topic.conversation_id == task_id and topic.turns.exists()) or topic.board_runs.filter(task_id=task_id).exists()
    ):
        raise PermissionDenied("This task cannot change this topic.")
    return topic


@transaction.atomic
def create_topic_scout(
    *,
    team: Team,
    user: User,
    task_id: UUID,
    topic_id: UUID,
    name: str,
    instructions: str,
    cron: str | None,
    request: Request,
) -> tuple[dict[str, str | bool], bool]:
    topic = _bound_topic(team, user, task_id, topic_id)
    canonical_team = team.parent_team or team
    if canonical_team.organization.is_ai_data_processing_approved is not True:
        raise PermissionDenied("Enable AI data processing for this project to run scouts.")
    # Tool retries (including a resumed turn) keep one scout, even if the user renamed or paused it in Signals.
    identity = uuid5(topic.pk, json.dumps([name, instructions, cron]))
    skill_name = f"meep-scout-{identity.hex}"
    existing = next(
        (
            row
            for row in signals.scouts_for_source(canonical_team.id, SOURCE, str(topic.pk))
            if row.skill_name == skill_name
        ),
        None,
    )
    if existing:
        return {
            "id": existing.config_id,
            "skill_name": existing.skill_name,
            "name": existing.display_name or name,
            "enabled": existing.enabled,
        }, False
    result = signals.create_scout_for_source(
        team=canonical_team,
        user=user,
        name=skill_name,
        display_name=name,
        description=name,
        body=(
            f"{instructions}\n\nWhen you find something material, file a native Scout report with evidence using "
            "the Scout report channel. Meep shows the report in the originating topic. Skip a report when there is no finding."
        ),
        files=[],
        config_options={"emit": True, **({"run_cron_schedule": cron} if cron else {})},
        request=request,
        serializer_context={"project_id": team.project_id, "team": canonical_team, "request": request},
        source_product=SOURCE,
        source_id=str(topic.pk),
    )
    rows = linked_scouts(topic)
    _announce(topic, rows)
    return {
        "id": str(result.config.id),
        "skill_name": result.config.skill_name,
        "name": result.config.display_name,
        "enabled": result.config.enabled,
    }, result.created


@transaction.atomic
def set_topic_scout_enabled(
    *,
    team: Team,
    user: User,
    task_id: UUID,
    topic_id: UUID,
    scout_id: UUID,
    enabled: bool,
    request: Request,
) -> dict[str, str | bool]:
    topic = _bound_topic(team, user, task_id, topic_id)
    canonical_team = team.parent_team or team
    if enabled and canonical_team.organization.is_ai_data_processing_approved is not True:
        raise PermissionDenied("Enable AI data processing for this project to run scouts.")
    scout = signals.set_source_scout_enabled(
        team=canonical_team,
        user=user,
        source_product=SOURCE,
        source_id=str(topic.pk),
        config_id=scout_id,
        enabled=enabled,
        request=request,
    )
    if scout is None:
        raise NotFound("Scout not found in this topic.")
    _announce(topic, linked_scouts(topic))
    return {
        "id": scout.config_id,
        "skill_name": scout.skill_name,
        "name": scout.display_name or scout.skill_name,
        "enabled": scout.enabled,
    }
