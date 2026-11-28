// `PUT /v1/integrations/mirror`: copies Django `posthog_integration` rows, keyed by their int id.
// Django stays the source of truth, so a row replaces every stored field. The sender's
// `source_version` orders the writes, so a late retry of an older copy cannot win.
//
// `POST /v1/integrations/mirror/purge`: the rollback. It hard-deletes the copies of one kind.
// A soft delete would leave a tombstone, and a tombstone answers a later upsert with `stale`,
// so a new backfill after the rollback could not start clean.

import { randomUUID } from 'node:crypto'
import type { Pool, PoolClient } from 'pg'

import { IntegrationAuthError, assertKindAllowed } from '../auth/integrations'
import type { JsonObject } from '../crypto/canonical'
import type { Envelope, SealedSecret } from '../crypto/envelope'
import type { IntegrationOwner } from '../db/integrations'
import {
    type MirrorOwnedRow,
    type MirrorRow,
    type MirrorWriteResult,
    findKeyHolder,
    getByLegacyId,
    hardDeleteMirrorOwned,
    insertMirrored,
    listMirrorOwned,
    lockByLegacyId,
    replaceMirrored,
    softDeleteMirrored,
} from '../db/mirror'
import { deleteSecret, putSecret } from '../db/secrets'
import { withTransaction } from '../db/transaction'
import { logger } from '../lib/logging'
import { type AuditEntry, insertAuditRows, logAuditEntries } from './audit'
import { IntegrationApiError } from './errors'
import { mirrorPurgeRowsTotal, mirrorRowsTotal } from './metrics'
import { type Caller, isEmpty, owner, sealSecret, writeDeadline } from './service'
import {
    type MirrorBody,
    type MirrorDeleteRow,
    type MirrorPurgeBody,
    type MirrorRowBody,
    type MirrorUpsertRow,
    checkAuthType,
} from './validation'

const MIRROR_CONCURRENCY = 8
// A tombstone has no auth type of its own. A valid one keeps readers of the change feed parsing it.
const TOMBSTONE_AUTH_TYPE = 'credentials'
// A tombstone needs a source version to count as a mirror row, so the purge can find it.
// A stored tombstone refuses every upsert whatever its version, so the lowest one is enough.
const TOMBSTONE_SOURCE_VERSION = 0

export type MirrorOutcome =
    | 'created'
    | 'updated'
    | 'deleted'
    | 'unchanged'
    | 'stale'
    | 'absent'
    | 'owner_mismatch'
    | 'conflict'
    | 'rejected'

export interface MirrorResult {
    legacy_id: number
    outcome: MirrorOutcome
    id?: string
    /** Set with a key `conflict`. Null when the row that holds the key did not come from the mirror. */
    conflicting_legacy_id?: number | null
    /** Set with `rejected`, and with a retryable `conflict` (`concurrent_write`) after two lost races. */
    code?: string
}

export type MirrorWrite = 'insert' | 'tombstone' | 'replace' | 'delete'

export type MirrorDecision = { outcome: 'owner_mismatch' | 'stale' | 'unchanged' | 'absent' } | { write: MirrorWrite }

type StoredState = Pick<MirrorRow, 'ownerType' | 'ownerId' | 'deletedAt' | 'sourceVersion'>

/** What a mirrored row does to the stored row with its legacy id. */
export function decideMirror(
    stored: StoredState | null,
    row: MirrorRowBody,
    teamOwner: IntegrationOwner,
    force: boolean
): MirrorDecision {
    if (stored && (stored.ownerType !== teamOwner.type || stored.ownerId !== teamOwner.id)) {
        return { outcome: 'owner_mismatch' }
    }
    if (!stored) {
        if (!row.deleted) {
            return { write: 'insert' }
        }
        return row.tombstone ? { write: 'tombstone' } : { outcome: 'absent' }
    }
    if (stored.deletedAt !== null) {
        return { outcome: row.deleted ? 'unchanged' : 'stale' }
    }
    // A delete wins whatever its version: a deleted Django id never comes back, and the version
    // a delete signal carries can be older than the last update.
    if (row.deleted) {
        return { write: 'delete' }
    }
    // A live row with a legacy id but no source version was not written by the mirror.
    const storedVersion = stored.sourceVersion ?? -1
    if (row.source_version < storedVersion) {
        return { outcome: 'stale' }
    }
    if (row.source_version === storedVersion && !force) {
        return { outcome: 'unchanged' }
    }
    return { write: 'replace' }
}

