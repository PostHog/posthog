from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("warehouse_sources", "0207_externaldataschema_last_checked_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="externaldataschema",
            name="new_column_policy",
            field=models.CharField(
                blank=True,
                choices=[("include", "Include"), ("exclude", "Exclude")],
                max_length=16,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="externaldatasource",
            name="new_column_policy",
            field=models.CharField(
                blank=True,
                choices=[("include", "Include"), ("exclude", "Exclude")],
                max_length=16,
                null=True,
            ),
        ),
    ]
