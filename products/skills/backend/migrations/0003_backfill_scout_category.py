from django.db import migrations


def backfill_scout_category(apps, schema_editor):
    # One-time decoupling: existing scouts were only identifiable by the historical
    # `signals-scout-*` name convention. Stamp them with the new generic category so the UI and
    # API can filter on `category` instead of the name prefix going forward. The prefix is used
    # here, and only here, as the source of historical truth.
    LLMSkill = apps.get_model("skills", "LLMSkill")
    LLMSkill.objects.filter(name__startswith="signals-scout-").update(category="scout")


def unset_scout_category(apps, schema_editor):
    LLMSkill = apps.get_model("skills", "LLMSkill")
    LLMSkill.objects.filter(category="scout").update(category="")


class Migration(migrations.Migration):
    dependencies = [
        ("skills", "0002_llmskill_category"),
    ]

    operations = [
        migrations.RunPython(backfill_scout_category, unset_scout_category),
    ]
