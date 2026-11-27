from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("warehouse_sources", "0208_move_apollo_accounts_to_full_refresh"),
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
