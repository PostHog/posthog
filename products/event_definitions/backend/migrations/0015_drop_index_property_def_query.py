from django.db import migrations

from posthog.migration_helpers import SafeRemoveIndexConcurrently


class Migration(migrations.Migration):
    # Concurrent index drops cannot run inside a transaction.
    atomic = False

    dependencies = [("event_definitions", "0014_drop_taxonomy_project_id_fk_idx")]

    operations = [
        # The team-keyed twin of index_property_def_query_proj. Readers moved to the project key, and the
        # remaining team-keyed reads plan on posthog_pro_team_id_eac36d_idx without it.
        SafeRemoveIndexConcurrently(model_name="propertydefinition", name="index_property_def_query"),
    ]
