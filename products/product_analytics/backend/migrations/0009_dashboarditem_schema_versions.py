from django.db import migrations

# One `kind:version` stamp per node of the insight query that carries a `kind`, at any depth,
# with a missing or null version stamped as 0. The schema-upgrade workflow tests staleness as an
# overlap against this array, which the GIN index in the next migration serves.
#
# The stamp must carry the same integer text the workflow enumerates. Query schemas type
# `version` as a float, so a saved node can hold 3.0, which floor() brings back to 3. A version of
# any other JSON type is not one the upgrade can read, so that node gets no stamp.
CREATE_SCHEMA_VERSIONS_FN = """
CREATE OR REPLACE FUNCTION posthog_dashboarditem_schema_versions(query jsonb) RETURNS text[]
LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT AS $$
    SELECT array_agg(DISTINCT stamp)
    FROM (
        SELECT (node ->> 'kind') || ':' || CASE coalesce(jsonb_typeof(node -> 'version'), 'null')
            WHEN 'number' THEN greatest(floor((node ->> 'version')::numeric), 0)::text
            WHEN 'null' THEN '0'
        END AS stamp
        FROM jsonb_path_query(query, '$.** ? (exists(@.kind))') AS node
    ) AS nodes
    WHERE stamp IS NOT NULL
$$;
"""

DROP_SCHEMA_VERSIONS_FN = "DROP FUNCTION IF EXISTS posthog_dashboarditem_schema_versions(jsonb);"


class Migration(migrations.Migration):
    dependencies = [("product_analytics", "0008_repair_insightviewed_null_unique_index")]

    operations = [migrations.RunSQL(CREATE_SCHEMA_VERSIONS_FN, DROP_SCHEMA_VERSIONS_FN)]
