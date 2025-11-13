-- Add partitioned person table
-- This creates a new person table partitioned by team_id using hash partitioning

CREATE TABLE IF NOT EXISTS posthog_person_new (
    LIKE posthog_person INCLUDING DEFAULTS
) PARTITION BY HASH (team_id);

-- Add primary key constraint that includes the partition key
ALTER TABLE posthog_person_new
    ADD CONSTRAINT posthog_person_new_pkey PRIMARY KEY (team_id, id);

-- Create index on uuid - must include team_id for partitioning
CREATE UNIQUE INDEX IF NOT EXISTS posthog_person_new_uuid_idx ON posthog_person_new (team_id, uuid);

-- Create 64 hash partitions
DO $$
DECLARE
    num_partitions INTEGER := 64;
    i INTEGER;
BEGIN
    FOR i IN 0..(num_partitions - 1) LOOP
        EXECUTE format(
            'CREATE TABLE IF NOT EXISTS posthog_person_p%s PARTITION OF posthog_person_new FOR VALUES WITH (MODULUS %s, REMAINDER %s)',
            i, num_partitions, i
        );
    END LOOP;
END $$;

CREATE TABLE posthog_person_deletes_log (
      id BIGINT NOT NULL,
      deleted_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
      team_id INTEGER NOT NULL,
      uuid UUID NOT NULL,
      created_at TIMESTAMP WITH TIME ZONE,
      version BIGINT,
      PRIMARY KEY (id, deleted_at)
  );

CREATE INDEX idx_person_deletes_log_deleted_at ON posthog_person_deletes_log(deleted_at);
CREATE INDEX idx_person_deletes_log_team_id ON posthog_person_deletes_log(team_id);


-- Trigger function to replicate writes from posthog_person to posthog_person_new
CREATE OR REPLACE FUNCTION replicate_person_writes()
RETURNS TRIGGER AS $$
BEGIN
    IF (TG_OP = 'DELETE') THEN
        DELETE FROM posthog_person_new WHERE id = OLD.id;
        RETURN OLD;
    ELSE
        -- Handle both INSERT and UPDATE
        INSERT INTO posthog_person_new VALUES (NEW.*)
        ON CONFLICT (team_id, id) DO UPDATE SET
            created_at = EXCLUDED.created_at,
            properties = EXCLUDED.properties,
            is_user_id = EXCLUDED.is_user_id,
            is_identified = EXCLUDED.is_identified,
            uuid = EXCLUDED.uuid,
            properties_last_updated_at = EXCLUDED.properties_last_updated_at,
            properties_last_operation = EXCLUDED.properties_last_operation,
            version = EXCLUDED.version;
        RETURN NEW;
    END IF;
END;
$$ LANGUAGE plpgsql;

-- Delete logging trigger function
CREATE OR REPLACE FUNCTION log_person_deletes()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO posthog_person_deletes_log (id, team_id, uuid, created_at, version)
    VALUES (OLD.id, OLD.team_id, OLD.uuid, OLD.created_at, OLD.version)
    ON CONFLICT (id, deleted_at) DO NOTHING;
    RETURN OLD;
END;
$$ LANGUAGE plpgsql;

-- Create trigger to replicate writes from posthog_person to posthog_person_new
CREATE TRIGGER replicate_person_trigger
    AFTER INSERT OR UPDATE OR DELETE ON posthog_person
    FOR EACH ROW EXECUTE FUNCTION replicate_person_writes();

-- Create trigger to log deletes from posthog_person
CREATE TRIGGER log_person_deletes_trigger
    AFTER DELETE ON posthog_person
    FOR EACH ROW EXECUTE FUNCTION log_person_deletes();
