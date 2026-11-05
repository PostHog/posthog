from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("signals", "0235_signalspend_is_private")]

    operations = [
        migrations.RunSQL(
            sql="""
                CREATE OR REPLACE FUNCTION signals_snapshot_spend_visibility() RETURNS trigger AS $$
                BEGIN
                    IF TG_OP = 'UPDATE' AND OLD.is_private IS NOT NULL
                        AND OLD.scout_run_id IS NOT DISTINCT FROM NEW.scout_run_id
                        AND OLD.team_id = NEW.team_id THEN
                        NEW.is_private := OLD.is_private;
                    ELSIF NEW.scout_run_id IS NULL THEN
                        NEW.is_private := false;
                    ELSE
                        SELECT COALESCE(metadata, '{}'::jsonb) ? 'scout_trial'
                        INTO NEW.is_private
                        FROM signals_signalscoutrun
                        WHERE id = NEW.scout_run_id AND team_id = NEW.team_id;
                    END IF;
                    RETURN NEW;
                END;
                $$ LANGUAGE plpgsql;

                CREATE OR REPLACE TRIGGER signals_snapshot_spend_visibility
                BEFORE INSERT OR UPDATE OF scout_run_id, team_id, is_private ON signals_signalspend
                FOR EACH ROW EXECUTE FUNCTION signals_snapshot_spend_visibility();
            """,
            reverse_sql="""
                DROP TRIGGER IF EXISTS signals_snapshot_spend_visibility ON signals_signalspend;
                DROP FUNCTION IF EXISTS signals_snapshot_spend_visibility();
            """,
        ),
    ]
