from typing import Any

from django.db import migrations

import structlog

logger = structlog.get_logger(__name__)

BATCH_SIZE = 1_000
MAX_IDENTIFIER_LENGTH = 512


def backfill_canvas_search_documents(apps, schema_editor):
    Canvas = apps.get_model("canvas", "Canvas")
    SearchDocument = apps.get_model("tasks", "TaskSearchDocument")
    Team = apps.get_model("posthog", "Team")
    parent_team_ids = dict(Team.objects.exclude(parent_team_id=None).values_list("id", "parent_team_id"))
    documents: list[Any] = []
    documents_processed = 0

    logger.info("canvas_search_backfill_started", batch_size=BATCH_SIZE)

    def flush():
        nonlocal documents_processed
        if not documents:
            return
        batch_count = len(documents)
        SearchDocument.objects.bulk_create(documents, batch_size=BATCH_SIZE, ignore_conflicts=True)
        documents.clear()
        documents_processed += batch_count

    for canvas in (
        Canvas.objects.filter(deleted=False, source_policy="standard")
        .only("id", "team_id", "channel_id", "name", "kind", "template_id")
        .iterator(chunk_size=BATCH_SIZE)
    ):
        name = (canvas.name or "").strip().lower()[:MAX_IDENTIFIER_LENGTH]
        if not name:
            continue
        documents.append(
            SearchDocument(
                team_id=parent_team_ids.get(canvas.team_id) or canvas.team_id,
                kind="canvas",
                source_key=str(canvas.id),
                title=canvas.name[:512],
                subtitle="",
                search_text=name,
                exact_identifiers=[name],
                channel_id=canvas.channel_id,
                metadata={
                    "canvas_id": str(canvas.id),
                    "canvas_kind": canvas.kind,
                    "template_id": canvas.template_id,
                },
            )
        )
        if len(documents) >= BATCH_SIZE:
            flush()

    flush()
    logger.info("canvas_search_backfill_completed", documents_processed=documents_processed)


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("tasks", "0119_alter_tasksearchdocument_kind"),
        ("canvas", "0016_canvas_source_policy"),
    ]

    operations = [migrations.RunPython(backfill_canvas_search_documents, migrations.RunPython.noop, elidable=True)]
