import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    """Track which run prompted a quarantine so reviewers can jump back to
    the failing snapshot. Mirrors `ToleratedHash.source_run`. Nullable so
    historical entries and quarantines created without run context (e.g.
    from the snapshot history page) still validate.
    """

    dependencies = [
        ("visual_review", "0001_squash_2026_09_07_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="quarantinedidentifier",
            name="source_run",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="originated_quarantines",
                to="visual_review.run",
            ),
        ),
    ]
