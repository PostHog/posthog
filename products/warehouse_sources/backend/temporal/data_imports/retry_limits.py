from datetime import timedelta

# The largest retry cap an import activity gets. It lives apart from `external_data_job` so the
# schema model can read it: that module loads temporalio, and the model loads during django.setup().
MAX_RESUMABLE_SOURCE_RETRIES_PRODUCTION = 15

# How long a resumable import may run across all of its attempts. A worker hand-off does not count
# toward the cap above, so this is what ends an import that hands off and never finishes. It is
# shorter than the TTL of the v3 pipeline lock, because the run takes that lock before the import.
RESUMABLE_IMPORT_DEADLINE = timedelta(days=6)
