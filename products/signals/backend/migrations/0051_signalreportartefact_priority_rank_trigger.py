from django.db import migrations

# Derives `priority_rank` from `content` for `priority_judgment` rows. Runs BEFORE INSERT/UPDATE so it
# wins over whatever the ORM sends (the column is DB-maintained, read-only application-side) and catches
# every writer — the model funnel, `bulk_create`, data migrations, raw SQL. The inner BEGIN/EXCEPTION makes
# a malformed-JSON `content` yield NULL instead of raising, so a bad payload can never break an artefact
# write. `OF content, type` keeps it from firing on unrelated column updates.
CREATE_TRIGGER = """
CREATE OR REPLACE FUNCTION signals_set_artefact_priority_rank() RETURNS trigger AS $$
BEGIN
    NEW.priority_rank := NULL;
    IF NEW.type = 'priority_judgment' THEN
        BEGIN
            NEW.priority_rank := CASE (NEW.content::jsonb ->> 'priority')
                WHEN 'P0' THEN 0 WHEN 'P1' THEN 1 WHEN 'P2' THEN 2 WHEN 'P3' THEN 3 WHEN 'P4' THEN 4
            END;
        EXCEPTION WHEN others THEN
            NEW.priority_rank := NULL;
        END;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER signals_artefact_priority_rank_trg
    BEFORE INSERT OR UPDATE OF content, type ON signals_signalreportartefact
    FOR EACH ROW EXECUTE FUNCTION signals_set_artefact_priority_rank();
"""

DROP_TRIGGER = """
DROP TRIGGER IF EXISTS signals_artefact_priority_rank_trg ON signals_signalreportartefact;
DROP FUNCTION IF EXISTS signals_set_artefact_priority_rank();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("signals", "0050_signalreportartefact_priority_rank"),
    ]

    operations = [
        migrations.RunSQL(sql=CREATE_TRIGGER, reverse_sql=DROP_TRIGGER),
    ]
