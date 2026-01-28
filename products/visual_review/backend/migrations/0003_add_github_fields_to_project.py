from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("visual_review", "0002_add_hash_fields_to_runsnapshot"),
    ]

    operations = [
        migrations.AddField(
            model_name="project",
            name="repo_full_name",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="project",
            name="baseline_file_paths",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
