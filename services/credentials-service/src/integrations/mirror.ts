// `PUT /v1/integrations/mirror`: copies Django `posthog_integration` rows, keyed by their int id.
// Django stays the source of truth, so a row replaces every stored field. The sender's
// `source_version` orders the writes, so a late retry of an older copy cannot win.

import { randomUUID } from 'node:crypto'
import type { Pool, PoolClient } from 'pg'

import { IntegrationAuthError, assertKindAllowed } from '../auth/integrations'
import type { JsonObject } from '../crypto/canonical'
import type { Envelope, SealedSecret } from '../crypto/envelope'
import type { IntegrationOwner } from '../db/integrations'
import {
    type MirrorRow,
    type MirrorWriteResult,
    findKeyHolder,
    getByLegacyId,
    insertMirrored,
    lockByLegacyId,
    replaceMirrored,
    softDeleteMirrored,
} from '../db/mirror'
import { deleteSecret, putSecret } from '../db/secrets'
import { withTransaction } from '../db/transaction'
import { logger } from '../lib/logging'
import { type AuditEntry, insertAuditRows, logAuditEntries } from './audit'
import { IntegrationApiError } from './errors'
import { mirrorRowsTotal } from './metrics'
import { type Caller, isEmpty, owner, sealSecret, writeDeadline } from './service'
import {
    type MirrorBody,
    type MirrorDeleteRow,
    type MirrorRowBody,
    type MirrorUpsertRow,
    checkAuthType,
} from './validation'

const MIRROR_CONCURRENCY = 8
// A tombstone has no auth type of its own. A valid one keeps readers of the change feed parsing it.
const TOMBSTONE_AUTH_TYPE = 'credentials'

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
    // A live row with a legacy id but no source version was not written by the mirror.
    const storedVersion = stored.sourceVersion ?? -1
    if (row.deleted) {
        // A delete without a version still wins: a deleted Django id never comes back.
        return row.source_version !== undefined && row.source_version < storedVersion
            ? { outcome: 'stale' }
            : { write: 'delete' }
    }
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
                sourceVersion: (row as MirrorDeleteRow).source_version ?? null,
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
            occurredAt: new Date(),
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
