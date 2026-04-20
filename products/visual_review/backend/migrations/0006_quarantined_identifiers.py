import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("visual_review", "0005_tolerated_hashes"),
    ]

    operations = [
        migrations.CreateModel(
            name="QuarantinedIdentifier",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("team_id", models.BigIntegerField(db_index=True)),
                ("identifier", models.CharField(max_length=512)),
                ("run_type", models.CharField(max_length=20)),
                ("reason", models.CharField(max_length=255)),
                ("expires_at", models.DateTimeField(blank=True, null=True)),
                ("created_by_id", models.BigIntegerField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "repo",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="quarantined_identifiers",
                        to="visual_review.repo",
                    ),
                ),
            ],
        ),
        migrations.AddConstraint(
            model_name="quarantinedidentifier",
            constraint=models.UniqueConstraint(
                fields=["repo", "identifier", "run_type"],
                name="unique_quarantined_identifier",
            ),
        ),
        migrations.AddIndex(
            model_name="quarantinedidentifier",
            index=models.Index(fields=["repo", "run_type", "identifier"], name="quarantine_lookup"),
        ),
        migrations.AddField(
            model_name="runsnapshot",
            name="is_quarantined",
            field=models.BooleanField(default=False),
        ),
    ]
