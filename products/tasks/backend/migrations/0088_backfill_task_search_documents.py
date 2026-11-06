import re
import hashlib
from typing import Any

from django.db import migrations

import structlog

logger = structlog.get_logger(__name__)

PR_URL_RE = re.compile(r"^https?://github\.com/(?P<repo>[^/]+/[^/]+)/pull/(?P<number>\d+)(?:/.*)?$", re.IGNORECASE)
MAX_INDEXED_PR_URLS = 50
MAX_INDEXED_ARTIFACTS = 100
MAX_IDENTIFIER_LENGTH = 512
BATCH_SIZE = 1_000
LOG_EVERY_BATCHES = 25


def _normalized(values):
    return list(
        dict.fromkeys(value.strip().lower()[:MAX_IDENTIFIER_LENGTH] for value in values if value and value.strip())
    )


def _source_key(value):
    if len(value) <= MAX_IDENTIFIER_LENGTH:
        return value
    digest = hashlib.sha256(value.encode()).hexdigest()
    return f"{value[: MAX_IDENTIFIER_LENGTH - len(digest) - 1]}:{digest}"


def _task_slug(task):
    if task.task_number is None:
        return ""
    clean_name = "".join(character for character in task.team.name if character.isalnum())
    uppercase_letters = [character for character in clean_name if character.isupper()]
    prefix = "".join(uppercase_letters[:3]) if len(uppercase_letters) >= 3 else clean_name[:3].upper() or "TSK"
    return f"{prefix}-{task.task_number}"


def _document(SearchDocument, *, team_id, kind, source_key, title, subtitle="", identifiers=(), **relations):
    exact_identifiers = _normalized(identifiers)
    return SearchDocument(
        team_id=team_id,
        kind=kind,
        source_key=_source_key(source_key),
        title=title[:512],
        subtitle=subtitle[:512],
        search_text=" ".join(_normalized([title, subtitle, *exact_identifiers])),
        exact_identifiers=exact_identifiers,
        metadata=relations.pop("metadata", {}),
        **relations,
    )


