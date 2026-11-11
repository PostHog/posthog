from django.db import migrations

from posthog.migration_helpers import DropFieldIndexesConcurrently, SafeRemoveIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("review_hog", "0034_review_repositories"),
    ]

    operations = [
        DropFieldIndexesConcurrently(model_name="reviewreportartefact", name="report"),
        SafeRemoveIndexConcurrently(model_name="reviewreportartefact", name="reviewhog_art_report_idx"),
    ]
