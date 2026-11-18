-- A workflow conversion goal has to stay observable after the run that enrolled the person has
-- finished. The run's cyclotron job is gone by then, so the subscription matcher's parked-job lookup
-- cannot reach it, and every conversion landing after the last step is invisible. For a workflow with
-- no delay step that is every conversion it will ever have.
--
-- A watcher is one row per enrolled run, outliving the run itself, that the matcher evaluates the
-- goal against. It is deliberately NOT a cyclotron_jobs row: it is never dequeued, executed, retried
-- or woken, so status, queue_name, priority, vm_state and the janitor would all need per-row
-- exemptions, and a watcher accidentally scheduled onto a queue nothing consumes becomes permanent
-- cdp_cyclotron_v2_queue_depth backlog that CDP KEDA scales on.
--
-- Deleting the row IS the claim: a conversion is counted by DELETE ... RETURNING, so exactly one
-- caller can win it and a counted watcher stops being scanned in the same statement. That removes the
-- need for a counted_at flag, a SELECT ... FOR UPDATE, and any state parsing.
CREATE TABLE IF NOT EXISTS conversion_watchers (
    id UUID PRIMARY KEY,
    team_id INT NOT NULL,
    -- The hog flow, matching cyclotron_jobs.function_id so metrics attribute the same way.
    function_id UUID NOT NULL,
    -- The invocation that enrolled, joining this watcher's conversion to that run's enrollment event.
    run_id UUID NOT NULL,
    -- Batch children attribute their metrics to the parent batch job, as the executor does.
    parent_run_id UUID,
    distinct_id TEXT,
    person_id TEXT,
    -- Watermark for person_id. Merge repoints are not Kafka-keyed, so a chain (anon -> A -> B) can
    -- arrive out of order and across batches; without a persisted high-water mark a late lower-version
    -- repoint would rewind the anchor and the (team_id, person_id) lookup would stop resolving. -1
    -- rather than 0 so a version-0 first mapping ("this distinct_id now has a person") still applies
    -- once. A row starts unwatermarked: the enrolling run reads its person through the person store,
    -- which does not carry the version, so only re-keys move this forward.
    person_version INT NOT NULL DEFAULT -1,
    -- The version the run started under, so a per-version conversion rate divides a versioned
    -- numerator by a versioned denominator.
    flow_version INT,
    -- The compiled goal as it stood when the run enrolled: {properties?: bytecode, events?: bytecode[]}.
    -- Pinned rather than re-read from the live flow so editing a goal cannot retroactively re-judge
    -- cohorts that are already in flight under the old one.
    goal JSONB NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- The matcher looks watchers up the same two ways it looks up parked jobs: by the triggering event's
-- distinct_id, and by person_id for person-property changes that carry no distinct_id.
CREATE INDEX IF NOT EXISTS idx_conversion_watchers_distinct_id
    ON conversion_watchers (team_id, distinct_id)
    WHERE distinct_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_conversion_watchers_person_id
    ON conversion_watchers (team_id, person_id)
    WHERE person_id IS NOT NULL;

-- Drives the expiry sweep. Watchers are the only rows here that are never claimed by a conversion,
-- so without this they would accumulate for the lifetime of the table.
CREATE INDEX IF NOT EXISTS idx_conversion_watchers_expires_at
    ON conversion_watchers (expires_at);
