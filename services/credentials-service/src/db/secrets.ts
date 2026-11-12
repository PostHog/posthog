// Queries over `integration_secrets`. A secret row has no owner column, so every read joins the
// live `integrations` row and binds its owner.

import type { SealedSecret } from '../crypto/envelope'
import { type IntegrationOwner, type Queryable, query } from './integrations'

export interface StoredSecret {
    integrationId: string
    sealed: SealedSecret
    /** Keys of a migrated blob that could not be decrypted. They are not in the sealed blob. */
    legacyUnreadableKeys: string[]
}

interface DbSecretRow {
    integration_id: string
    key_id: string
    wrapped_dek: Buffer
    ciphertext: Buffer
    nonce: Buffer
    enc_version: number
    legacy_unreadable_keys: string[]
}

function toStoredSecret(row: DbSecretRow): StoredSecret {
    return {
        integrationId: row.integration_id,
        sealed: {
            keyId: row.key_id,
            wrappedKey: row.wrapped_dek,
            ciphertext: row.ciphertext,
            nonce: row.nonce,
            encVersion: row.enc_version,
        },
        legacyUnreadableKeys: row.legacy_unreadable_keys,
    }
}

/** The secrets of the given live rows of the owner, by integration id. A row with no secret is absent. */
export async function getSecrets(
    db: Queryable,
    owner: IntegrationOwner,
    integrationIds: readonly string[]
): Promise<Map<string, StoredSecret>> {
    if (integrationIds.length === 0) {
        return new Map()
    }
    const result = await query<DbSecretRow>(
        db,
        `SELECT s.integration_id, s.key_id, s.wrapped_dek, s.ciphertext, s.nonce, s.enc_version, s.legacy_unreadable_keys
         FROM integration_secrets s
         JOIN integrations i ON i.id = s.integration_id
         WHERE i.owner_type = $1 AND i.owner_id = $2 AND i.deleted_at IS NULL AND s.integration_id = ANY($3::uuid[])`,
        [owner.type, owner.id, integrationIds]
    )
    return new Map(result.rows.map((row) => [row.integration_id, toStoredSecret(row)]))
}

/**
 * Stores the sealed blob of a row and replaces any blob it had. Call it only in the transaction
 * that read or locked the row for its owner.
 */
export async function putSecret(
    db: Queryable,
    integrationId: string,
    sealed: SealedSecret,
    legacyUnreadableKeys: readonly string[] = []
): Promise<void> {
    await query(
        db,
        `INSERT INTO integration_secrets
            (integration_id, key_id, wrapped_dek, ciphertext, nonce, enc_version, legacy_unreadable_keys)
         VALUES ($1, $2, $3, $4, $5, $6, $7)
         ON CONFLICT (integration_id) DO UPDATE SET
            key_id = EXCLUDED.key_id,
            wrapped_dek = EXCLUDED.wrapped_dek,
            ciphertext = EXCLUDED.ciphertext,
            nonce = EXCLUDED.nonce,
            enc_version = EXCLUDED.enc_version,
            legacy_unreadable_keys = EXCLUDED.legacy_unreadable_keys,
            rewrapped_at = NULL,
            updated_at = now()`,
        [
            integrationId,
            sealed.keyId,
            sealed.wrappedKey,
            sealed.ciphertext,
            sealed.nonce,
            sealed.encVersion,
            legacyUnreadableKeys,
        ]
    )
}

/** Removes the blob of a row. Same transaction rule as `putSecret`. */
export async function deleteSecret(db: Queryable, integrationId: string): Promise<void> {
    await query(db, 'DELETE FROM integration_secrets WHERE integration_id = $1', [integrationId])
}

/** Removes the blobs of many rows. Same transaction rule as `putSecret`. */
export async function deleteSecrets(db: Queryable, integrationIds: readonly string[]): Promise<void> {
    if (integrationIds.length === 0) {
        return
    }
    await query(db, 'DELETE FROM integration_secrets WHERE integration_id = ANY($1::uuid[])', [integrationIds])
}

/**
 * The current secrets of the given rows, whatever their owner. A row without a secret is absent.
 * Only the change feed may call it: it does not bind an owner.
 */
export async function getSecretsOf(
    db: Queryable,
    integrationIds: readonly string[]
): Promise<Map<string, StoredSecret>> {
    if (integrationIds.length === 0) {
        return new Map()
    }
    const result = await query<DbSecretRow>(
        db,
        `SELECT integration_id, key_id, wrapped_dek, ciphertext, nonce, enc_version, legacy_unreadable_keys
         FROM integration_secrets
         WHERE integration_id = ANY($1::uuid[])`,
        [integrationIds]
    )
    return new Map(result.rows.map((row) => [row.integration_id, toStoredSecret(row)]))
}
