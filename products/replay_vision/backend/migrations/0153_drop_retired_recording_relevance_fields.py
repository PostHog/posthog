from django.db import migrations, transaction
from django.db.models import Q


def _without_retired_fields(query: dict) -> dict:
    cleaned = {key: value for key, value in query.items() if key != "recommended_only"}
    if cleaned.get("order") == "surfacing_score":
        cleaned.pop("order")
    return cleaned


def _clean_rows(manager, alias: str, field: str, retired: Q, query_of) -> None:
    for row_id in list(manager.filter(retired).values_list("id", flat=True)):
        # Each row is re-read and saved in its own short transaction, so a concurrent edit is kept and no lock outlives
        # its row. Re-running skips rows already cleaned, so a retry after a partial run is safe.
        with transaction.atomic(using=alias):
            row = manager.select_for_update().filter(retired, id=row_id).first()
            query = query_of(row) if row is not None else None
            # Stored queries are free-form JSON, so a non-object value is left alone rather than failing the deploy.
            if not isinstance(query, dict):
                continue
            setattr(
                row,
                field,
                _without_retired_fields(query)
                if field == "query"
                else {**row.scanner_snapshot, "query": _without_retired_fields(query)},
            )
            row.save(update_fields=[field])


# Stored scanner queries are validated against the recordings query schema, which no longer has the relevance sort or
# filter, so a leftover key would fail every read of the scanner.
def drop_retired_relevance_fields(apps, schema_editor):
    alias = schema_editor.connection.alias
    _clean_rows(
        apps.get_model("replay_vision", "ReplayScanner")._base_manager.using(alias),
        alias,
        "query",
        Q(query__order="surfacing_score") | Q(query__has_key="recommended_only"),
        lambda scanner: scanner.query,
    )
    _clean_rows(
        apps.get_model("replay_vision", "ReplayScannerBackfill")._base_manager.using(alias),
        alias,
        "scanner_snapshot",
        Q(scanner_snapshot__query__order="surfacing_score") | Q(scanner_snapshot__query__has_key="recommended_only"),
        lambda backfill: (
            backfill.scanner_snapshot.get("query") if isinstance(backfill.scanner_snapshot, dict) else None
        ),
    )


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("replay_vision", "0152_replayscanner_sampling_mode_db_default"),
    ]

    operations = [
        migrations.RunPython(drop_retired_relevance_fields, migrations.RunPython.noop, elidable=True),
    ]
