import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("workflows", "0034_teamworkflowsconfig_replay_vision_scan_limits"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="hogflow",
            name="enable_requested_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="hogflow",
            name="enable_requested_by",
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
        migrations.AddField(
            model_name="hogflow",
            name="went_live_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        # Choices live only in Django's state, so the new status value needs no SQL.
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterField(
                    model_name="hogflow",
                    name="status",
                    field=models.CharField(
                        choices=[
                            ("draft", "Draft"),
                            ("active", "Active"),
                            ("waiting_for_domain", "Waiting For Domain"),
                            ("archived", "Archived"),
                        ],
                        default="draft",
                        max_length=20,
                    ),
                ),
            ],
            database_operations=[],
        ),
    ]
