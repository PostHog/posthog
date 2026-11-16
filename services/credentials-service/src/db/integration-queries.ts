// Reads and row locks over `integrations` for the HTTP routes. Owner-scoped queries bind the owner
// from the caller's token. Config keys and values are always bind parameters, never SQL text.

import {
    COLUMNS,
    type DbRow,
    type IntegrationOwner,
    type IntegrationRef,
    type IntegrationRow,
    type Queryable,
    query,
    toRow,
} from './integrations'

/** A value that a config key can equal. The JSON type is part of the comparison. */
export type ConfigValue = string | number | boolean | null
export type ConfigInValue = string | number | boolean

export type SourceRows = 'exclude' | 'only' | 'include'

export interface ConfigFilter {
    where: Readonly<Record<string, ConfigValue>>
    whereIn: Readonly<Record<string, readonly ConfigInValue[]>>
    /** Keys are one config key, or two joined by a dot for one nested key. */
    whereIexact: Readonly<Record<string, string>>
    hasConfigKey: string | null
}

export interface RowSelection extends ConfigFilter {
    /** Null selects every kind. An empty list selects no row. */
    kinds: readonly string[] | null
    authTypes: readonly string[] | null
    externalId: string | null
    sourceRows: SourceRows
}

export interface CrossTeamSelection extends RowSelection {
    /** Null selects every team. An empty list selects no row. */
    teamIds: readonly number[] | null
    excludeTeamIds: readonly number[]
    createdByIds: readonly number[] | null
}

/** A keyset position: the `created_at` text Postgres printed, so no precision is lost, and the id. */
export interface ListCursor {
    createdAt: string
    id: string
}

export interface PageRequest {
    limit: number
    newestFirst: boolean
    after: ListCursor | null
}

export interface Page {
    rows: IntegrationRow[]
    /** The position after the last row, or null when no more rows match. */
    next: ListCursor | null
}

// Classid of the advisory locks that serialize upserts of one key. A fixed classid keeps these
// locks apart from other users of the two-int advisory lock space.
const UPSERT_LOCK_CLASS = 0x6372_6564

/** Collects SQL conditions and their bind values. */
class Conditions {
    readonly parts: string[] = []
    readonly values: unknown[] = []

    bind(value: unknown): string {
        this.values.push(value)
        return `$${this.values.length}`
    }

    add(condition: string): void {
        this.parts.push(condition)
    }

    sql(): string {
        return this.parts.length === 0 ? 'TRUE' : this.parts.join(' AND ')
    }
}

function addSelection(conditions: Conditions, selection: RowSelection): void {
    if (selection.kinds !== null) {
        conditions.add(`kind = ANY(${conditions.bind(selection.kinds)}::text[])`)
    }
    if (selection.authTypes !== null) {
        conditions.add(`auth_type = ANY(${conditions.bind(selection.authTypes)}::text[])`)
    }
    if (selection.externalId !== null) {
        conditions.add(`external_id = ${conditions.bind(selection.externalId)}`)
    }
    if (selection.sourceRows === 'exclude') {
        conditions.add('NOT is_source_row')
    } else if (selection.sourceRows === 'only') {
        conditions.add('is_source_row')
    }
    for (const [key, value] of Object.entries(selection.where)) {
        conditions.add(`config -> ${conditions.bind(key)}::text = ${conditions.bind(JSON.stringify(value))}::jsonb`)
    }
    for (const [key, values] of Object.entries(selection.whereIn)) {
        const encoded = values.map((value) => JSON.stringify(value))
        conditions.add(`config -> ${conditions.bind(key)}::text = ANY(${conditions.bind(encoded)}::jsonb[])`)
    }
    for (const [path, text] of Object.entries(selection.whereIexact)) {
        conditions.add(
            `lower(config #>> ${conditions.bind(path.split('.'))}::text[]) = lower(${conditions.bind(text)}::text)`
        )
    }
    if (selection.hasConfigKey !== null) {
        conditions.add(`config ? ${conditions.bind(selection.hasConfigKey)}::text`)
    }
}

interface PagedDbRow extends DbRow {
    cursor_created_at: string
}

