import { type IntegrationOwner, type Queryable, query } from './integrations'

export type IdempotencyClaim =
    /** The key is new, or its earlier use expired. The caller does the write and records the result. */
    | { status: 'claimed' }
    /** A live earlier request used the key with the same body. */
    | { status: 'replay'; integrationId: string | null }
    /** A live earlier request used the key with another body. */
    | { status: 'mismatch' }

/**
 * Claims an idempotency key in the caller's transaction. A second request with the same key
 * waits on the row lock until the first one commits or rolls back, so it never sees a half write.
 */
export async function claimIdempotencyKey(
    db: Queryable,
    deployment: string,
    owner: IntegrationOwner,
    operation: string,
    key: string,
    requestHash: Buffer
): Promise<IdempotencyClaim> {
    const claimed = await query(
        db,
        `INSERT INTO idempotency_keys (deployment, owner_type, owner_id, operation, key, request_hash)
         VALUES ($1, $2, $3, $4, $5, $6)
         ON CONFLICT (deployment, owner_type, owner_id, operation, key) DO UPDATE SET
            request_hash = EXCLUDED.request_hash,
            integration_id = NULL,
            created_at = now(),
            expires_at = now() + interval '24 hours'
         WHERE idempotency_keys.expires_at <= now()
         RETURNING key`,
        [deployment, owner.type, owner.id, operation, key, requestHash]
    )
    if (claimed.rows.length > 0) {
        return { status: 'claimed' }
    }
    const existing = await query<{ request_hash: Buffer; integration_id: string | null }>(
        db,
        `SELECT request_hash, integration_id FROM idempotency_keys
         WHERE deployment = $1 AND owner_type = $2 AND owner_id = $3 AND operation = $4 AND key = $5`,
        [deployment, owner.type, owner.id, operation, key]
    )
    const row = existing.rows[0]
    if (!row || !row.request_hash.equals(requestHash)) {
        return { status: 'mismatch' }
    }
    return { status: 'replay', integrationId: row.integration_id }
}

export async function recordIdempotencyResult(
    db: Queryable,
    deployment: string,
    owner: IntegrationOwner,
    operation: string,
    key: string,
    integrationId: string
): Promise<void> {
    await query(
        db,
        `UPDATE idempotency_keys SET integration_id = $6
         WHERE deployment = $1 AND owner_type = $2 AND owner_id = $3 AND operation = $4 AND key = $5`,
        [deployment, owner.type, owner.id, operation, key, integrationId]
    )
}

/** Deletes up to `limit` expired keys. Returns how many it deleted. */
export async function deleteExpiredIdempotencyKeys(db: Queryable, limit = 1000): Promise<number> {
    const result = await query(
        db,
        `DELETE FROM idempotency_keys WHERE ctid IN (
            SELECT ctid FROM idempotency_keys WHERE expires_at <= now() LIMIT $1)`,
        [limit]
    )
    return result.rowCount ?? 0
}
