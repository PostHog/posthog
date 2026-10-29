from django.db import migrations

from posthog.migration_helpers import SafeRemoveIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [("signals", "0219_signalteamconfig_implementation_repositories")]

    operations = [
        # The only lookup on these columns uses iexact. A plain btree on repository cannot serve it.
        SafeRemoveIndexConcurrently(
            model_name="signalreportassignment",
            name="signals_assign_pr_identity",
        ),
    ]
