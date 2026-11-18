-- Up Migration

-- A key belongs to one (deployment, owner, operation), so two deployments can never collide on, or replay, each other's keys.
ALTER TABLE idempotency_keys ADD COLUMN deployment text NOT NULL DEFAULT '';
ALTER TABLE idempotency_keys ALTER COLUMN deployment DROP DEFAULT;
ALTER TABLE idempotency_keys DROP CONSTRAINT idempotency_keys_pkey;
ALTER TABLE idempotency_keys ADD PRIMARY KEY (deployment, owner_type, owner_id, operation, key);

-- Down Migration

ALTER TABLE idempotency_keys DROP CONSTRAINT idempotency_keys_pkey;
ALTER TABLE idempotency_keys DROP COLUMN deployment;
ALTER TABLE idempotency_keys ADD PRIMARY KEY (owner_type, owner_id, operation, key);
