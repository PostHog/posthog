from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("surveys", "0005_migrate_product_analytics_models"),
    ]

    operations = [
        migrations.AddField(
            model_name="survey",
            name="ai_translations_snapshot",
            field=models.JSONField(blank=True, null=True),
        ),
    ]
