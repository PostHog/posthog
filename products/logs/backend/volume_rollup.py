"""Facts about `logs_volume_buckets` that both its writer and its readers need."""

import os
from datetime import timedelta

# TTL on logs_volume_buckets, see posthog/clickhouse/hcl/sql/*/logs.sql. The
# table keeps a row longer when the team's log retention is longer, so this is
# the floor every team gets, not a ceiling.
VOLUME_BUCKETS_TTL_DAYS = 42

# A bucket only becomes due this long after it closes, so late-arriving logs are
# already in place when it is counted. Sized from measured prod ingestion lag:
# 99.96% of rows land within 10 minutes; the residual tail is reconciliation's job.
# A dial, not grid identity: env-tunable (read at import, so a worker restart applies it).
FINALIZATION_ALLOWANCE = timedelta(minutes=int(os.environ.get("LOGS_VOLUME_TICK_FINALIZATION_ALLOWANCE_MINUTES", "10")))
