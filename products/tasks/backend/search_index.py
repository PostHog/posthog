import re
import hashlib
import logging
from collections.abc import Iterable
from typing import Any

from django.db import transaction
from django.db.models import Q, Value
from django.db.models.functions import Concat, Lower, Trim
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from posthog.models.scoping.manager import resolve_effective_team_id
from posthog.models.team import Team

from products.tasks.backend.models import Channel, Task, TaskArtifact, TaskRun, TaskSearchDocument

logger = logging.getLogger(__name__)

_PR_URL_RE = re.compile(r"^https?://github\.com/(?P<repo>[^/]+/[^/]+)/pull/(?P<number>\d+)(?:/.*)?$", re.IGNORECASE)
MAX_INDEXED_PR_URLS = 50
MAX_INDEXED_ARTIFACTS = 100
MAX_IDENTIFIER_LENGTH = 512


def _normalized(values: Iterable[str]) -> list[str]:
    return list(
        dict.fromkeys(value.strip().lower()[:MAX_IDENTIFIER_LENGTH] for value in values if value and value.strip())
    )


def _source_key(value: str) -> str:
    if len(value) <= MAX_IDENTIFIER_LENGTH:
        return value
    digest = hashlib.sha256(value.encode()).hexdigest()
    return f"{value[: MAX_IDENTIFIER_LENGTH - len(digest) - 1]}:{digest}"


