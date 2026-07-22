from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("managed_migrations", "0001_migrate_managed_migrations_models"),
    ]

    operations = [
        migrations.AlterField(
            model_name="batchimport",
            name="status",
            field=models.TextField(
                choices=[
                    ("completed", "Completed"),
                    ("failed", "Failed"),
                    ("paused", "Paused"),
                    ("running", "Running"),
                    ("cancelled", "Cancelled"),
                ],
                default="running",
            ),
        ),
    ]
