import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

import posthog.models.utils


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1098_add_customerio_integration_kinds"),
        ("messaging", "0002_optout_sync_config"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="MessageSuppression",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=posthog.models.utils.UUIDT,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("deleted", models.BooleanField(default=False)),
                ("identifier", models.CharField(max_length=512)),
                (
                    "source",
                    models.CharField(
                        choices=[("BOUNCE", "Bounce"), ("MANUAL", "Manual")],
                        default="BOUNCE",
                        max_length=16,
                    ),
                ),
                ("reason", models.TextField(blank=True, null=True)),
                ("transient_bounce_count", models.IntegerField(default=0)),
                ("last_bounce_at", models.DateTimeField(blank=True, null=True)),
                ("last_bounce_diagnostic", models.TextField(blank=True, null=True)),
                ("suppressed", models.BooleanField(default=False)),
                ("suppressed_at", models.DateTimeField(blank=True, null=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        db_constraint=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "team",
                    models.ForeignKey(
                        db_constraint=False,
                        on_delete=django.db.models.deletion.CASCADE,
                        to="posthog.team",
                    ),
                ),
            ],
            options={
                "db_table": "posthog_messagesuppression",
                "unique_together": {("team", "identifier")},
            },
        ),
    ]
