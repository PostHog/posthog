from django.db import migrations

# One `kind:version` stamp per node of the insight query that carries a `kind`, at any depth,
# with a missing or null version stamped as 0. The schema-upgrade workflow tests staleness as an
# overlap against this array, which the GIN index in the next migration serves.
CREATE_SCHEMA_VERSIONS_FN = """
CREATE OR REPLACE FUNCTION posthog_dashboarditem_schema_versions(query jsonb) RETURNS text[]
LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT AS $$
    SELECT array_agg(DISTINCT (node ->> 'kind') || ':' || coalesce(node ->> 'version', '0'))
    FROM jsonb_path_query(query, '$.** ? (exists(@.kind))') AS node
$$;
"""

DROP_SCHEMA_VERSIONS_FN = "DROP FUNCTION IF EXISTS posthog_dashboarditem_schema_versions(jsonb);"


class Migration(migrations.Migration):
    dependencies = [("product_analytics", "0008_repair_insightviewed_null_unique_index")]

    operations = [migrations.RunSQL(CREATE_SCHEMA_VERSIONS_FN, DROP_SCHEMA_VERSIONS_FN)]
