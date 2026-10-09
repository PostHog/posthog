from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("slack_app", "0020_slacksettings_auto_model_choice"),
    ]

    operations = [
        migrations.AddField(
            model_name="slacksettings",
            name="unprompted_answer_mode",
            field=models.CharField(
                blank=True,
                choices=[("auto", "Answer automatically"), ("ask", "Ask me first"), ("off", "Never answer")],
                help_text="What PostHog does with this user's top-level channel messages that do not tag the app.",
                max_length=16,
                null=True,
            ),
        ),
    ]
