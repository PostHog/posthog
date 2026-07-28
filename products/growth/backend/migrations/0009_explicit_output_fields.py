from django.db import migrations

# The output contract used to fall back to the config's label name when output_fields was empty,
# which made a human-readable label into a data key. Every config now carries its schema
# explicitly so the two are independent and a label can be renamed freely.
LEGACY_SHAPE = [
    {"key": "confidence", "type": "number", "description": "0-1 confidence in the verdict."},
    {"key": "reasoning", "type": "string", "description": "One short sentence."},
]


def set_explicit_output_fields(apps, schema_editor):
    EnrichmentPromptConfig = apps.get_model("growth", "EnrichmentPromptConfig")
    for config in EnrichmentPromptConfig.objects.filter(output_fields=[]):
        config.output_fields = [
            {"key": config.name, "type": "boolean", "description": f"Whether the company is {config.name}."},
            *LEGACY_SHAPE,
        ]
        config.save(update_fields=["output_fields"])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [("growth", "0008_enrichmentpromptconfig_input_query_and_more")]

    operations = [migrations.RunPython(set_explicit_output_fields, noop)]