async function selectPage(db: Queryable, conditions: Conditions, page: PageRequest): Promise<Page> {
    const direction = page.newestFirst ? 'DESC' : 'ASC'
    if (page.after) {
        const comparison = page.newestFirst ? '<' : '>'
        conditions.add(
            `(created_at, id) ${comparison} (${conditions.bind(page.after.createdAt)}::timestamptz, ${conditions.bind(page.after.id)}::uuid)`
        )
    }
    // One extra row tells whether another page follows.
    const limit = conditions.bind(page.limit + 1)
    const result = await query<PagedDbRow>(
        db,
        `SELECT ${COLUMNS}, created_at::text AS cursor_created_at
         FROM integrations
         WHERE ${conditions.sql()}
         ORDER BY created_at ${direction}, id ${direction}
         LIMIT ${limit}`,
        conditions.values
    )
    const dbRows = result.rows.slice(0, page.limit)
    const last = dbRows[dbRows.length - 1]
    const next = result.rows.length > page.limit && last ? { createdAt: last.cursor_created_at, id: last.id } : null
    return { rows: dbRows.map(toRow), next }
}

/** One page of the owner's live rows that match. */
export async function listIntegrations(
    db: Queryable,
    owner: IntegrationOwner,
    selection: RowSelection,
    page: PageRequest
): Promise<Page> {
    const conditions = new Conditions()
    conditions.add(`owner_type = ${conditions.bind(owner.type)}`)
    conditions.add(`owner_id = ${conditions.bind(owner.id)}`)
    conditions.add('deleted_at IS NULL')
    addSelection(conditions, selection)
    return selectPage(db, conditions, page)
}

/** One page of the live team rows of every team that match. For the cross-team list only. */
export async function listIntegrationsAcrossTeams(
    db: Queryable,
    selection: CrossTeamSelection,
    page: PageRequest
): Promise<Page> {
    const conditions = new Conditions()
    conditions.add(`owner_type = 'team'`)
    conditions.add('deleted_at IS NULL')
    addSelection(conditions, selection)
    if (selection.teamIds !== null) {
        conditions.add(`owner_id = ANY(${conditions.bind(selection.teamIds)}::bigint[])`)
    }
    if (selection.excludeTeamIds.length > 0) {
        conditions.add(`owner_id <> ALL(${conditions.bind(selection.excludeTeamIds)}::bigint[])`)
    }
    if (selection.createdByIds !== null) {
        conditions.add(`created_by_id = ANY(${conditions.bind(selection.createdByIds)}::bigint[])`)
    }
    return selectPage(db, conditions, page)
}

/** The owner's live rows with any of these refs. A ref of another owner or a deleted row is absent. */
export async function getIntegrationsByRefs(
    db: Queryable,
    owner: IntegrationOwner,
    refs: readonly IntegrationRef[]
): Promise<IntegrationRow[]> {
    const ids = refs.flatMap((ref) => ('id' in ref ? [ref.id] : []))
    const legacyIds = refs.flatMap((ref) => ('legacyId' in ref ? [ref.legacyId] : []))
    if (ids.length === 0 && legacyIds.length === 0) {
        return []
    }
    const result = await query<DbRow>(
        db,
        `SELECT ${COLUMNS} FROM integrations
         WHERE owner_type = $1 AND owner_id = $2 AND deleted_at IS NULL
           AND (id = ANY($3::uuid[]) OR legacy_id = ANY($4::bigint[]))`,
        [owner.type, owner.id, ids, legacyIds]
    )
    return result.rows.map(toRow)
}

/** Locks one live row of the owner until the transaction ends. Null when there is no such row. */
export async function lockIntegration(
    db: Queryable,
    owner: IntegrationOwner,
    ref: IntegrationRef
): Promise<IntegrationRow | null> {
    const column = 'id' in ref ? 'id = $3::uuid' : 'legacy_id = $3'
    const result = await query<DbRow>(
        db,
        `SELECT ${COLUMNS} FROM integrations
         WHERE owner_type = $1 AND owner_id = $2 AND ${column} AND deleted_at IS NULL
         FOR UPDATE`,
        [owner.type, owner.id, 'id' in ref ? ref.id : ref.legacyId]
    )
    const row = result.rows[0]
    return row ? toRow(row) : null
}

/**
 * Serializes writers of one (owner, kind, external id) key until the transaction ends, then locks
 * and returns the live row with that key. A null external id is a key too, the same as in Django.
 */
export async function lockIntegrationByKey(
    db: Queryable,
    owner: IntegrationOwner,
    kind: string,
    externalId: string | null
): Promise<IntegrationRow | null> {
    // The unique index does not cover a null external id, so only this lock stops two upserts
    // from both inserting.
    await query(db, 'SELECT pg_advisory_xact_lock($1, hashtext($2))', [
        UPSERT_LOCK_CLASS,
        JSON.stringify([owner.type, owner.id, kind, externalId]),
    ])
    const result = await query<DbRow>(
        db,
        `SELECT ${COLUMNS} FROM integrations
         WHERE owner_type = $1 AND owner_id = $2 AND kind = $3 AND external_id IS NOT DISTINCT FROM $4
           AND deleted_at IS NULL
         ORDER BY created_at, id
         LIMIT 1
         FOR UPDATE`,
        [owner.type, owner.id, kind, externalId]
    )
    const row = result.rows[0]
    return row ? toRow(row) : null
}

