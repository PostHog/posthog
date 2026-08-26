from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("replay_vision", "0082_admission_budget_cache"),
    ]

    operations = [
        migrations.AlterField(
            model_name="replayscanner",
            name="admission_credits_since_refresh",
            field=models.PositiveIntegerField(
                default=0,
                db_default=0,
                help_text="Credits admitted since the last admission-budget refresh. Every refresh resets this to the admitting cost, or to zero on a refusal.",
            ),
        ),
    ]