type RaceReason = 'row_changed' | 'legacy_id_taken' | 'key_taken'

/** The locked row is not the one the decision and the seal were made for, or a concurrent writer won. */
class RowChanged extends Error {
    constructor(readonly reason: RaceReason) {
        super(reason)
    }
}

function sameState(a: MirrorRow | null, b: MirrorRow | null): boolean {
    return a === null || b === null ? a === b : a.id === b.id && a.version === b.version
}

function secretOf(row: MirrorUpsertRow): JsonObject | null {
    const blob = row.sensitive_config as JsonObject
    return isEmpty(blob) && row.legacy_unreadable_keys.length === 0 ? null : blob
}

export interface MirrorPurgeResult {
    /** The rows deleted. Zero for a dry run. */
    purged: number
    /** The legacy ids deleted, or for a dry run the ones it would delete, in order. */
    legacy_ids: number[]
    /** The cursor for the next page, or null when this page was the last. */
    next_after_legacy_id: number | null
}

export interface MirrorDeps {
    pool: Pool
    envelope: Envelope
    /** Test hook. Runs in the write transaction just before the row's write statement. */
    beforeWrite?: ((legacyId: number, attempt: number) => Promise<void>) | undefined
}

export class MirrorService {
    constructor(private readonly deps: MirrorDeps) {}

    async mirror(caller: Caller, body: MirrorBody): Promise<{ results: MirrorResult[] }> {
        const teamOwner = owner(caller)
        const results: MirrorResult[] = new Array(body.rows.length)
        let next = 0
        let failed = false
        const worker = async (): Promise<void> => {
            while (!failed && next < body.rows.length) {
                const index = next++
                const row = body.rows[index] as MirrorRowBody
                let result: MirrorResult
                try {
                    result = await this.mirrorRow(caller, teamOwner, body, row)
                } catch (err) {
                    failed = true
                    throw err
                }
                mirrorRowsTotal.labels({ origin: body.origin, outcome: result.outcome }).inc()
                results[index] = result
            }
        }
        // Waits for the rows in flight, so no write commits after the request has failed.
        const settled = await Promise.allSettled(
            Array.from({ length: Math.min(MIRROR_CONCURRENCY, body.rows.length) }, worker)
        )
        const failure = settled.find((outcome) => outcome.status === 'rejected')
        if (failure) {
            throw failure.reason
        }
        return { results }
    }

    /** Deletes one page of the rows that the mirror wrote for `body.kind`. One transaction per page. */
    async purge(caller: Caller, body: MirrorPurgeBody): Promise<MirrorPurgeResult> {
        // The route checked the kind against the token. Source rows of the kind need the source-row grant too.
        assertKindAllowed(caller.auth, body.kind)
        const sourceRows = caller.auth.sourceRows
        const filter = {
            kind: body.kind,
            afterLegacyId: body.after_legacy_id,
            limit: body.limit,
            teamIds: body.team_ids,
            sourceRows: sourceRows !== null && (sourceRows.kinds === null || sourceRows.kinds.includes(body.kind)),
        }
        const entry = (outcome: string, details: Record<string, unknown>, row?: MirrorOwnedRow): AuditEntry => ({
            actor: caller.actor,
            occurredAt: new Date(),
            operation: 'mirror_purge',
            outcome,
            ownerType: row?.ownerType ?? null,
            ownerId: row?.ownerId ?? null,
            integrationId: row?.id ?? null,
            kind: body.kind,
            fields: [],
            details,
        })

        let rows: MirrorOwnedRow[]
        let entries: AuditEntry[]
        if (body.dry_run) {
            rows = await listMirrorOwned(this.deps.pool, filter, false)
            entries = [entry('dry_run', { matched: rows.length, after_legacy_id: body.after_legacy_id })]
            await insertAuditRows(this.deps.pool, entries)
        } else {
            const page = await this.writeTransaction(async (tx) => {
                const locked = await listMirrorOwned(tx, filter, true)
                const deleted = await hardDeleteMirrorOwned(
                    tx,
                    locked.map((row) => row.id)
                )
                // No foreign key points from audit_log to integrations, so these rows outlive the purge.
                const written = deleted.map((row) =>
                    entry('purged', { legacy_id: row.legacyId, source_version: row.sourceVersion }, row)
                )
                await insertAuditRows(tx, written)
                return { deleted, written }
            })
            rows = page.deleted
            entries = page.written
        }
        logAuditEntries(entries)
        if (rows.length > 0) {
            mirrorPurgeRowsTotal.labels({ outcome: body.dry_run ? 'dry_run' : 'purged' }).inc(rows.length)
        }

        const legacyIds = rows.map((row) => row.legacyId)
        return {
            purged: body.dry_run ? 0 : rows.length,
            legacy_ids: legacyIds,
            // A page shorter than the limit was the last one.
            next_after_legacy_id: legacyIds.length === body.limit ? (legacyIds.at(-1) ?? null) : null,
        }
    }

