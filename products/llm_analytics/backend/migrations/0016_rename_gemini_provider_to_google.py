from django.db import migrations, models


def forward_rename_gemini_to_google(apps, schema_editor):
    llm_provider_key = apps.get_model("llm_analytics", "LLMProviderKey")
    llm_model_configuration = apps.get_model("llm_analytics", "LLMModelConfiguration")

    llm_provider_key.objects.filter(provider="gemini").update(provider="google")
    llm_model_configuration.objects.filter(provider="gemini").update(provider="google")


def backward_rename_google_to_gemini(apps, schema_editor):
    llm_provider_key = apps.get_model("llm_analytics", "LLMProviderKey")
    llm_model_configuration = apps.get_model("llm_analytics", "LLMModelConfiguration")

    llm_provider_key.objects.filter(provider="google").update(provider="gemini")
    llm_model_configuration.objects.filter(provider="google").update(provider="gemini")


class Migration(migrations.Migration):
    dependencies = [
        ("llm_analytics", "0015_add_fireworks_provider"),
    ]

    operations = [
        migrations.RunPython(forward_rename_gemini_to_google, backward_rename_google_to_gemini),
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
