import django.db.models.deletion
from django.contrib.postgres.fields import ArrayField
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1280_alter_integration_kind"),
        ("tasks", "0079_backfill_task_repositories"),
    ]

    operations = [
        migrations.AddField(
            model_name="channel",
            name="github_integration",
            field=models.ForeignKey(
                blank=True,
                limit_choices_to={"kind": "github"},
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to="posthog.integration",
            ),
        ),
        migrations.AddField(
            model_name="channel",
            name="repositories",
            field=ArrayField(
                base_field=models.CharField(max_length=255),
                blank=True,
                db_default=[],
                default=list,
                help_text="GitHub repositories inherited by new tasks in this channel",
                size=None,
            ),
        ),
    ]
