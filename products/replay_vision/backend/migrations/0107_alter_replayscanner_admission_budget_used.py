from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("replay_vision", "0106_remove_prompt_suggestions"),
    ]

    operations = [
        migrations.AlterField(
            model_name="replayscanner",
            name="admission_budget_used",
            field=models.IntegerField(
                blank=True,
                help_text="Credits counted against credit_limit at the last admission-budget refresh: settled receipts and in-flight reservations.",
                null=True,
            ),
        ),
    ]
