from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("skills", "0006_llmskill_version_description"),
    ]

    operations = [
        migrations.AddField(
            model_name="llmskill",
            name="provenance",
            field=models.CharField(
                blank=True, choices=[("posthog", "PostHog")], db_default="", default="", max_length=32
            ),
        ),
    ]
