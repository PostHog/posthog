from django.db import migrations, models


class Migration(migrations.Migration):
    """Additive-only schema change. All existing rows receive the default `paused` status; the
    row-updating backfill that resets rows to `active` where `enabled=True` lives in 0024 so the
    schema change can land and be rolled back independently of the data migration."""

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
    ]
