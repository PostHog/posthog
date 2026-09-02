from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("tasks", "0083_taskcommentactivity")]

    operations = [
        migrations.AddField(
            model_name="sandboxsession",
            name="provider_cpu_usage_usec",
            field=models.PositiveBigIntegerField(
                blank=True,
                help_text="Cumulative provider CPU time sampled immediately before sandbox cleanup",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="sandboxsession",
            name="provider_usage_measured_at",
            field=models.DateTimeField(
                blank=True,
                help_text="When provider resource usage was sampled",
                null=True,
            ),
        ),
    ]
