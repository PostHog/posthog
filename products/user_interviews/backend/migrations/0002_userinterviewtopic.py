import django.db.models.deletion
import django.contrib.postgres.fields
from django.conf import settings
from django.db import migrations, models

import posthog.models.utils

import products.user_interviews.backend.models


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("posthog", "1152_fix_device_bucketing_persist_across_auth"),
        ("user_interviews", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="UserInterviewTopic",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "id",
                    models.UUIDField(
                        default=posthog.models.utils.UUIDT, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("interviewee_cohort", models.BigIntegerField(blank=True, null=True)),
                (
                    "interviewee_emails",
                    django.contrib.postgres.fields.ArrayField(
                        base_field=models.CharField(
                            max_length=254,
                            validators=[products.user_interviews.backend.models.EmailWithDisplayNameValidator()],
                        ),
                        blank=True,
                        default=list,
                        size=None,
                    ),
                ),
                (
                    "interviewee_distinct_ids",
                    django.contrib.postgres.fields.ArrayField(
                        base_field=models.CharField(max_length=400),
                        blank=True,
                        default=list,
                        size=None,
                    ),
                ),
                ("topic", models.TextField()),
                ("agent_context", models.TextField(blank=True, default="")),
                (
                    "questions",
                    django.contrib.postgres.fields.ArrayField(
                        base_field=models.TextField(),
                        blank=True,
                        default=list,
                        size=None,
                    ),
                ),
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
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
    ]
