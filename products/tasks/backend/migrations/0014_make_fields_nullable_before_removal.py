from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("tasks", "0013_taskrun_artifacts"),
    ]

    operations = [
        migrations.AlterField(
            model_name="task",
            name="position",
            field=models.IntegerField(default=0, null=True),
        ),
        migrations.AlterField(
            model_name="task",
            name="repository_config",
            field=models.JSONField(
                default=dict,
                null=True,
                help_text="Repository configuration with organization and repository fields",
            ),
        ),
        migrations.AlterField(
            model_name="taskrun",
            name="log",
            field=models.JSONField(
                blank=True,
                default=list,
                null=True,
                help_text="DEPRECATED: Logs now stored in S3. This field only contains legacy logs.",
            ),
        ),
    ]
