from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("messaging", "0012_email_hard_bounce"),
    ]

    operations = [
        migrations.AddField(
            model_name="messagetemplate",
            name="key",
            field=models.CharField(
                blank=True,
                help_text="Client-chosen identifier, unique within this environment among templates that are not deleted. Letters, numbers, hyphens (-) and underscores (_) only.",
                max_length=400,
                null=True,
            ),
        ),
    ]
