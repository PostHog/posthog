from django.db import migrations, models


def migrate_prompt_to_configs(apps, schema_editor):
    """Migrate prompt field to evaluation_config/output_config structure"""
    Evaluation = apps.get_model("llm_analytics", "Evaluation")

    batch_size = 1000
    evaluations = Evaluation.objects.all()

    updates = []
    for evaluation in evaluations.iterator(chunk_size=batch_size):
        evaluation.evaluation_type = "llm_judge"
        evaluation.output_type = "boolean"
        evaluation.evaluation_config = {"prompt": evaluation.prompt}
        evaluation.output_config = {}
        updates.append(evaluation)

        if len(updates) >= batch_size:
            Evaluation.objects.bulk_update(
                updates,
                ["evaluation_type", "output_type", "evaluation_config", "output_config"],
                batch_size=batch_size,
            )
            updates = []

    if updates:
        Evaluation.objects.bulk_update(
            updates,
            ["evaluation_type", "output_type", "evaluation_config", "output_config"],
            batch_size=batch_size,
        )


def reverse_migrate_configs_to_prompt(apps, schema_editor):
    """Reverse migration: copy evaluation_config['prompt'] back to prompt"""
    Evaluation = apps.get_model("llm_analytics", "Evaluation")

    batch_size = 1000
    evaluations = Evaluation.objects.all()

    updates = []
    for evaluation in evaluations.iterator(chunk_size=batch_size):
        if evaluation.evaluation_config and "prompt" in evaluation.evaluation_config:
            evaluation.prompt = evaluation.evaluation_config["prompt"]
            updates.append(evaluation)

            if len(updates) >= batch_size:
                Evaluation.objects.bulk_update(updates, ["prompt"], batch_size=batch_size)
                updates = []

    if updates:
        Evaluation.objects.bulk_update(updates, ["prompt"], batch_size=batch_size)


class Migration(migrations.Migration):
    dependencies = [
        ("llm_analytics", "0002_evaluation"),
    ]

    operations = [
        # Step 1: Add new fields (nullable initially)
        migrations.AddField(
            model_name="evaluation",
            name="evaluation_type",
            field=models.CharField(
                choices=[("llm_judge", "LLM as a judge")],
                max_length=50,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="evaluation",
            name="evaluation_config",
            field=models.JSONField(default=dict, null=True),
        ),
        migrations.AddField(
            model_name="evaluation",
            name="output_type",
            field=models.CharField(
                choices=[("boolean", "Boolean (Pass/Fail)")],
                max_length=50,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="evaluation",
            name="output_config",
            field=models.JSONField(default=dict, null=True),
        ),
        # Step 2: Migrate data
        # This is safe to run synchronously since the Evaluation model is not yet in production use (count < 100)
        migrations.RunPython(migrate_prompt_to_configs, reverse_migrate_configs_to_prompt),
        # Step 3: Make new fields non-nullable
        migrations.AlterField(
            model_name="evaluation",
            name="evaluation_type",
            field=models.CharField(
                choices=[("llm_judge", "LLM as a judge")],
                max_length=50,
            ),
        ),
        migrations.AlterField(
            model_name="evaluation",
            name="evaluation_config",
            field=models.JSONField(default=dict),
        ),
        migrations.AlterField(
            model_name="evaluation",
            name="output_type",
            field=models.CharField(
                choices=[("boolean", "Boolean (Pass/Fail)")],
                max_length=50,
            ),
        ),
        migrations.AlterField(
            model_name="evaluation",
            name="output_config",
            field=models.JSONField(default=dict),
        ),
        # Step 4: Remove old prompt field
        migrations.RemoveField(
            model_name="evaluation",
            name="prompt",
        ),
    ]
