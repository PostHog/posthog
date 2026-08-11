from django.db import migrations

from posthog.migration_helpers import SafeRemoveIndexConcurrently


class Migration(migrations.Migration):
    # Concurrent index drops cannot run inside a transaction.
    atomic = False

    dependencies = [
        (
            "error_tracking",
            "0021_remove_errortrackingsettings_autocapture_exceptions_opt_in",
        ),
    ]

    operations = [
        # Duplicates `unique_ref_per_team` on the same (team_id, ref) columns. The unique
        # constraint serves every scan the workload issues against those columns, so the
        # only thing this index still costs is write amplification and ~106 GB.
        SafeRemoveIndexConcurrently(
            model_name="errortrackingsymbolset",
            name="posthog_err_team_id_927574_idx",
        ),
    ]
