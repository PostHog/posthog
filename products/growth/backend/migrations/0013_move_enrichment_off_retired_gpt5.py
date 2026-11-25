from django.db import migrations

# OpenAI shuts these models down on 2026-12-11. A prompt config still saved on them would fail every enrichment run.
RETIRED_MODELS = ("gpt-5", "gpt-5-mini", "gpt-5-nano")
REPLACEMENT_MODEL = "gpt-6-luna"


def move_prompt_configs_off_retired_models(apps, schema_editor):
    EnrichmentPromptConfig = apps.get_model("growth", "EnrichmentPromptConfig")
    EnrichmentPromptConfig.objects.filter(model__in=RETIRED_MODELS).update(model=REPLACEMENT_MODEL)


class Migration(migrations.Migration):
    dependencies = [
        ("growth", "0012_daily_health_rollups_autovacuum"),
    ]

    operations = [
        migrations.RunPython(move_prompt_configs_off_retired_models, migrations.RunPython.noop),
    ]
