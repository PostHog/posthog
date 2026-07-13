from django.db import migrations

from posthog.migration_helpers import chunked_queryset_iterator


def strip_emits_embeddings(apps, schema_editor):
    # `emits_embeddings` was removed from the summarizer config when embeddings became always-on (#61284).
    # Old rows still carry the dead key, which now fails save-time config validation. Idempotent — only rows
    # that still have the key are loaded and rewritten.
    ReplayScanner = apps.get_model("replay_vision", "ReplayScanner")
    qs = chunked_queryset_iterator(
        ReplayScanner.objects.filter(
            scanner_type="summarizer",
            scanner_config__has_key="emits_embeddings",
        ),
        chunk_size=500,
    )
    for scanner in qs:
        scanner.scanner_config.pop("emits_embeddings", None)
        scanner.save(update_fields=["scanner_config"])


class Migration(migrations.Migration):
    dependencies = [
        ("replay_vision", "0040_replayobservation_rlo_team_in_flight_idx"),
    ]

    operations = [
        migrations.RunPython(strip_emits_embeddings, reverse_code=migrations.RunPython.noop),
    ]
