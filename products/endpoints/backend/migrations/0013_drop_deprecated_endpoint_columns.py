# This migration drops deprecated columns from the endpoints_endpoint table.
# IMPORTANT: Only merge this AFTER migration 0012 has been deployed and stable.
#
# Migration 0012 removed these fields from Django state (code can't access them),
# but left the columns in the database for safe rollback during deployment.
# This migration completes the cleanup by dropping the actual columns.

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("endpoints", "0012_remove_deprecated_endpoint_fields"),
    ]

    operations = [
        migrations.RunSQL(
            sql='ALTER TABLE "endpoints_endpoint" DROP COLUMN IF EXISTS "cache_age_seconds"',
            reverse_sql='ALTER TABLE "endpoints_endpoint" ADD COLUMN "cache_age_seconds" INTEGER NULL',
        ),
        migrations.RunSQL(
            sql='ALTER TABLE "endpoints_endpoint" DROP COLUMN IF EXISTS "description"',
            reverse_sql='ALTER TABLE "endpoints_endpoint" ADD COLUMN "description" TEXT NULL',
        ),
        migrations.RunSQL(
            sql='ALTER TABLE "endpoints_endpoint" DROP COLUMN IF EXISTS "parameters"',
            reverse_sql='ALTER TABLE "endpoints_endpoint" ADD COLUMN "parameters" JSONB NULL',
        ),
        migrations.RunSQL(
            sql='ALTER TABLE "endpoints_endpoint" DROP COLUMN IF EXISTS "query"',
            reverse_sql='ALTER TABLE "endpoints_endpoint" ADD COLUMN "query" JSONB NULL',
        ),
        migrations.RunSQL(
            sql='ALTER TABLE "endpoints_endpoint" DROP COLUMN IF EXISTS "saved_query_id"',
            reverse_sql='ALTER TABLE "endpoints_endpoint" ADD COLUMN "saved_query_id" UUID NULL',
        ),
    ]