    private async mirrorRow(
        caller: Caller,
        teamOwner: IntegrationOwner,
        body: MirrorBody,
        row: MirrorRowBody
    ): Promise<MirrorResult> {
        const legacyId = row.legacy_id
        try {
            if (!row.deleted) {
                checkAuthType(row.auth_type)
                assertKindAllowed(caller.auth, row.kind, { sourceRow: row.is_source_row })
            }
            for (let attempt = 0; ; attempt++) {
                const stored = await getByLegacyId(this.deps.pool, legacyId)
                const decision = this.decide(caller, stored, row, teamOwner, body.force)
                if ('outcome' in decision) {
                    return this.terminal(legacyId, decision.outcome, stored)
                }
                const id = stored?.id ?? randomUUID()
                const secret = row.deleted ? null : secretOf(row)
                // Sealed before the transaction, so the KMS call holds no row lock or connection.
                const sealed =
                    secret === null
                        ? null
                        : await sealSecret(this.deps.envelope, { id, ownerId: teamOwner.id, kind: row.kind }, secret)
                const committed: AuditEntry[] = []
                try {
                    const result = await this.writeTransaction(async (tx) => {
                        const locked = await lockByLegacyId(tx, legacyId)
                        if (!sameState(stored, locked)) {
                            throw new RowChanged('row_changed')
                        }
                        return this.write(
                            tx,
                            caller,
                            teamOwner,
                            body,
                            row,
                            decision.write,
                            id,
                            sealed,
                            committed,
                            attempt
                        )
                    })
                    logAuditEntries(committed)
                    return result
                } catch (err) {
                    if (!(err instanceof RowChanged)) {
                        throw err
                    }
                    logger.warn('integrations:mirror_row_changed', { legacyId, attempt, reason: err.reason })
                    if (attempt >= 1) {
                        // The sender retries the row later. The other rows of the batch keep their results.
                        return { legacy_id: legacyId, outcome: 'conflict', code: 'concurrent_write' }
                    }
                }
            }
        } catch (err) {
            if (err instanceof IntegrationAuthError) {
                return { legacy_id: legacyId, outcome: 'rejected', code: err.code }
            }
            if (err instanceof IntegrationApiError && err.code !== 'kms_unavailable') {
                return { legacy_id: legacyId, outcome: 'rejected', code: err.code }
            }
            throw err
        }
    }

    private decide(
        caller: Caller,
        stored: MirrorRow | null,
        row: MirrorRowBody,
        teamOwner: IntegrationOwner,
        force: boolean
    ): MirrorDecision {
        const decision = decideMirror(stored, row, teamOwner, force)
        if (stored && !('outcome' in decision && decision.outcome === 'owner_mismatch')) {
            assertKindAllowed(caller.auth, stored.kind, { sourceRow: stored.isSourceRow })
        } else if (!stored && row.deleted) {
            assertKindAllowed(caller.auth, row.kind)
        }
        return decision
    }