def _upsert(
    *,
    team_id: int,
    kind: str,
    source_key: str,
    title: str,
    subtitle: str = "",
    identifiers: Iterable[str] = (),
    task_id: Any = None,
    task_run_id: Any = None,
    channel_id: Any = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    exact_identifiers = _normalized(identifiers)
    TaskSearchDocument.objects.for_team(team_id, canonical=True).update_or_create(
        team_id=team_id,
        kind=kind,
        source_key=_source_key(source_key),
        defaults={
            "task_id": task_id,
            "task_run_id": task_run_id,
            "channel_id": channel_id,
            "title": title[:512],
            "subtitle": subtitle[:512],
            "search_text": " ".join(_normalized([title, subtitle, *exact_identifiers])),
            "exact_identifiers": exact_identifiers,
            "metadata": metadata or {},
        },
    )


def index_task(task_id: Any, *, include_related: bool = True, canonical_team_id: int | None = None) -> None:
    task = Task.objects.filter(id=task_id).first()
    if task is None or task.deleted:
        TaskSearchDocument.objects.unscoped().filter(task_id=task_id).delete()
        return
    identifiers = [str(task.task_number)] if task.task_number is not None else []
    if task.slug:
        identifiers.append(task.slug)
    canonical_team_id = canonical_team_id or resolve_effective_team_id(task.team_id)
    _upsert(
        team_id=canonical_team_id,
        kind=TaskSearchDocument.Kind.TASK,
        source_key=str(task.id),
        title=task.title,
        subtitle=task.repository or "",
        identifiers=identifiers,
        task_id=task.id,
        channel_id=task.channel_id,
        metadata={"archived": task.archived},
    )
    if not include_related:
        return
    # Task title/channel changes affect descendant navigation context, but
    # rereading every historical run manifest would make a task save unbounded.
    # Update the projected fields in a fixed number of queries instead.
    descendants = TaskSearchDocument.objects.for_team(canonical_team_id, canonical=True).filter(task_id=task.id)
    descendants.update(channel_id=task.channel_id)
    descendants.filter(kind=TaskSearchDocument.Kind.ARTIFACT).update(
        subtitle=task.title[:MAX_IDENTIFIER_LENGTH],
        search_text=Trim(
            Concat(
                Lower("title"),
                Value(" "),
                Lower(Value(task.title[:MAX_IDENTIFIER_LENGTH])),
            )
        ),
    )


def _pr_urls(output: dict[str, Any] | None) -> list[str]:
    if not output:
        return []
    listed = output.get("pr_urls")
    values = [value for value in listed if isinstance(value, str)] if isinstance(listed, list) else []
    single = output.get("pr_url")
    if isinstance(single, str):
        values.append(single)
    return list(dict.fromkeys(value for value in values if value.strip()))[:MAX_INDEXED_PR_URLS]


@transaction.atomic
def index_task_run(run_id: Any, *, canonical_team_id: int | None = None) -> None:
    run = TaskRun.objects.select_related("task").filter(id=run_id).first()
    if run is None or run.task.deleted:
        TaskSearchDocument.objects.unscoped().filter(task_run_id=run_id).delete()
        return
    canonical_team_id = canonical_team_id or resolve_effective_team_id(run.team_id)
    TaskSearchDocument.objects.for_team(canonical_team_id, canonical=True).filter(
        source_key__startswith=f"run:{run.id}:"
    ).delete()
    for url in _pr_urls(run.output):
        match = _PR_URL_RE.match(url.strip())
        if not match:
            continue
        repo, number = match.group("repo", "number")
        _upsert(
            team_id=canonical_team_id,
            kind=TaskSearchDocument.Kind.PULL_REQUEST,
            source_key=f"run:{run.id}:{url.lower()}",
            title=f"PR #{number}",
            subtitle=repo,
            identifiers=[url, f"#{number}", number, f"{repo}#{number}"],
            task_id=run.task_id,
            task_run_id=run.id,
            channel_id=run.task.channel_id,
            metadata={"url": url, "number": int(number), "repository": repo},
        )
    for position, artifact in enumerate((run.artifacts or [])[:MAX_INDEXED_ARTIFACTS]):
        if not isinstance(artifact, dict) or artifact.get("dismissed_at"):
            continue
        name = artifact.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        source_id = artifact.get("id") or artifact.get("storage_path") or f"{position}:{name}"
        _upsert(
            team_id=canonical_team_id,
            kind=TaskSearchDocument.Kind.ARTIFACT,
            source_key=f"run:{run.id}:{source_id}",
            title=name,
            subtitle=run.task.title,
            identifiers=[name],
            task_id=run.task_id,
            task_run_id=run.id,
            channel_id=run.task.channel_id,
            metadata={"artifact_id": artifact.get("id"), "artifact_type": artifact.get("type")},
        )


def index_task_artifact(artifact_id: Any, *, canonical_team_id: int | None = None) -> None:
    artifact = TaskArtifact.objects.unscoped().select_related("task").filter(id=artifact_id).first()
    source_key = f"living:{artifact_id}"
    if artifact is None or artifact.status != TaskArtifact.Status.ACTIVE or artifact.task.deleted:
        TaskSearchDocument.objects.unscoped().filter(
            kind=TaskSearchDocument.Kind.ARTIFACT, source_key=source_key
        ).delete()
        return
    canonical_team_id = canonical_team_id or resolve_effective_team_id(artifact.team_id)
    _upsert(
        team_id=canonical_team_id,
        kind=TaskSearchDocument.Kind.ARTIFACT,
        source_key=source_key,
        title=artifact.name,
        subtitle=artifact.task.title,
        identifiers=[artifact.name],
        task_id=artifact.task_id,
        task_run_id=artifact.task_run_id,
        channel_id=artifact.task.channel_id,
        metadata={"artifact_id": str(artifact.id), "artifact_type": artifact.artifact_type, "living": True},
    )


def index_channel(channel_id: Any, *, canonical_team_id: int | None = None) -> None:
    channel = Channel.objects.unscoped().filter(id=channel_id).first()
    if channel is None or channel.deleted:
        TaskSearchDocument.objects.unscoped().filter(
            kind=TaskSearchDocument.Kind.CHANNEL, source_key=str(channel_id)
        ).delete()
        return
    canonical_team_id = canonical_team_id or resolve_effective_team_id(channel.team_id)
    _upsert(
        team_id=canonical_team_id,
        kind=TaskSearchDocument.Kind.CHANNEL,
        source_key=str(channel.id),
        title=channel.name,
        identifiers=[channel.name],
        channel_id=channel.id,
        metadata={"channel_type": channel.channel_type},
    )


def rebuild_team_search_index(team_id: int) -> None:
    canonical_team_id = resolve_effective_team_id(team_id)
    environment_ids = Team.objects.filter(Q(id=canonical_team_id) | Q(parent_team_id=canonical_team_id)).values_list(
        "id", flat=True
    )
    TaskSearchDocument.objects.for_team(canonical_team_id, canonical=True).delete()
    for task_id in Task.objects.filter(team_id__in=environment_ids).values_list("id", flat=True).iterator():
        index_task(task_id, include_related=False, canonical_team_id=canonical_team_id)
    for run_id in TaskRun.objects.filter(team_id__in=environment_ids).values_list("id", flat=True).iterator():
        index_task_run(run_id, canonical_team_id=canonical_team_id)
    for artifact_id in (
        TaskArtifact.objects.for_team(canonical_team_id, canonical=True).values_list("id", flat=True).iterator()
    ):
        index_task_artifact(artifact_id, canonical_team_id=canonical_team_id)
    for channel_id in (
        Channel.objects.for_team(canonical_team_id, canonical=True).values_list("id", flat=True).iterator()
    ):
        index_channel(channel_id, canonical_team_id=canonical_team_id)


def _after_commit(callback) -> None:
    def safely_index() -> None:
        try:
            callback()
        except Exception:
            # This projection is rebuildable and must never turn a successful
            # task/run write into an apparent request failure.
            logger.exception("task_search_index_update_failed")

    transaction.on_commit(safely_index)


@receiver(post_save, sender=Task)
def task_saved(sender, instance: Task, update_fields=None, **kwargs) -> None:
    if update_fields is not None and not set(update_fields) & {
        "title",
        "task_number",
        "slug",
        "repository",
        "channel",
        "archived",
        "deleted",
    }:
        return
    include_related = update_fields is None or bool(set(update_fields) & {"title", "channel"})
    _after_commit(lambda: index_task(instance.id, include_related=include_related))


@receiver(post_save, sender=TaskRun)
def task_run_saved(sender, instance: TaskRun, update_fields=None, **kwargs) -> None:
    if update_fields is not None and not set(update_fields) & {"output", "artifacts"}:
        return
    _after_commit(lambda: index_task_run(instance.id))


@receiver(post_save, sender=TaskArtifact)
def task_artifact_saved(sender, instance: TaskArtifact, update_fields=None, **kwargs) -> None:
    if update_fields is not None and not set(update_fields) & {"name", "status", "task", "task_run", "artifact_type"}:
        return
    _after_commit(lambda: index_task_artifact(instance.id))


@receiver(post_save, sender=Channel)
def channel_saved(sender, instance: Channel, update_fields=None, **kwargs) -> None:
    if update_fields is not None and not set(update_fields) & {"name", "deleted", "channel_type", "created_by"}:
        return
    _after_commit(lambda: index_channel(instance.id))


@receiver(post_delete, sender=Channel)
def channel_deleted(sender, instance: Channel, **kwargs) -> None:
    _after_commit(
        lambda: (
            TaskSearchDocument.objects.unscoped()
            .filter(kind=TaskSearchDocument.Kind.CHANNEL, source_key=str(instance.id))
            .delete()
        )
    )
