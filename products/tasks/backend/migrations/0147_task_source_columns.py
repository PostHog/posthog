from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("tasks", "0146_sandboxsession_settle_indexes"),
    ]

    operations = [
        migrations.AddField(
            model_name="task",
            name="source_kind",
            field=models.CharField(blank=True, max_length=32, null=True),
        ),
        migrations.AddField(
            model_name="task",
            name="source_id",
            field=models.CharField(blank=True, max_length=64, null=True),
        ),
        migrations.AddField(
            model_name="task",
            name="idempotency_key",
            field=models.CharField(blank=True, max_length=128, null=True),
        ),
    ]
