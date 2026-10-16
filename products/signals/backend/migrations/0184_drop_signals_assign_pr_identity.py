from django.db import migrations

from posthog.migration_helpers import SafeRemoveIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [("signals", "0183_spend_accounting_failures")]

    operations = [
        # The only lookup on these columns uses iexact, which a plain btree on repository cannot serve.
        SafeRemoveIndexConcurrently(
            model_name="signalreportassignment",
            name="signals_assign_pr_identity",
        ),
    ]
