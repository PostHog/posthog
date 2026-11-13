from django.db import migrations
from django.db.models import Q


def _without_retired_fields(query: dict) -> dict:
    cleaned = {key: value for key, value in query.items() if key != "recommended_only"}
    if cleaned.get("order") == "surfacing_score":
        cleaned.pop("order")
    return cleaned


# Stored scanner queries are validated against the recordings query schema, which no longer has the
# relevance sort or filter, so a leftover key would fail every read of the scanner.
def drop_retired_relevance_fields(apps, schema_editor):
    ReplayScanner = apps.get_model("replay_vision", "ReplayScanner")
    scanners = ReplayScanner._base_manager.filter(
        Q(query__order="surfacing_score") | Q(query__has_key="recommended_only")
    )
    for scanner in scanners.only("id", "query").iterator(chunk_size=500):
        scanner.query = _without_retired_fields(scanner.query)
        scanner.save(update_fields=["query"])

    ReplayScannerBackfill = apps.get_model("replay_vision", "ReplayScannerBackfill")
    backfills = ReplayScannerBackfill._base_manager.filter(
        Q(scanner_snapshot__query__order="surfacing_score") | Q(scanner_snapshot__query__has_key="recommended_only")
    )
    for backfill in backfills.only("id", "scanner_snapshot").iterator(chunk_size=500):
        backfill.scanner_snapshot = {
            **backfill.scanner_snapshot,
            "query": _without_retired_fields(backfill.scanner_snapshot["query"]),
        }
        backfill.save(update_fields=["scanner_snapshot"])


class Migration(migrations.Migration):
    dependencies = [
        ("replay_vision", "0152_replayscanner_sampling_mode_db_default"),
    ]

    operations = [
        migrations.RunPython(drop_retired_relevance_fields, migrations.RunPython.noop, elidable=True),
    ]
