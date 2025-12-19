from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("endpoints", "0007_fix_hogql_variable_keys"),
    ]

    operations = [
        migrations.AddField(
            model_name="endpoint",
            name="last_execution_time",
            field=models.DateTimeField(
                blank=True,
                help_text="Last time this endpoint was executed via /run. Updated with hour granularity.",
                null=True,
            ),
        ),
    ]
