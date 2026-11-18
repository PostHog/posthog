import uuid

import django.utils.timezone
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1342_drop_cimd_blocklist_table"),
        ("tasks", "0117_task_set_null_cascade_indexes"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterField(
            model_name="channel",
            name="channel_type",
            field=models.CharField(
                choices=[
                    ("public", "Public"),
                    ("personal", "Personal"),
                    ("private", "Private"),
                ],
                default="public",
                max_length=16,
            ),
        ),
        migrations.CreateModel(
            name="ChannelMembership",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "channel",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="memberships",
                        to="tasks.channel",
                    ),
                ),
                (
                    "team",
                    models.ForeignKey(
                        db_constraint=False,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="+",
                        to="posthog.team",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        db_constraint=False,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "db_table": "posthog_task_channel_membership",
                "constraints": [
                    models.UniqueConstraint(
                        fields=("channel", "user"),
                        name="task_channel_membership_unique",
                    )
                ],
            },
        ),
    ]
