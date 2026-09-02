-- Stubs mimicking Aurora's functions with their documented column shapes, for pipeline tests.
CREATE OR REPLACE FUNCTION aurora_version() RETURNS text LANGUAGE sql AS $$ SELECT '16.4.0' $$;

CREATE OR REPLACE FUNCTION aurora_stat_wait_type() RETURNS TABLE(type_id int, type_name text) LANGUAGE sql AS $$
  VALUES (1,'LWLock'),(3,'Lock'),(6,'Client'),(10,'IO') $$;
CREATE OR REPLACE FUNCTION aurora_stat_wait_event() RETURNS TABLE(type_id int, event_id int, event_name text) LANGUAGE sql AS $$
  VALUES (1,100,'buffer_content'),(3,300,'transactionid'),(6,600,'ClientRead'),(10,1000,'XactSync') $$;
CREATE OR REPLACE FUNCTION aurora_stat_system_waits() RETURNS TABLE(type_id int, event_id int, waits bigint, wait_time bigint) LANGUAGE sql AS $$
  SELECT e.type_id, e.event_id, (extract(epoch from now())::bigint % 100000) * (e.event_id % 7 + 1), (extract(epoch from now())::bigint % 100000) * 13
  FROM aurora_stat_wait_event() e $$;
CREATE OR REPLACE FUNCTION aurora_stat_backend_waits(p int) RETURNS TABLE(type_id int, event_id int, waits bigint, wait_time bigint) LANGUAGE sql AS $$
  SELECT e.type_id, e.event_id, (p % 50)::bigint + e.event_id, (p % 50)::bigint * 10 + e.event_id FROM aurora_stat_wait_event() e $$;

CREATE OR REPLACE FUNCTION aurora_stat_get_db_commit_latency(dboid oid) RETURNS bigint LANGUAGE sql AS $$
  SELECT (extract(epoch from now())::bigint % 1000000) $$;
CREATE OR REPLACE FUNCTION aurora_stat_dml_activity(dboid oid)
  RETURNS TABLE(select_count bigint, select_latency_microsecs bigint, insert_count bigint, insert_latency_microsecs bigint,
                update_count bigint, update_latency_microsecs bigint, delete_count bigint, delete_latency_microsecs bigint)
  LANGUAGE sql AS $$ SELECT s.tup_returned, s.tup_returned*7, s.tup_inserted, s.tup_inserted*9, s.tup_updated, s.tup_updated*11, s.tup_deleted, s.tup_deleted*3
  FROM pg_stat_database s WHERE s.datid = dboid $$;

CREATE OR REPLACE FUNCTION aurora_replica_status()
  RETURNS TABLE(server_id text, session_id text, durable_lsn pg_lsn, highest_lsn_rcvd pg_lsn, current_read_lsn pg_lsn,
                cur_replay_latency_in_usec bigint, active_txns int, is_current bool, last_transport_error int,
                last_error_timestamp timestamptz, last_update_timestamp timestamptz, feedback_xmin xid, feedback_epoch int,
                replica_lag_in_msec float8, log_stream_speed_in_kib_per_second float8, log_buffer_sequence_number bigint,
                oldest_read_view_trx_id bigint, oldest_read_view_lsn pg_lsn, pending_read_ios bigint, read_ios bigint, iops int, cpu float8)
  LANGUAGE sql AS $$
  VALUES ('db-instance-1','MASTER_SESSION_ID','0/1'::pg_lsn,'0/1'::pg_lsn,'0/1'::pg_lsn,0::bigint,3,true,0,NULL::timestamptz,NULL::timestamptz,'100'::xid,0,NULL::float8,12.5::float8,1::bigint,0::bigint,'0/1'::pg_lsn,0::bigint,100::bigint,0,1.5::float8),
         ('db-instance-2','uuid-2','0/1'::pg_lsn,'0/1'::pg_lsn,'0/1'::pg_lsn,1500::bigint,1,true,0,NULL::timestamptz,now(),'100'::xid,0,13.0::float8,12.5::float8,1::bigint,0::bigint,'0/1'::pg_lsn,2::bigint,200::bigint,0,2.5::float8) $$;

CREATE OR REPLACE FUNCTION aurora_stat_memctx_usage() RETURNS TABLE(pid int, name text, allocated bigint, used bigint, instances int) LANGUAGE sql AS $$
  SELECT a.pid, c.name, c.alloc, c.alloc/2, 1 FROM pg_stat_activity a,
  LATERAL (VALUES ('CacheMemoryContext', 100*1024*1024::bigint), ('ExecutorState', 8192::bigint)) c(name, alloc)
  WHERE a.backend_type = 'client backend' $$;

CREATE OR REPLACE VIEW _aurora_stat_activity AS SELECT a.*, 424242::bigint AS plan_id FROM pg_stat_activity a;
CREATE OR REPLACE FUNCTION aurora_stat_activity() RETURNS SETOF _aurora_stat_activity LANGUAGE sql AS $$ SELECT * FROM _aurora_stat_activity $$;

CREATE OR REPLACE VIEW _aurora_stat_statements AS
  SELECT s.*, s.shared_blks_read AS storage_blks_read, 0::float8 AS orcache_blks_hit, s.blk_read_time AS storage_blk_read_time,
         0::float8 AS local_blk_read_time, 0::float8 AS orcache_blk_read_time,
         0::bigint AS total_plan_peakmem, 0::bigint AS min_plan_peakmem, 0::bigint AS max_plan_peakmem,
         (s.calls*65536)::bigint AS total_exec_peakmem, 65536::bigint AS min_exec_peakmem, 65536::bigint AS max_exec_peakmem
  FROM pg_stat_statements s;
CREATE OR REPLACE FUNCTION aurora_stat_statements(showtext bool) RETURNS SETOF _aurora_stat_statements LANGUAGE sql AS $$ SELECT * FROM _aurora_stat_statements $$;

CREATE OR REPLACE VIEW _aurora_stat_plans AS
  SELECT s.*, (s.queryid % 1000)::bigint AS planid, 'Seq Scan on t (cost=0.00..1.00)' AS explain_plan, 'estimate'::text AS plan_type, now() - interval '1 hour' AS plan_captured_time
  FROM _aurora_stat_statements s;
CREATE OR REPLACE FUNCTION aurora_stat_plans(showtext bool) RETURNS SETOF _aurora_stat_plans LANGUAGE sql AS $$ SELECT * FROM _aurora_stat_plans $$;
