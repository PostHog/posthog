// Queries for `PUT /v1/integrations/mirror`, which copies Django rows keyed by their int id.
// The lookups by legacy id bind no owner: legacy ids are unique across owners, and the service
// compares the owner in code so that it can answer `owner_mismatch` instead of inserting.

import { DatabaseError } from 'pg'

import {
    COLUMNS,
    type DbRow,
    type IntegrationOwner,
    type IntegrationRow,
    type Queryable,
    query,
    toRow,
} from './integrations'

export interface MirrorRow extends IntegrationRow {
    sourceVersion: number | null
}

export interface MirrorFields {
    kind: string
    externalId: string | null
    authType: string
    isSourceRow: boolean
    config: Record<string, unknown>
    errors: string
    createdById: number | null
    createdAt: string
    sourceVersion: number
}

export interface MirrorInsert extends Omit<MirrorFields, 'createdAt' | 'sourceVersion'> {
    id: string
    owner: IntegrationOwner
    legacyId: number
    deleted: boolean
    /** Null stores the insert time. */
    createdAt: string | null
    sourceVersion: number | null
}

/** `key_taken`: a live row of the owner has the same (kind, external id). `legacy_id_taken`: a concurrent insert won. */
export type MirrorWriteResult =
    | { status: 'ok'; row: MirrorRow }
    | { status: 'key_taken' }
    | { status: 'legacy_id_taken' }

const UNIQUE_VIOLATION = '23505'
const LIVE_UNIQUE_INDEX = 'integrations_owner_kind_external_id_live'
const LEGACY_ID_UNIQUE = 'integrations_legacy_id_key'
const MIRROR_COLUMNS = `${COLUMNS}, source_version`

interface MirrorDbRow extends DbRow {
    source_version: string | null
}

function toMirrorRow(row: MirrorDbRow): MirrorRow {
    const sourceVersion = row.source_version === null ? null : Number(row.source_version)
    if (sourceVersion !== null && !Number.isSafeInteger(sourceVersion)) {
        throw new Error(`source_version ${row.source_version} is outside the safe integer range`)
    }
    return { ...toRow(row), sourceVersion }
}

async function writeRow(db: Queryable, sql: string, values: unknown[]): Promise<MirrorWriteResult> {
    try {
        const result = await query<MirrorDbRow>(db, sql, values)
        const row = result.rows[0]
        if (!row) {
            throw new Error('mirror write changed no row')
        }
        return { status: 'ok', row: toMirrorRow(row) }
    } catch (err) {
        if (err instanceof DatabaseError && err.code === UNIQUE_VIOLATION) {
            if (err.constraint === LIVE_UNIQUE_INDEX) {
                return { status: 'key_taken' }
            }
            if (err.constraint === LEGACY_ID_UNIQUE) {
                return { status: 'legacy_id_taken' }
            }
        }
        throw err
    }
}

/** The row with this legacy id, live or deleted, of any owner. */
export async function getByLegacyId(db: Queryable, legacyId: number): Promise<MirrorRow | null> {
    const result = await query<MirrorDbRow>(db, `SELECT ${MIRROR_COLUMNS} FROM integrations WHERE legacy_id = $1`, [
        legacyId,
    ])
    const row = result.rows[0]
    return row ? toMirrorRow(row) : null
}

/** The same as `getByLegacyId`, and locks the row until the transaction ends. */
export async function lockByLegacyId(db: Queryable, legacyId: number): Promise<MirrorRow | null> {
    const result = await query<MirrorDbRow>(
        db,
        `SELECT ${MIRROR_COLUMNS} FROM integrations WHERE legacy_id = $1 FOR UPDATE`,
        [legacyId]
    )
    const row = result.rows[0]
    return row ? toMirrorRow(row) : null
}

/** The legacy id of another live row of the owner with this (kind, external id), or undefined when there is none. */
export async function findKeyHolder(
    db: Queryable,
    owner: IntegrationOwner,
    kind: string,
    externalId: string,
    exceptId: string | null
): Promise<{ legacyId: number | null } | undefined> {
    const result = await query<{ legacy_id: string | null }>(
        db,
        `SELECT legacy_id FROM integrations
         WHERE owner_type = $1 AND owner_id = $2 AND kind = $3 AND external_id = $4 AND deleted_at IS NULL
           AND ($5::uuid IS NULL OR id <> $5::uuid)
         LIMIT 1`,
        [owner.type, owner.id, kind, externalId, exceptId]
    )
    const row = result.rows[0]
    if (!row) {
        return undefined
    }
    return { legacyId: row.legacy_id === null ? null : Number(row.legacy_id) }
}

/** Inserts a mirrored row. A `deleted` row is a tombstone: it holds the legacy id so an older upsert cannot revive it. */
export async function insertMirrored(db: Queryable, input: MirrorInsert): Promise<MirrorWriteResult> {
    return writeRow(
        db,
        `INSERT INTO integrations
            (id, owner_type, owner_id, legacy_id, kind, external_id, auth_type, is_source_row, config, errors,
             created_by_id, created_at, source_version, deleted_at)
         VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, COALESCE($12::timestamptz, now()), $13,
                 CASE WHEN $14::boolean THEN now() END)
         RETURNING ${MIRROR_COLUMNS}`,
        [
            input.id,
            input.owner.type,
            input.owner.id,
            input.legacyId,
            input.kind,
            input.externalId,
            input.authType,
            input.isSourceRow,
            input.config,
            input.errors,
            input.createdById,
            input.createdAt,
            input.sourceVersion,
            input.deleted,
        ]
    )
}

/** Replaces every mirrored field of a locked live row. The refresh columns keep their values. */
export async function replaceMirrored(db: Queryable, id: string, fields: MirrorFields): Promise<MirrorWriteResult> {
    return writeRow(
        db,
        `UPDATE integrations SET
            kind = $2, external_id = $3, auth_type = $4, is_source_row = $5, config = $6, errors = $7,
            created_by_id = $8, created_at = $9::timestamptz, source_version = $10,
            version = version + 1, updated_at = now()
         WHERE id = $1 AND deleted_at IS NULL
         RETURNING ${MIRROR_COLUMNS}`,
        [
            id,
            fields.kind,
            fields.externalId,
            fields.authType,
            fields.isSourceRow,
            fields.config,
            fields.errors,
            fields.createdById,
            fields.createdAt,
            fields.sourceVersion,
        ]
    )
}

/** Soft-deletes a locked live row. A null `sourceVersion` keeps the stored one. */
export async function softDeleteMirrored(
    db: Queryable,
    id: string,
    sourceVersion: number | null
): Promise<MirrorWriteResult> {
    return writeRow(
        db,
        `UPDATE integrations SET
            deleted_at = now(), updated_at = now(), version = version + 1,
            source_version = COALESCE($2, source_version)
         WHERE id = $1 AND deleted_at IS NULL
         RETURNING ${MIRROR_COLUMNS}`,
        [id, sourceVersion]
    )
}
