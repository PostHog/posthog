import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("signals", "0076_signalscoutnote_discussion_origin"),
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
    ]
