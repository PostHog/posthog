// Queries for `PUT /v1/integrations/mirror`, which copies Django rows keyed by their int id, and
// for `POST /v1/integrations/mirror/purge`, which hard-deletes those copies on rollback.
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

/** Replaces every mirrored field of a locked live row of the owner. The refresh columns keep their values. */
export async function replaceMirrored(
    db: Queryable,
    owner: IntegrationOwner,
    id: string,
    fields: MirrorFields
): Promise<MirrorWriteResult> {
    return writeRow(
        db,
        `UPDATE integrations SET
            kind = $2, external_id = $3, auth_type = $4, is_source_row = $5, config = $6, errors = $7,
            created_by_id = $8, created_at = $9::timestamptz, source_version = $10,
            version = version + 1, updated_at = now()
         WHERE id = $1 AND owner_type = $11 AND owner_id = $12 AND deleted_at IS NULL
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
            owner.type,
            owner.id,
        ]
    )
}

/** Soft-deletes a locked live row of the owner. The stored source version never goes down. */
export async function softDeleteMirrored(
    db: Queryable,
    owner: IntegrationOwner,
    id: string,
    sourceVersion: number | null
): Promise<MirrorWriteResult> {
    return writeRow(
        db,
        `UPDATE integrations SET
            deleted_at = now(), updated_at = now(), version = version + 1,
            source_version = GREATEST($2::bigint, source_version)
         WHERE id = $1 AND owner_type = $3 AND owner_id = $4 AND deleted_at IS NULL
         RETURNING ${MIRROR_COLUMNS}`,
        [id, sourceVersion, owner.type, owner.id]
    )
}

/** A row the mirror wrote: it has a legacy id and a source version. */
export interface MirrorOwnedRow {
    id: string
    legacyId: number
    sourceVersion: number
    ownerType: string
    ownerId: number
    kind: string
}

export interface MirrorPurgeFilter {
    kind: string
    afterLegacyId: number | null
    limit: number
    /** Null matches every owner. */
    teamIds: readonly number[] | null
    /** False leaves warehouse source rows alone. */
    sourceRows: boolean
}

interface MirrorOwnedDbRow {
    id: string
    legacy_id: string
    source_version: string
    owner_type: string
    owner_id: string
    kind: string
}

function toMirrorOwnedRow(row: MirrorOwnedDbRow): MirrorOwnedRow {
    return {
        id: row.id,
        legacyId: Number(row.legacy_id),
        sourceVersion: Number(row.source_version),
        ownerType: row.owner_type,
        ownerId: Number(row.owner_id),
        kind: row.kind,
    }
}

const MIRROR_OWNED_COLUMNS = 'id, legacy_id, source_version, owner_type, owner_id, kind'

/**
 * One keyset page of the rows the mirror wrote for a kind, live or tombstoned, in legacy id
 * order. `lock` takes a row lock on each, so a concurrent mirror write waits for the purge.
 * A row the service created itself has no source version and never matches.
 */
export async function listMirrorOwned(
    db: Queryable,
    filter: MirrorPurgeFilter,
    lock: boolean
): Promise<MirrorOwnedRow[]> {
    const result = await query<MirrorOwnedDbRow>(
        db,
        `SELECT ${MIRROR_OWNED_COLUMNS} FROM integrations
         WHERE kind = $1 AND legacy_id IS NOT NULL AND source_version IS NOT NULL
           AND ($2::bigint IS NULL OR legacy_id > $2::bigint)
           AND ($3::bigint[] IS NULL OR (owner_type = 'team' AND owner_id = ANY($3::bigint[])))
           AND ($4::boolean OR NOT is_source_row)
         ORDER BY legacy_id
         LIMIT $5
         ${lock ? 'FOR UPDATE' : ''}`,
        [filter.kind, filter.afterLegacyId, filter.teamIds, filter.sourceRows, filter.limit]
    )
    return result.rows.map(toMirrorOwnedRow)
}

/** Hard-deletes locked mirror rows and their secrets. Returns the rows it deleted. */
export async function hardDeleteMirrorOwned(db: Queryable, ids: readonly string[]): Promise<MirrorOwnedRow[]> {
    if (ids.length === 0) {
        return []
    }
    await query(db, 'DELETE FROM integration_secrets WHERE integration_id = ANY($1::uuid[])', [ids])
    const result = await query<MirrorOwnedDbRow>(
        db,
        `DELETE FROM integrations
         WHERE id = ANY($1::uuid[]) AND legacy_id IS NOT NULL AND source_version IS NOT NULL
         RETURNING ${MIRROR_OWNED_COLUMNS}`,
        [ids]
    )
    return result.rows.map(toMirrorOwnedRow).sort((a, b) => a.legacyId - b.legacyId)
}
