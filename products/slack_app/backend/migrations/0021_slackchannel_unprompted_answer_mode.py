from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("slack_app", "0020_slacksettings_auto_model_choice"),
    ]

    operations = [
        migrations.AddField(
            model_name="slackchannel",
            name="unprompted_answer_mode",
            field=models.CharField(
                blank=True,
                choices=[
                    ("auto", "Always pick it up"),
                    ("ask", "Ask before picking it up"),
                    ("never", "Never pick it up"),
                ],
                help_text="The most PostHog may do with a top-level question in this channel that does not tag it.",
                max_length=16,
                null=True,
            ),
        ),
    ]
