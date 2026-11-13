// Typed queries over the `integrations` table. Every statement binds the owner, so no query here
// can read or change another team's row.

import { DatabaseError, Pool, type PoolClient, type QueryResult, type QueryResultRow } from 'pg'

/** A pool, or a client inside a transaction. */
export type Queryable = Pool | PoolClient

export type OwnerType = 'team'

export interface IntegrationOwner {
    type: OwnerType
    id: number
}

/**
 * A reference to one row: the UUID primary key, or the int id of the Django row it came from.
 * The string form is the one `posthog/integrations/references.py` writes.
 */
export type IntegrationRef = { id: string } | { legacyId: number }

export type RefreshState = 'idle' | 'backoff' | 'terminal'

export interface IntegrationRow {
    id: string
    legacyId: number | null
    ownerType: OwnerType
    ownerId: number
    kind: string
    externalId: string | null
    authType: string
    isSourceRow: boolean
    config: Record<string, unknown>
    errors: string
    createdById: number | null
    createdAt: Date
    updatedAt: Date
    version: number
    deletedAt: Date | null
    refreshDueAt: Date | null
    refreshState: RefreshState
    refreshAttempts: number
    refreshLastError: string | null
    refreshLockedUntil: Date | null
}

export interface NewIntegration {
    /** Set when the caller needs the id before the insert, for example to seal the secret first. */
    id?: string
    owner: IntegrationOwner
    kind: string
    externalId: string | null
    authType: string
    config?: Record<string, unknown>
    errors?: string
    isSourceRow?: boolean
    createdById?: number | null
    legacyId?: number | null
}

/** The fields an update may change. A field that is not set keeps its value. */
export interface IntegrationChanges {
    externalId?: string | null
    authType?: string
    config?: Record<string, unknown>
    errors?: string
    isSourceRow?: boolean
    createdById?: number | null
}

export type InsertResult = { status: 'ok'; row: IntegrationRow } | { status: 'conflict' }

export type WriteResult =
    | { status: 'ok'; row: IntegrationRow }
    | { status: 'not_found' }
    | { status: 'version_mismatch'; currentVersion: number }
    | { status: 'conflict' }

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/
const LEGACY_ID = /^(0|[1-9]\d*)$/
const UNIQUE_VIOLATION = '23505'
const LIVE_UNIQUE_INDEX = 'integrations_owner_kind_external_id_live'

/**
 * Reads the stored string form of a reference. Only the canonical forms parse, the same as
 * `IntegrationReference.parse`: ASCII digits with no leading zero, or a lowercase hyphenated UUID.
 */
export function parseIntegrationRef(value: string): IntegrationRef | null {
    if (LEGACY_ID.test(value)) {
        const legacyId = Number(value)
        return Number.isSafeInteger(legacyId) ? { legacyId } : null
    }
    return UUID.test(value) ? { id: value } : null
}

export function formatIntegrationRef(ref: IntegrationRef): string {
    return 'id' in ref ? ref.id : String(ref.legacyId)
}

export const COLUMNS = `
    id, legacy_id, owner_type, owner_id, kind, external_id, auth_type, is_source_row, config, errors,
    created_by_id, created_at, updated_at, version, deleted_at, refresh_due_at, refresh_state,
    refresh_attempts, refresh_last_error, refresh_locked_until`

export interface DbRow {
    id: string
    legacy_id: string | null
    owner_type: OwnerType
    owner_id: string
    kind: string
    external_id: string | null
    auth_type: string
    is_source_row: boolean
    config: Record<string, unknown>
    errors: string
    created_by_id: string | null
    created_at: Date
    updated_at: Date
    version: number
    deleted_at: Date | null
    refresh_due_at: Date | null
    refresh_state: RefreshState
    refresh_attempts: number
    refresh_last_error: string | null
    refresh_locked_until: Date | null
}

// pg returns bigint as a string, because a bigint can be larger than a JS number holds exactly.
function toInt(value: string): number {
    const parsed = Number(value)
    if (!Number.isSafeInteger(parsed)) {
        throw new Error(`bigint ${value} is outside the safe integer range`)
    }
    return parsed
}

export function toRow(row: DbRow): IntegrationRow {
    return {
        id: row.id,
        legacyId: row.legacy_id === null ? null : toInt(row.legacy_id),
        ownerType: row.owner_type,
        ownerId: toInt(row.owner_id),
        kind: row.kind,
        externalId: row.external_id,
        authType: row.auth_type,
        isSourceRow: row.is_source_row,
        config: row.config,
        errors: row.errors,
        createdById: row.created_by_id === null ? null : toInt(row.created_by_id),
        createdAt: row.created_at,
        updatedAt: row.updated_at,
        version: row.version,
        deletedAt: row.deleted_at,
        refreshDueAt: row.refresh_due_at,
        refreshState: row.refresh_state,
        refreshAttempts: row.refresh_attempts,
        refreshLastError: row.refresh_last_error,
        refreshLockedUntil: row.refresh_locked_until,
    }
}

/** The WHERE clause for one live row of one owner. Placeholders $1 to $3 are `refValues`. */
function refCondition(ref: IntegrationRef): string {
    const column = 'id' in ref ? 'id = $3::uuid' : 'legacy_id = $3'
    return `owner_type = $1 AND owner_id = $2 AND ${column} AND deleted_at IS NULL`
}

