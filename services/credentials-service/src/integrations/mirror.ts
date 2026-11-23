// `PUT /v1/integrations/mirror`: copies Django `posthog_integration` rows, keyed by their int id.
// Django stays the source of truth, so a row replaces every stored field. The sender's
// `source_version` orders the writes, so a late retry of an older copy cannot win.

import { randomUUID } from 'node:crypto'
import type { Pool, PoolClient } from 'pg'

import { IntegrationAuthError, assertKindAllowed } from '../auth/integrations'
import type { JsonObject } from '../crypto/canonical'
import type { Envelope, SealedSecret } from '../crypto/envelope'
import { KmsError } from '../crypto/types'
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
import { type Caller, encryptionContext, isEmpty, kmsUnavailable, owner, writeDeadline } from './service'
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
    /** Set with `conflict`. Null when the row that holds the key did not come from the mirror. */
    conflicting_legacy_id?: number | null
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
    if (row.deleted) {
        return { write: 'delete' }
    }
    // A live row with a legacy id but no source version was not written by the mirror: replace it.
    const storedVersion = stored.sourceVersion ?? -1
    if (row.source_version < storedVersion) {
        return { outcome: 'stale' }
    }
    if (row.source_version === storedVersion && !force) {
        return { outcome: 'unchanged' }
    }
    return { write: 'replace' }
}

/** The locked row is not the one the decision and the seal were made for. */
class RowChanged extends Error {}

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
}

export class MirrorService {
    constructor(private readonly deps: MirrorDeps) {}

    async mirror(caller: Caller, body: MirrorBody): Promise<{ results: MirrorResult[] }> {
        const teamOwner = owner(caller)
        const results: MirrorResult[] = new Array(body.rows.length)
        let next = 0
        const worker = async (): Promise<void> => {
            while (next < body.rows.length) {
                const index = next++
                const row = body.rows[index] as MirrorRowBody
                const result = await this.mirrorRow(caller, teamOwner, body, row)
                mirrorRowsTotal.labels({ origin: body.origin, outcome: result.outcome }).inc()
                results[index] = result
            }
        }
        await Promise.all(Array.from({ length: Math.min(MIRROR_CONCURRENCY, body.rows.length) }, worker))
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
                    secret === null ? null : await this.seal({ id, ownerId: teamOwner.id, kind: row.kind }, secret)
                const committed: AuditEntry[] = []
                try {
                    const result = await this.writeTransaction(async (tx) => {
                        const locked = await lockByLegacyId(tx, legacyId)
                        if (!sameState(stored, locked)) {
                            throw new RowChanged()
                        }
                        return this.write(tx, caller, teamOwner, body, row, decision.write, id, sealed, committed)
                    })
                    logAuditEntries(committed)
                    return result
                } catch (err) {
                    if (!(err instanceof RowChanged) || attempt >= 1) {
                        throw err
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
        committed: AuditEntry[]
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
                    : await replaceMirrored(tx, id, fields)
            outcome = write === 'insert' ? 'created' : 'updated'
        } else if (write === 'tombstone') {
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
            written = await softDeleteMirrored(tx, id, (row as MirrorDeleteRow).source_version ?? null)
            outcome = 'deleted'
        }
        // A concurrent writer took the legacy id or the key after the checks above. The retry sees it.
        if (written.status !== 'ok') {
            throw new RowChanged()
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
            fields: row.deleted ? [] : Object.keys(row.sensitive_config).sort(),
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

    private async seal(row: { id: string; ownerId: number; kind: string }, blob: JsonObject): Promise<SealedSecret> {
        try {
            return await this.deps.envelope.seal(blob, encryptionContext(row))
        } catch (err) {
            if (err instanceof KmsError) {
                logger.error('integrations:seal_failed', { integrationId: row.id, reason: err.reason })
                throw kmsUnavailable()
            }
            throw err
        }
    }
}
