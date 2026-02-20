from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("llm_analytics", "0016_rename_gemini_provider_to_google"),
    ]

    operations = [
        migrations.AlterField(
            model_name="llmproviderkey",
            name="provider",
            field=models.CharField(
                choices=[
                    ("openai", "Openai"),
                    ("anthropic", "Anthropic"),
                    ("google", "Google"),
                    ("openrouter", "Openrouter"),
                    ("fireworks", "Fireworks"),
                ],
                max_length=50,
            ),
        ),
        migrations.AlterField(
            model_name="llmmodelconfiguration",
            name="provider",
            field=models.CharField(
                choices=[
                    ("openai", "Openai"),
                    ("anthropic", "Anthropic"),
                    ("google", "Google"),
                    ("openrouter", "Openrouter"),
                    ("fireworks", "Fireworks"),
                ],
                max_length=50,
            ),
        ),
    ]
