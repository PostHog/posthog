from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("tasks", "0096_taskworkflowdispatch")]

    operations = [
        migrations.AddField(
            model_name="sandboxsession",
            name="provider_billed_cpu_usage_attribution_usec",
            field=models.PositiveBigIntegerField(
                blank=True, help_text="Estimated billed CPU time sampled when user attribution starts", null=True
            ),
        ),
        migrations.AddField(
            model_name="sandboxsession",
            name="provider_billed_cpu_usage_usec",
            field=models.PositiveBigIntegerField(
                blank=True, help_text="Estimated billed CPU time sampled immediately before sandbox cleanup", null=True
            ),
        ),
    ]
