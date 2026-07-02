import django.contrib.postgres.fields
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("tasks", "0046_task_channel_feed_index"),
    ]

    operations = [
        migrations.AddField(
            model_name="task",
            name="additional_repositories",
            field=django.contrib.postgres.fields.ArrayField(
                base_field=models.CharField(max_length=255),
                blank=True,
                default=list,
                help_text=(
                    "Extra repos cloned into the sandbox alongside `repository` so the agent can work "
                    "across them. Each is organization/repo. PRs still target `repository`."
                ),
                size=None,
            ),
        ),
    ]