def backfill_task_search_documents(apps, schema_editor):
    Channel = apps.get_model("tasks", "Channel")
    Task = apps.get_model("tasks", "Task")
    TaskArtifact = apps.get_model("tasks", "TaskArtifact")
    TaskRun = apps.get_model("tasks", "TaskRun")
    SearchDocument = apps.get_model("tasks", "TaskSearchDocument")
    Team = apps.get_model("posthog", "Team")
    parent_team_ids = dict(Team.objects.exclude(parent_team_id=None).values_list("id", "parent_team_id"))
    documents: list[Any] = []
    documents_processed = 0
    batches_committed = 0

    logger.info("task_search_backfill_started", batch_size=BATCH_SIZE)

    def canonical_team_id(team_id):
        return parent_team_ids.get(team_id) or team_id

    def flush():
        nonlocal documents_processed, batches_committed
        if not documents:
            return
        batch_count = len(documents)
        SearchDocument.objects.bulk_create(documents, batch_size=BATCH_SIZE, ignore_conflicts=True)
        documents.clear()
        documents_processed += batch_count
        batches_committed += 1
        if batches_committed % LOG_EVERY_BATCHES == 0:
            logger.info(
                "task_search_backfill_progress",
                batches_committed=batches_committed,
                documents_processed=documents_processed,
            )

    def add(document):
        documents.append(document)
        if len(documents) >= BATCH_SIZE:
            flush()

    for channel in (
        Channel.objects.filter(deleted=False).only("id", "team_id", "name", "channel_type").iterator(chunk_size=1_000)
    ):
        add(
            _document(
                SearchDocument,
                team_id=canonical_team_id(channel.team_id),
                kind="channel",
                source_key=str(channel.id),
                title=channel.name,
                identifiers=[channel.name],
                channel_id=channel.id,
                metadata={"channel_type": channel.channel_type},
            )
        )

    for task in (
        Task.objects.filter(deleted=False)
        .select_related("team")
        .only(
            "id",
            "team_id",
            "team__name",
            "task_number",
            "title",
            "repository",
            "channel_id",
            "archived",
        )
        .iterator(chunk_size=1_000)
    ):
        identifiers = [str(task.task_number)] if task.task_number is not None else []
        slug = _task_slug(task)
        if slug:
            identifiers.append(slug)
        add(
            _document(
                SearchDocument,
                team_id=canonical_team_id(task.team_id),
                kind="task",
                source_key=str(task.id),
                title=task.title,
                subtitle=task.repository or "",
                identifiers=identifiers,
                task_id=task.id,
                channel_id=task.channel_id,
                metadata={"archived": task.archived},
            )
        )

    for run in (
        TaskRun.objects.filter(task__deleted=False)
        .select_related("task")
        .only("id", "team_id", "task_id", "output", "artifacts", "task__title", "task__channel_id")
        .iterator(chunk_size=1_000)
    ):
        output = run.output or {}
        listed = output.get("pr_urls")
        urls = [value for value in listed if isinstance(value, str)] if isinstance(listed, list) else []
        if isinstance(output.get("pr_url"), str):
            urls.append(output["pr_url"])
        for url in list(dict.fromkeys(url for url in urls if url.strip()))[:MAX_INDEXED_PR_URLS]:
            match = PR_URL_RE.match(url.strip())
            if not match:
                continue
            repo, number = match.group("repo", "number")
            add(
                _document(
                    SearchDocument,
                    team_id=canonical_team_id(run.team_id),
                    kind="pull_request",
                    source_key=f"run:{run.id}:{url.lower()}",
                    title=f"PR #{number}",
                    subtitle=repo,
                    identifiers=[url, f"#{number}", number, f"{repo}#{number}"],
                    task_id=run.task_id,
                    task_run_id=run.id,
                    channel_id=run.task.channel_id,
                    metadata={"url": url, "number": int(number), "repository": repo},
                )
            )
        for position, artifact in enumerate((run.artifacts or [])[:MAX_INDEXED_ARTIFACTS]):
            if not isinstance(artifact, dict) or artifact.get("dismissed_at"):
                continue
            name = artifact.get("name")
            if not isinstance(name, str) or not name.strip():
                continue
            source_id = artifact.get("id") or artifact.get("storage_path") or f"{position}:{name}"
            add(
                _document(
                    SearchDocument,
                    team_id=canonical_team_id(run.team_id),
                    kind="artifact",
                    source_key=f"run:{run.id}:{source_id}",
                    title=name,
                    subtitle=run.task.title,
                    identifiers=[name],
                    task_id=run.task_id,
                    task_run_id=run.id,
                    channel_id=run.task.channel_id,
                    metadata={"artifact_id": artifact.get("id"), "artifact_type": artifact.get("type")},
                )
            )

    for artifact in (
        TaskArtifact.objects.filter(status="active", task__deleted=False)
        .select_related("task")
        .only(
            "id",
            "team_id",
            "task_id",
            "task_run_id",
            "name",
            "artifact_type",
            "task__title",
            "task__channel_id",
        )
        .iterator(chunk_size=1_000)
    ):
        add(
            _document(
                SearchDocument,
                team_id=canonical_team_id(artifact.team_id),
                kind="artifact",
                source_key=f"living:{artifact.id}",
                title=artifact.name,
                subtitle=artifact.task.title,
                identifiers=[artifact.name],
                task_id=artifact.task_id,
                task_run_id=artifact.task_run_id,
                channel_id=artifact.task.channel_id,
                metadata={"artifact_id": str(artifact.id), "artifact_type": artifact.artifact_type, "living": True},
            )
        )

    flush()
    logger.info(
        "task_search_backfill_completed",
        batches_committed=batches_committed,
        documents_processed=documents_processed,
    )


class Migration(migrations.Migration):
    # Each 1,000-document bulk insert commits independently. Avoid wrapping the
    # complete historical scan in a deployment-long transaction.
    atomic = False

    dependencies = [("tasks", "0087_tasksearchdocument")]

    operations = [migrations.RunPython(backfill_task_search_documents, migrations.RunPython.noop, elidable=True)]
