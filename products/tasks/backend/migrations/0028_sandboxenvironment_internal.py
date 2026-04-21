from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("tasks", "0027_task_signal_report_idx"),
    ]

    operations = [
        migrations.AddField(
            model_name="sandboxenvironment",
            name="internal",
            field=models.BooleanField(
                default=False,
                help_text="If true, this environment is for internal use (e.g. signals pipeline) and should not be exposed to end users.",
            ),
        ),
    ]
