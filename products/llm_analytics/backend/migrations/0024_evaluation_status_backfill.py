from django.db import migrations


def backfill_status(apps, schema_editor):
    """Map the existing boolean to the new lifecycle enum. We can't retroactively tell which
    `enabled=False` rows were system-disabled vs user-paused, so everything inactive stays
    `paused` (the default from 0023). Only the enabled rows need explicit promotion to `active`.
    Future system transitions will set `error` going forward."""
    Evaluation = apps.get_model("llm_analytics", "Evaluation")
    Evaluation.objects.filter(enabled=True).update(status="active")


def reverse_noop(apps, schema_editor):
    # Rolling back the backfill is a no-op — the schema rollback in 0023 drops the column anyway.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("llm_analytics", "0023_evaluation_status"),
    ]

    operations = [
        migrations.RunPython(backfill_status, reverse_noop),
    ]
