from django.db import migrations


def backfill_monitor_verdict(apps, schema_editor):
    # Idempotent — only rows whose `verdict` is still boolean are touched.
    ReplayObservation = apps.get_model("replay_vision", "ReplayObservation")
    qs = ReplayObservation.objects.filter(
        scanner_snapshot__scanner_type="monitor",
        scanner_result__isnull=False,
    ).iterator(chunk_size=500)
    for obs in qs:
        model_output = obs.scanner_result.get("model_output") if obs.scanner_result else None
        if not isinstance(model_output, dict):
            continue
        verdict = model_output.get("verdict")
        if not isinstance(verdict, bool):
            continue
        model_output["verdict"] = "yes" if verdict else "no"
        obs.scanner_result["model_output"] = model_output
        obs.save(update_fields=["scanner_result"])


class Migration(migrations.Migration):
    dependencies = [
        ("replay_vision", "0010_replayscanner_last_seen_session_id"),
    ]

    operations = [
        migrations.RunPython(backfill_monitor_verdict, reverse_code=migrations.RunPython.noop),
    ]
