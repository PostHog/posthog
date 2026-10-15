from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("signals", "0143_scout_emission_confidence_nullable"),
    ]

    operations = [
        # Hand-written `ADD COLUMN` rather than the `AddField` SQL: `auto_now` gives the field an
        # effective default, so Django would stamp every existing row with the migration's own
        # timestamp. A run that settled last month did not change at deploy time, so the rows the
        # column never observed stay NULL and a reader that wants one timestamp per row takes
        # `coalesce(updated_at, created_at)`. No default and no backfill keeps the ALTER
        # metadata-only. `IF NOT EXISTS` so a `bin/migrate` retry is a no-op.
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddField(
                    model_name="signalscoutrun",
                    name="updated_at",
                    field=models.DateTimeField(auto_now=True, null=True),
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql='ALTER TABLE "signals_signalscoutrun" ADD COLUMN IF NOT EXISTS "updated_at" timestamptz NULL;',
                    reverse_sql='ALTER TABLE "signals_signalscoutrun" DROP COLUMN IF EXISTS "updated_at";',
                ),
            ],
        ),
    ]
