from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("tasks", "0084_sandboxsession_provider_cpu_usage")]

    operations = [
        migrations.AddField(
            model_name="sandboxsession",
            name="provider_cpu_usage_attribution_measured_at",
            field=models.DateTimeField(
                blank=True,
                help_text="When provider CPU usage was sampled at user attribution",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="sandboxsession",
            name="provider_cpu_usage_attribution_usec",
            field=models.PositiveBigIntegerField(
                blank=True,
                help_text="Cumulative provider CPU time sampled when user attribution starts",
                null=True,
            ),
        ),
    ]