    private terminal(legacyId: number, outcome: MirrorOutcome, stored: MirrorRow | null): MirrorResult {
        // Another team's row id is not the caller's to learn.
        return stored && outcome !== 'owner_mismatch'
            ? { legacy_id: legacyId, outcome, id: stored.id }
            : { legacy_id: legacyId, outcome }
    }

    private async write(
        tx: PoolClient,
        caller: Caller,
        teamOwner: IntegrationOwner,
        body: MirrorBody,
        row: MirrorRowBody,
        write: MirrorWrite,
        id: string,
        sealed: SealedSecret | null,
        committed: AuditEntry[],
        attempt: number
    ): Promise<MirrorResult> {
        const legacyId = row.legacy_id
        let written: MirrorWriteResult
        let outcome: 'created' | 'updated' | 'deleted'
        if (write === 'insert' || write === 'replace') {
            const upsert = row as MirrorUpsertRow
            if (upsert.integration_id !== null) {
                const holder = await findKeyHolder(
                    tx,
                    teamOwner,
                    upsert.kind,
                    upsert.integration_id,
                    write === 'replace' ? id : null
                )
                if (holder) {
                    return { legacy_id: legacyId, outcome: 'conflict', conflicting_legacy_id: holder.legacyId }
                }
            }
            await this.deps.beforeWrite?.(legacyId, attempt)
            const fields = {
                kind: upsert.kind,
                externalId: upsert.integration_id,
                authType: checkAuthType(upsert.auth_type),
                isSourceRow: upsert.is_source_row,
                config: upsert.config,
                errors: upsert.errors,
                createdById: upsert.created_by_id,
                createdAt: upsert.created_at,
                sourceVersion: upsert.source_version,
            }
            written =
                write === 'insert'
                    ? await insertMirrored(tx, { ...fields, id, owner: teamOwner, legacyId, deleted: false })
                    : await replaceMirrored(tx, teamOwner, id, fields)
            outcome = write === 'insert' ? 'created' : 'updated'
        } else if (write === 'tombstone') {
            await this.deps.beforeWrite?.(legacyId, attempt)
            written = await insertMirrored(tx, {
                id,
                owner: teamOwner,
                legacyId,
                deleted: true,
                kind: row.kind,
                externalId: null,
                authType: TOMBSTONE_AUTH_TYPE,
                isSourceRow: false,
                config: {},
                errors: '',
                createdById: null,
                createdAt: null,
                sourceVersion: (row as MirrorDeleteRow).source_version ?? TOMBSTONE_SOURCE_VERSION,
            })
            outcome = 'deleted'
        } else {
            await this.deps.beforeWrite?.(legacyId, attempt)
            written = await softDeleteMirrored(tx, teamOwner, id, (row as MirrorDeleteRow).source_version ?? null)
            outcome = 'deleted'
        }
        // A concurrent writer took the legacy id or the key after the checks above. The retry sees it.
        if (written.status !== 'ok') {
            throw new RowChanged(written.status)
        }

        if (sealed) {
            await putSecret(tx, id, sealed, (row as MirrorUpsertRow).legacy_unreadable_keys)
        } else if (write !== 'insert' && write !== 'tombstone') {
            await deleteSecret(tx, id)
        }

        const entry: AuditEntry = {
            actor: caller.actor,
            occurredAt: caller.requestedAt,
            operation: 'mirror',
            outcome,
            ownerType: written.row.ownerType,
            ownerId: written.row.ownerId,
            integrationId: written.row.id,
            kind: written.row.kind,
            fields: row.deleted
                ? []
                : [...new Set([...Object.keys(row.sensitive_config), ...row.legacy_unreadable_keys])].sort(),
            details: { origin: body.origin, legacy_id: legacyId, source_version: row.source_version ?? null },
        }
        await insertAuditRows(tx, [entry])
        committed.push(entry)
        return { legacy_id: legacyId, outcome, id: written.row.id }
    }

    private writeTransaction<T>(fn: (tx: PoolClient) => Promise<T>): Promise<T> {
        const checkDeadline = writeDeadline()
        return withTransaction(this.deps.pool, async (tx) => {
            const result = await fn(tx)
            checkDeadline()
            return result
        })
    }
}
