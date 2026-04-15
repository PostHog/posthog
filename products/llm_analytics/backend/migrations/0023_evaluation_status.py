from django.db import migrations, models


def backfill_status(apps, schema_editor):
    Evaluation = apps.get_model("llm_analytics", "Evaluation")
    # We can't retroactively tell which disabled evals were system-disabled vs user-paused,
    # so everything inactive starts as PAUSED. Future system transitions will set ERROR correctly.
    Evaluation.objects.filter(enabled=True).update(status="active")
    Evaluation.objects.filter(enabled=False).update(status="paused")


def reverse_noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("llm_analytics", "0022_reviewqueue_reviewqueueitem_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="evaluation",
            name="status",
            field=models.CharField(
                choices=[
                    ("active", "Active"),
                    ("paused", "Paused"),
                    ("error", "Error"),
                ],
                default="paused",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="evaluation",
            name="status_reason",
            field=models.CharField(
                blank=True,
                choices=[
                    ("trial_limit_reached", "Trial evaluation limit reached"),
                    ("model_not_allowed", "Model not available on the trial plan"),
                    ("provider_key_deleted", "Provider API key was deleted"),
                ],
                max_length=50,
                null=True,
            ),
        ),
        migrations.RunPython(backfill_status, reverse_noop),
    ]
