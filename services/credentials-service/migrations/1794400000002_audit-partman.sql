-- Up Migration

-- Daily audit_log partitions and 30-day retention through pg_partman, run hourly by pg_cron.
-- Infra creates both extensions (pg_partman in schema partman, and pg_cron) and grants
-- the migrate role what pg_partman and pg_cron need. A pg_cron job runs as the role that schedules
-- it, so the migrate role creates and owns every partition, and drops them for retention.
-- The runtime role gets no grant on a partition: for DML through audit_log, Postgres checks the
-- privileges on audit_log only.
DO $$
DECLARE
    missing text[];
    partman_version text;
BEGIN
    -- pg_cron always installs into pg_catalog. Its objects are in schema cron.
    SELECT array_agg(want.name ORDER BY want.name) INTO missing
    FROM (VALUES ('pg_partman', 'partman'), ('pg_cron', NULL)) AS want (name, schema)
    WHERE NOT EXISTS (
        SELECT 1 FROM pg_extension e JOIN pg_namespace n ON n.oid = e.extnamespace
        WHERE e.extname = want.name AND (want.schema IS NULL OR n.nspname = want.schema)
    );
    IF missing IS NOT NULL THEN
        IF current_setting('credentials_service.partman_optional', true) IS DISTINCT FROM 'on' THEN
            RAISE EXCEPTION 'audit_log retention needs pg_partman in schema partman and pg_cron; missing: %', missing
                USING HINT = 'Infra must create the extensions in this database before this migration runs.';
        END IF;
        RAISE NOTICE 'skipping pg_partman setup for audit_log: missing %', missing;
        RETURN;
    END IF;

    SELECT extversion INTO partman_version FROM pg_extension WHERE extname = 'pg_partman';
    IF split_part(partman_version, '.', 1)::int < 5 THEN
        RAISE EXCEPTION 'audit_log retention needs pg_partman 5 or later, found %', partman_version;
    END IF;

    -- create_parent takes ACCESS EXCLUSIVE on audit_log until commit, so reads and writes pause.
    -- lock_timeout bounds the wait to acquire a lock, not the pause after it is acquired.
    PERFORM set_config('lock_timeout', '10s', true);
    LOCK TABLE audit_log IN SHARE ROW EXCLUSIVE MODE;

    IF NOT EXISTS (SELECT 1 FROM partman.part_config WHERE parent_table = 'public.audit_log') THEN
        -- A row in the default partition stops pg_partman from attaching a partition for that day.
        -- The rows move out first and come back once the partitions exist.
        CREATE TEMP TABLE audit_log_pending (LIKE audit_log) ON COMMIT DROP;
        WITH moved AS (DELETE FROM audit_log_default RETURNING *)
        INSERT INTO audit_log_pending SELECT * FROM moved;

        -- The default partition exists already, so pg_partman must not make one.
        PERFORM partman.create_parent(
            p_parent_table => 'public.audit_log',
            p_control => 'occurred_at',
            p_interval => '1 day',
            p_premake => 7,
            p_default_table => false
        );

        -- A row outside the new partitions goes back to the default partition. partition_data_time
        -- makes a partition for its day and moves it there. Unlike partition_data_proc, it is a
        -- function, so it can run inside the migration transaction.
        INSERT INTO audit_log SELECT * FROM audit_log_pending;
        WHILE partman.partition_data_time('public.audit_log', p_batch_count => 1000) > 0 LOOP
        END LOOP;
    END IF;

    -- Retention also drops unexported rows. The lag alert uses their oldest age.
    UPDATE partman.part_config
    SET premake = 7, retention = '30 days', retention_keep_table = false, infinite_time_partitions = true
    WHERE parent_table = 'public.audit_log';

    EXECUTE $procedure$
        CREATE OR REPLACE PROCEDURE public.audit_log_maintenance()
        LANGUAGE plpgsql
        AS $body$
        BEGIN
            PERFORM set_config('lock_timeout', '5s', false);
            CALL partman.partition_data_proc('public.audit_log');
            CALL partman.run_maintenance_proc();
        END
        $body$
    $procedure$;

    -- Scheduling the same name again replaces the job, so a rerun does not add a second one.
    PERFORM cron.schedule('credentials-service-audit-partman', '17 * * * *', 'CALL public.audit_log_maintenance()');
END
$$;

-- Down Migration

-- Puts every row back in the default partition and removes the pg_partman and pg_cron setup.
DO $$
DECLARE
    child record;
    template regclass;
BEGIN
    IF to_regclass('cron.job') IS NOT NULL THEN
        PERFORM cron.unschedule(jobid) FROM cron.job
        WHERE jobname = 'credentials-service-audit-partman' AND username = current_user;
    END IF;
    EXECUTE 'DROP PROCEDURE IF EXISTS public.audit_log_maintenance()';
    IF to_regclass('partman.part_config') IS NULL THEN
        RETURN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM partman.part_config WHERE parent_table = 'public.audit_log') THEN
        RETURN;
    END IF;

    PERFORM set_config('lock_timeout', '10s', true);
    LOCK TABLE audit_log IN SHARE ROW EXCLUSIVE MODE;
    FOR child IN SELECT partition_schemaname, partition_tablename FROM partman.show_partitions('public.audit_log') LOOP
        EXECUTE format('ALTER TABLE audit_log DETACH PARTITION %I.%I', child.partition_schemaname, child.partition_tablename);
        EXECUTE format('INSERT INTO audit_log SELECT * FROM %I.%I', child.partition_schemaname, child.partition_tablename);
        EXECUTE format('DROP TABLE %I.%I', child.partition_schemaname, child.partition_tablename);
    END LOOP;

    SELECT to_regclass(template_table) INTO template FROM partman.part_config WHERE parent_table = 'public.audit_log';
    DELETE FROM partman.part_config WHERE parent_table = 'public.audit_log';
    IF template IS NOT NULL THEN
        EXECUTE format('DROP TABLE %s', template);
    END IF;
END
$$;
