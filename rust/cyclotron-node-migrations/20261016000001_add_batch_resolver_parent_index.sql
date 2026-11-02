-- no-transaction
-- A realtime cohort's ready callback looks up the batch resolver of one batch run. A workflow can hold a
-- large backlog of invocation jobs, so a partial index keeps that lookup to the resolver rows instead of
-- scanning the workflow's jobs through the function_id index.
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_cyclotron_jobs_batch_resolver_parent_run
    ON cyclotron_jobs (team_id, parent_run_id)
    WHERE queue_name = 'hogflow_batch_resolve';
