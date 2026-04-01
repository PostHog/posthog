from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("experiments", "0001_migrate_experiments_models"),
    ]

    operations = [
        migrations.AddField(
            model_name="experiment",
            name="only_count_matured_users",
            field=models.BooleanField(default=False),
        ),
    ]
