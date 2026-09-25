from django.db import migrations

from posthog.migration_helpers.lock_phase import lock_tables


def lock_view_history(apps, schema_editor):
    lock_tables(schema_editor, ["posthog_insightviewed"])


class Migration(migrations.Migration):
    dependencies = [("product_analytics", "0013_insight_viewed_context_uniqueness")]

    operations = [
        migrations.RunPython(lock_view_history, migrations.RunPython.noop),
        migrations.RemoveConstraint(model_name="insightviewed", name="posthog_unique_insightviewed"),
    ]
