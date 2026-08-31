from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("subscriptions", "0004_pulse_outcome_loop"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                -- migration-analyzer: safe reason=This defines a trigger; BEFORE UPDATE is event syntax and performs no data mutation.
                CREATE OR REPLACE FUNCTION subscriptions_outcome_observation_immutable()
                RETURNS trigger AS $$
                BEGIN
                    RAISE EXCEPTION 'Outcome observations are immutable';
                END;
                $$ LANGUAGE plpgsql;

                CREATE OR REPLACE TRIGGER subscriptions_outcome_observation_immutable
                BEFORE UPDATE ON subscriptions_outcomeobservation
                FOR EACH ROW EXECUTE FUNCTION subscriptions_outcome_observation_immutable();
            """,
            reverse_sql="""
                DROP TRIGGER IF EXISTS subscriptions_outcome_observation_immutable
                ON subscriptions_outcomeobservation;
                DROP FUNCTION IF EXISTS subscriptions_outcome_observation_immutable();
            """,
        ),
    ]
