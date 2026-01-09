-- Backup table for person property reconciliation job
-- Stores original person state before updates for audit/rollback

CREATE TABLE IF NOT EXISTS posthog_person_reconciliation_backup (
    job_id TEXT NOT NULL,
    team_id INTEGER NOT NULL,
    person_id BIGINT NOT NULL,
    -- Full row backup of posthog_person columns (BEFORE state)
    uuid UUID NOT NULL,
    properties JSONB NOT NULL,
    properties_last_updated_at JSONB,
    properties_last_operation JSONB,
    version BIGINT,
    is_identified BOOLEAN NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    is_user_id INTEGER,
    -- Operations to be applied (from ClickHouse query)
    pending_operations JSONB NOT NULL,
    -- AFTER state (computed before update)
    properties_after JSONB,
    properties_last_updated_at_after JSONB,
    properties_last_operation_after JSONB,
    version_after BIGINT,
    -- Metadata
    backed_up_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    PRIMARY KEY (job_id, team_id, person_id)
);

CREATE INDEX IF NOT EXISTS person_reconciliation_backup_team_person
    ON posthog_person_reconciliation_backup (team_id, person_id);
