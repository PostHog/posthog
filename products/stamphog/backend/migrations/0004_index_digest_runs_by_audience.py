from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    """Index the (team, audience) lookup that decides how far back a claim reaches.

    Separate from 0003 because CREATE INDEX CONCURRENTLY cannot run inside a transaction, and 0003
    carries DDL that should stay atomic.
    """

    atomic = False

    dependencies = [("stamphog", "0003_digest_runs_record_their_destination")]

    operations = [
        SafeAddIndexConcurrently(
            model_name="digestrun",
            index=models.Index(fields=["team_id", "audience_key"], name="stamphog_digest_run_audience"),
        ),
    ]
