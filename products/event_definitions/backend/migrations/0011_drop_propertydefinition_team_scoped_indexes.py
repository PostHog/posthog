from django.db import migrations

from posthog.migration_helpers.concurrent_index import SafeRemoveIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("event_definitions", "0010_propertydefinition_warehouse_origin"),
    ]

    # Both indexes lead with a bare team_id equality. Every reader scopes through
    # coalesce(project_id, team_id), which the project-scoped twins already serve
    # (index_property_def_query_proj and posthog_pro_project_3583d2_idx), so these
    # only add write cost on each property-definition upsert.
    operations = [
        SafeRemoveIndexConcurrently(
            model_name="propertydefinition",
            name="index_property_def_query",
        ),
        SafeRemoveIndexConcurrently(
            model_name="propertydefinition",
            name="posthog_pro_team_id_eac36d_idx",
        ),
    ]
