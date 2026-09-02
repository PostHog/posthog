from django.db import migrations


def backfill_paused_by_user(apps, schema_editor):
    # Rows disabled before `status` existed can only have been switched off by a human:
    # nothing system-driven ever wrote `enabled` until this field shipped. One UPDATE over a
    # small table (scout configs, not events); kept separate from 0077's AddFields so the
    # data write never shares a transaction with schema locks.
    SignalScoutConfig = apps.get_model("signals", "SignalScoutConfig")
    # `_default_manager`, not `objects`: the model's Meta routes the default manager to the
    # unscoped `all_teams`, so the historical model carries no `objects` attribute.
    SignalScoutConfig._default_manager.filter(enabled=False).update(status="paused_by_user")


class Migration(migrations.Migration):
    dependencies = [
        ("signals", "0077_signalscoutconfig_status"),
    ]

    operations = [
        migrations.RunPython(backfill_paused_by_user, reverse_code=migrations.RunPython.noop),
    ]
