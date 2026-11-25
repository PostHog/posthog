import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("meep", "0001_initial")]

    operations = [
        migrations.AddField(model_name="chatturn", name="target_message_id", field=models.UUIDField(null=True)),
        migrations.AddField(
            model_name="boardrun",
            name="parent_turn",
            field=models.ForeignKey(
                null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="children", to="meep.chatturn"
            ),
        ),
        migrations.AddField(model_name="boardrun", name="request_id", field=models.UUIDField(null=True)),
        migrations.AddField(
            model_name="boardrun", name="notified", field=models.BooleanField(default=False, db_default=False)
        ),
        migrations.AddConstraint(
            model_name="boardrun",
            constraint=models.UniqueConstraint(fields=("topic", "request_id"), name="meep_unique_child_request"),
        ),
        migrations.CreateModel(
            name="ChildWait",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("request_id", models.UUIDField()),
                ("parent_run_id", models.UUIDField()),
                ("item_ids", models.JSONField(default=list)),
                ("child_run_ids", models.JSONField(default=list)),
                ("status", models.CharField(default="waiting", max_length=16)),
                (
                    "topic",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE, related_name="child_waits", to="meep.topic"
                    ),
                ),
                (
                    "turn",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE, related_name="child_waits", to="meep.chatturn"
                    ),
                ),
            ],
            options={
                "constraints": [models.UniqueConstraint(fields=("topic", "request_id"), name="meep_unique_child_wait")]
            },
        ),
    ]
