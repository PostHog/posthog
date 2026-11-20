from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("workflows", "0047_hogflowbatchjob_max_audience_size"),
    ]

    operations = [
        migrations.AddField(
            model_name="teamworkflowsconfig",
            name="email_workflow_run_link_tag_enabled",
            field=models.BooleanField(db_default=True, default=True),
        ),
    ]
