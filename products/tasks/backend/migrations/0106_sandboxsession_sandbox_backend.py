from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("tasks", "0105_taskrun_webhook_lookup_indexes")]

    operations = [
        migrations.AddField(
            model_name="sandboxsession",
            name="sandbox_backend",
            field=models.CharField(
                blank=True,
                help_text="Provider backend (e.g. hogland); NULL for Modal. Hogland's TTL is idle, not absolute",
                max_length=32,
                null=True,
            ),
        ),
    ]
