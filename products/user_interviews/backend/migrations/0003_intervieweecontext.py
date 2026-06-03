import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

import posthog.models.utils


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("posthog", "1152_fix_device_bucketing_persist_across_auth"),
        ("user_interviews", "0002_userinterviewtopic"),
    ]

    operations = [
        migrations.CreateModel(
            name="IntervieweeContext",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "id",
                    models.UUIDField(
                        default=posthog.models.utils.UUIDT, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("interviewee_identifier", models.CharField(max_length=400)),
                ("agent_context", models.TextField()),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                ("team", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="posthog.team")),
                (
                    "topic",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="interviewee_contexts",
                        to="user_interviews.userinterviewtopic",
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddConstraint(
            model_name="intervieweecontext",
            constraint=models.UniqueConstraint(
                fields=("topic", "interviewee_identifier"), name="unique_interviewee_per_topic"
            ),
        ),
    ]
