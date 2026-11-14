from django.db import migrations, transaction
from django.db.models import Q


def _without_retired_fields(query: dict) -> dict:
    cleaned = {key: value for key, value in query.items() if key != "recommended_only"}
    if cleaned.get("order") == "surfacing_score":
        cleaned.pop("order")
    return cleaned


def _clean_rows(model, field: str, retired: Q, query_of) -> None:
    ids = list(model._base_manager.filter(retired).values_list("id", flat=True))
    for row_id in ids:
        # Each row is re-read under its own row lock, so an edit made while this runs is kept.
        with transaction.atomic():
            row = model._base_manager.select_for_update().filter(retired, id=row_id).first()
            if row is None:
                continue
            setattr(row, field, query_of(row))
            row.save(update_fields=[field])


# Stored scanner queries are validated against the recordings query schema, which no longer has the relevance sort or
# filter, so a leftover key would fail every read of the scanner.
def drop_retired_relevance_fields(apps, schema_editor):
    _clean_rows(
        apps.get_model("replay_vision", "ReplayScanner"),
        "query",
        Q(query__order="surfacing_score") | Q(query__has_key="recommended_only"),
        lambda scanner: _without_retired_fields(scanner.query),
    )
    _clean_rows(
        apps.get_model("replay_vision", "ReplayScannerBackfill"),
        "scanner_snapshot",
        Q(scanner_snapshot__query__order="surfacing_score") | Q(scanner_snapshot__query__has_key="recommended_only"),
        lambda backfill: {
            **backfill.scanner_snapshot,
            "query": _without_retired_fields(backfill.scanner_snapshot["query"]),
        },
    )


class Migration(migrations.Migration):
    dependencies = [
        ("replay_vision", "0152_replayscanner_sampling_mode_db_default"),
    ]

    operations = [
        migrations.RunPython(drop_retired_relevance_fields, migrations.RunPython.noop, elidable=True),
    ]