/**
 * Locks every live team row of one kind with this external id, in every team, until the
 * transaction ends. Id order keeps two such transactions from deadlocking each other.
 */
export async function lockIntegrationsByExternalId(
    db: Queryable,
    kind: string,
    externalId: string,
    sourceRows: SourceRows
): Promise<IntegrationRow[]> {
    const conditions = new Conditions()
    conditions.add(`owner_type = 'team'`)
    conditions.add('deleted_at IS NULL')
    conditions.add(`kind = ${conditions.bind(kind)}`)
    conditions.add(`external_id = ${conditions.bind(externalId)}`)
    if (sourceRows === 'exclude') {
        conditions.add('NOT is_source_row')
    } else if (sourceRows === 'only') {
        conditions.add('is_source_row')
    }
    const result = await query<DbRow>(
        db,
        `SELECT ${COLUMNS} FROM integrations WHERE ${conditions.sql()} ORDER BY id FOR UPDATE`,
        conditions.values
    )
    return result.rows.map(toRow)
}

/**
 * Soft-deletes up to `limit` live rows of the owner, lowest ids first, and returns them. Run it in
 * a transaction and repeat until it returns no rows.
 */
export async function softDeleteOwnerBatch(
    db: Queryable,
    owner: IntegrationOwner,
    limit: number
): Promise<IntegrationRow[]> {
    const result = await query<DbRow>(
        db,
        `WITH batch AS (
             SELECT id FROM integrations
             WHERE owner_type = $1 AND owner_id = $2 AND deleted_at IS NULL
             ORDER BY id
             LIMIT $3
             FOR UPDATE
         )
         UPDATE integrations
         SET deleted_at = now(), updated_at = now(), version = version + 1
         WHERE id IN (SELECT id FROM batch)
         RETURNING ${COLUMNS}`,
        [owner.type, owner.id, limit]
    )
    return result.rows.map(toRow)
}

/** A position in the change feed: the `updated_at` text Postgres printed, and the id. */
export interface ChangeCursor {
    updatedAt: string
    id: string
}

export interface ChangeRequest {
    /** Null selects every kind. */
    kinds: readonly string[] | null
    after: ChangeCursor | null
    limit: number
    /** Rows younger than this are not returned yet. See `listChangedIntegrations`. */
    settleSeconds: number
}

export interface ChangedRow {
    row: IntegrationRow
    cursor: ChangeCursor
}

interface ChangedDbRow extends DbRow {
    cursor_updated_at: string
}

/**
 * Team rows changed after `after`, deleted rows included, oldest change first.
 *
 * `updated_at` is `now()` of the writing transaction, which is its start time. A transaction that
 * started earlier can commit after a later one, so a reader that follows the cursor could pass
 * a row that is not visible yet and never see it. The feed therefore holds back rows younger than
 * `settleSeconds`: it is safe as long as no write transaction lasts that long. A statement timeout
 * and the short write paths bound them far below the default window, and every integration write
 * rolls back past `WRITE_DEADLINE_MS`. `statement_timestamp()` is stable within the
 * query, so the cutoff is an upper bound of the index scan rather than a per-row filter.
 */
export async function listChangedIntegrations(db: Queryable, request: ChangeRequest): Promise<ChangedRow[]> {
    const conditions = new Conditions()
    conditions.add(`owner_type = 'team'`)
    conditions.add(
        `updated_at <= statement_timestamp() - make_interval(secs => ${conditions.bind(request.settleSeconds)}::double precision)`
    )
    if (request.kinds !== null) {
        conditions.add(`kind = ANY(${conditions.bind(request.kinds)}::text[])`)
    }
    if (request.after) {
        conditions.add(
            `(updated_at, id) > (${conditions.bind(request.after.updatedAt)}::timestamptz, ${conditions.bind(request.after.id)}::uuid)`
        )
    }
    const limit = conditions.bind(request.limit)
    const result = await query<ChangedDbRow>(
        db,
        `SELECT ${COLUMNS}, updated_at::text AS cursor_updated_at
         FROM integrations
         WHERE ${conditions.sql()}
         ORDER BY updated_at, id
         LIMIT ${limit}`,
        conditions.values
    )
    return result.rows.map((row) => ({ row: toRow(row), cursor: { updatedAt: row.cursor_updated_at, id: row.id } }))
}
