import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def backfill_paused_by_user(apps, schema_editor):
    # Rows disabled before `status` existed can only have been switched off by a human:
    # nothing system-driven ever wrote `enabled` until this field shipped.
    SignalScoutConfig = apps.get_model("signals", "SignalScoutConfig")
    # `_default_manager`, not `objects`: the model's Meta routes the default manager to the
    # unscoped `all_teams`, so the historical model carries no `objects` attribute.
    SignalScoutConfig._default_manager.filter(enabled=False).update(status="paused_by_user")


class Migration(migrations.Migration):
    dependencies = [
        ("signals", "0074_signalreport_charts"),
    ]

    operations = [
        migrations.AddField(
            model_name="signalscoutconfig",
            name="status",
            field=models.CharField(
                choices=[
                    ("active", "Active"),
                    ("pending_pause", "Pending pause"),
                    ("paused_by_system", "Paused by system"),
                    ("paused_by_user", "Paused by user"),
                ],
                db_default="active",
                default="active",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="signalscoutconfig",
            name="pause_reason",
            field=models.CharField(
                blank=True,
                choices=[
                    ("no_output", "No output"),
                    ("ignored", "Ignored"),
                    ("repeated_failures", "Repeated failures"),
                ],
                max_length=20,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="signalscoutconfig",
            name="status_changed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="signalscoutconfig",
            name="status_changed_by",
            field=models.ForeignKey(
                blank=True,
                db_constraint=False,
                db_index=False,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.RunPython(backfill_paused_by_user, reverse_code=migrations.RunPython.noop),
    ]
