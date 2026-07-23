from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("tasks", "0071_task_session")]

    operations = [
        migrations.AddField(
            model_name="tasksession",
            name="revision",
            field=models.PositiveBigIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="tasksession",
            name="pending_sync_id",
            field=models.UUIDField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="tasksession",
            name="pending_object_storage_key",
            field=models.CharField(blank=True, max_length=512, null=True, unique=True),
        ),
    ]
