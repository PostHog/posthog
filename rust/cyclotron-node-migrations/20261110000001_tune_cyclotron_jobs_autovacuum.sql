-- Every job writes several heap versions over its life (insert, dequeue, heartbeats, finish), and none
-- of them are HOT updates because each one changes an indexed column. A dequeued job leaves dead entries
-- at the due end of idx_cyclotron_jobs_dequeue, and every poll walks those entries until vacuum removes
-- them. The server-wide scale factor lets dead rows reach a large fraction of the table before vacuum
-- starts, so polls get slower between vacuums.
--
-- Vacuum starts at 5000 dead rows plus 1% of the live rows. The fixed part sets a floor for a drained
-- queue: each vacuum pass scans every index of this table in full, so without the floor a near-empty
-- queue would start a new pass after only a few dead rows. The cost delay and cost limit stay at the
-- server values, because vacuum shares CPU with the job writers.
--
-- SET (...) takes SHARE UPDATE EXCLUSIVE, which does not conflict with reads or writes. It waits behind
-- a running vacuum of this table. There is no lock_timeout, because waiting blocks no queries, and a
-- failed migration holds back every later cyclotron migration until someone runs it again.

ALTER TABLE cyclotron_jobs SET (
    autovacuum_vacuum_scale_factor = 0.01,
    autovacuum_vacuum_threshold = 5000,
    autovacuum_analyze_scale_factor = 0.02,
    autovacuum_analyze_threshold = 5000
);