function refValues(owner: IntegrationOwner, ref: IntegrationRef): unknown[] {
    return [owner.type, owner.id, 'id' in ref ? ref.id : ref.legacyId]
}

// Both types have many `query` overloads, so TypeScript cannot call `query` on the union. Narrow first.
export function query<R extends QueryResultRow>(
    db: Queryable,
    text: string,
    values: unknown[]
): Promise<QueryResult<R>> {
    return db instanceof Pool ? db.query<R>(text, values) : db.query<R>(text, values)
}

// legacy_id stays unique across owners and soft-deleted rows, so reusing one is a conflict too.
const LEGACY_ID_UNIQUE = 'integrations_legacy_id_key'

function isLiveUniqueViolation(err: unknown): boolean {
    return (
        err instanceof DatabaseError &&
        err.code === UNIQUE_VIOLATION &&
        (err.constraint === LIVE_UNIQUE_INDEX || err.constraint === LEGACY_ID_UNIQUE)
    )
}

/** A live row of the owner, or null. A soft-deleted row and another owner's row read as null. */
export async function getIntegration(
    db: Queryable,
    owner: IntegrationOwner,
    ref: IntegrationRef
): Promise<IntegrationRow | null> {
    const result = await query<DbRow>(
        db,
        `SELECT ${COLUMNS} FROM integrations WHERE ${refCondition(ref)}`,
        refValues(owner, ref)
    )
    const row = result.rows[0]
    return row ? toRow(row) : null
}

export async function insertIntegration(db: Queryable, input: NewIntegration): Promise<InsertResult> {
    try {
        const result = await query<DbRow>(
            db,
            `INSERT INTO integrations
                (id, owner_type, owner_id, kind, external_id, auth_type, config, errors, is_source_row, created_by_id, legacy_id)
             VALUES (COALESCE($11::uuid, gen_random_uuid()), $1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
             RETURNING ${COLUMNS}`,
            [
                input.owner.type,
                input.owner.id,
                input.kind,
                input.externalId,
                input.authType,
                input.config ?? {},
                input.errors ?? '',
                input.isSourceRow ?? false,
                input.createdById ?? null,
                input.legacyId ?? null,
                input.id ?? null,
            ]
        )
        return { status: 'ok', row: toRow(result.rows[0] as DbRow) }
    } catch (err) {
        if (isLiveUniqueViolation(err)) {
            return { status: 'conflict' }
        }
        throw err
    }
}

// Static column names only: a key of IntegrationChanges never reaches the SQL text.
const CHANGE_COLUMNS: { [K in keyof Required<IntegrationChanges>]: string } = {
    externalId: 'external_id',
    authType: 'auth_type',
    config: 'config',
    errors: 'errors',
    isSourceRow: 'is_source_row',
    createdById: 'created_by_id',
}

/**
 * Changes a live row only when its version is still `expectedVersion`, and bumps the version.
 * A stale version returns `version_mismatch` with the current version, so the caller can reread.
 */
export async function updateIntegration(
    db: Queryable,
    owner: IntegrationOwner,
    ref: IntegrationRef,
    expectedVersion: number,
    changes: IntegrationChanges
): Promise<WriteResult> {
    const values = refValues(owner, ref)
    values.push(expectedVersion)
    const assignments = ['version = version + 1', 'updated_at = now()']
    for (const key of Object.keys(CHANGE_COLUMNS) as (keyof IntegrationChanges)[]) {
        const value = changes[key]
        if (value !== undefined) {
            values.push(value)
            assignments.push(`${CHANGE_COLUMNS[key]} = $${values.length}`)
        }
    }
    return writeWithVersion(
        db,
        owner,
        ref,
        `UPDATE integrations SET ${assignments.join(', ')}
         WHERE ${refCondition(ref)} AND version = $4
         RETURNING ${COLUMNS}`,
        values
    )
}

/**
 * Marks a live row deleted. The row stays for the audit trail, and the unique index stops
 * covering it, so a new row with the same external id can follow. With `expectedVersion`, a
 * stale version returns `version_mismatch`.
 */
export async function softDeleteIntegration(
    db: Queryable,
    owner: IntegrationOwner,
    ref: IntegrationRef,
    options: { expectedVersion?: number } = {}
): Promise<WriteResult> {
    return writeWithVersion(
        db,
        owner,
        ref,
        `UPDATE integrations SET deleted_at = now(), updated_at = now(), version = version + 1
         WHERE ${refCondition(ref)} AND ($4::integer IS NULL OR version = $4)
         RETURNING ${COLUMNS}`,
        [...refValues(owner, ref), options.expectedVersion ?? null]
    )
}

async function writeWithVersion(
    db: Queryable,
    owner: IntegrationOwner,
    ref: IntegrationRef,
    sql: string,
    values: unknown[]
): Promise<WriteResult> {
    let result: QueryResult<DbRow>
    try {
        result = await query<DbRow>(db, sql, values)
    } catch (err) {
        if (isLiveUniqueViolation(err)) {
            return { status: 'conflict' }
        }
        throw err
    }
    const row = result.rows[0]
    if (row) {
        return { status: 'ok', row: toRow(row) }
    }
    // No row changed: the row is gone, or its version moved on. Tell the two apart.
    const current = await getIntegration(db, owner, ref)
    return current ? { status: 'version_mismatch', currentVersion: current.version } : { status: 'not_found' }
}
