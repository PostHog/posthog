from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("exports", "0001_migrate_exports_models"),
    ]

    operations = [
        migrations.AddField(
            model_name="subscription",
            name="prompt",
            field=models.TextField(blank=True, null=True),
        ),
    ]
