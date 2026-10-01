from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    """
    Result lookups by calculation key filter on (experiment, metric_uuid, fingerprint) and then on query_to.
    The index is not unique, so it does not limit a calculation key to one row per window.

    Built with CREATE INDEX CONCURRENTLY (SHARE UPDATE EXCLUSIVE) rather than a plain AddIndex, so reads and
    writes on posthog_experimentmetricresult keep running while it builds.
    """

    atomic = False

    dependencies = [
        ("experiments", "0046_untrack_legacy_recalculation_time"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="experimentmetricresult",
            index=models.Index(
                fields=["experiment", "metric_uuid", "fingerprint", "query_to"], name="exp_metric_result_key_idx"
            ),
        ),
    ]
