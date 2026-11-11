// What each `/v1/integrations/*` route does. The routes parse and authorize; this class reads and
// writes rows, seals and opens secrets, and writes the audit trail. Every owner here comes from
// the caller's token.

import { createHash, randomUUID } from 'node:crypto'
import type { Pool } from 'pg'

import { type IntegrationAuth, assertKindAllowed } from '../auth/integrations'
import { type JsonObject, type JsonValue, canonicalJson } from '../crypto/canonical'
import type { Envelope, SealedSecret } from '../crypto/envelope'
import { EnvelopeError, KmsError } from '../crypto/types'
import { claimIdempotencyKey, recordIdempotencyResult } from '../db/idempotency'
import {
    type ListCursor,
    type Page,
    type PageRequest,
    getIntegrationsByRefs,
    listIntegrations,
    listIntegrationsAcrossTeams,
    lockIntegration,
    lockIntegrationByKey,
} from '../db/integration-queries'
import {
    type IntegrationChanges,
    type IntegrationOwner,
    type IntegrationRow,
    type Queryable,
    getIntegration,
    insertIntegration,
    softDeleteIntegration,
    updateIntegration,
} from '../db/integrations'
import { type StoredSecret, deleteSecret, getSecrets, putSecret } from '../db/secrets'
import { withTransaction } from '../db/transaction'
import { logger } from '../lib/logging'
import { type AuditActor, type AuditEntry, type AuditQueue, insertAuditRows, logAuditEntries } from './audit'
import { IntegrationApiError, notFound } from './errors'
import { assertIdentityUnchanged } from './identity'
import { type IntegrationRecordJson, exposedCredentials, toRecordJson, tokenExpiresAt } from './record'
import {
    type CrossTeamBody,
    type ListQuery,
    type NewIntegrationBody,
    type PatchBody,
    checkAuthType,
    parseRef,
} from './validation'

const DECRYPT_CONCURRENCY = 16
const IDEMPOTENT_CREATE = 'create'
// The text form Postgres prints for a timestamptz, as the list cursor carries it.
const CURSOR_TIMESTAMP = /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(\.\d{1,6})?[+-]\d{2}(:\d{2}){0,2}$/
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/

export interface IntegrationsDeps {
    pool: Pool
    envelope: Envelope
    audit: AuditQueue
}

/** The verified caller of one request. */
export interface Caller {
    auth: IntegrationAuth
    actor: AuditActor
}

export interface RecordPage {
    results: IntegrationRecordJson[]
    next: string | null
}

export interface ResolvedRecord {
    record: IntegrationRecordJson
    credentials: JsonObject
    expires_at: string | null
}

export interface ResolveResult {
    records: Record<string, ResolvedRecord>
    missing: string[]
    /** Refs that exist but whose secret the service cannot return, with the reason. */
    errors: Record<string, { code: 'unreadable_secret'; message: string; details: Record<string, unknown> }>
}

/** A row is allowed when its kind is, and a warehouse source row also needs the source-row grant. */
function assertRowAllowed(auth: IntegrationAuth, row: IntegrationRow): void {
    assertKindAllowed(auth, row.kind, { sourceRow: row.isSourceRow })
}

/**
 * The kinds a list may return, once the token's source-row grant is applied. Throws when the
 * request asks for source rows that the grant does not cover.
 */
function listKinds(
    auth: IntegrationAuth,
    mode: 'exclude' | 'only' | 'include',
    requested: readonly string[] | null
): readonly string[] | null {
    if (mode === 'exclude') {
        return requested ?? auth.kinds
    }
    const grant = auth.sourceRows
    // `include` mixes both row types under one kind filter, so it needs an unrestricted grant.
    if (grant === null || (mode === 'include' && grant.kinds !== null)) {
        throw new IntegrationApiError('forbidden_kind', 'the token does not allow source rows')
    }
    if (mode === 'only') {
        const allowed = grant.kinds
        if (allowed !== null && requested !== null && !requested.every((kind) => allowed.includes(kind))) {
            throw new IntegrationApiError('forbidden_kind', 'the token does not allow this kind')
        }
        return requested ?? grant.kinds
    }
    return requested ?? auth.kinds
}

function owner(caller: Caller): IntegrationOwner {
    const tokenOwner = caller.auth.owner
    if (tokenOwner === null) {
        // The auth middleware rejects an ownerless token for every owner-scoped operation.
        throw new IntegrationApiError('forbidden_op', 'this operation needs a token with an owner')
    }
    return tokenOwner
}

function isEmpty(value: object): boolean {
    return Object.keys(value).length === 0
}

function sameJson(a: JsonObject, b: JsonObject): boolean {
    return canonicalJson(a) === canonicalJson(b)
}

/** The value after `patch` is merged in and the `remove` keys are dropped, the same as the Python SDK. */
function patched(current: JsonObject, patch: JsonObject, remove: readonly string[]): JsonObject {
    const result: JsonObject = { ...current, ...patch }
    for (const key of remove) {
        delete result[key]
    }
    return result
}

function encodeCursor(cursor: ListCursor | null): string | null {
    return cursor === null ? null : Buffer.from(JSON.stringify([cursor.createdAt, cursor.id])).toString('base64url')
}

function decodeCursor(value: string | null): ListCursor | null {
    if (value === null) {
        return null
    }
    let parsed: unknown
    try {
        parsed = JSON.parse(Buffer.from(value, 'base64url').toString('utf8'))
    } catch {
        parsed = null
    }
    if (
        !Array.isArray(parsed) ||
        parsed.length !== 2 ||
        typeof parsed[0] !== 'string' ||
        typeof parsed[1] !== 'string' ||
        !CURSOR_TIMESTAMP.test(parsed[0]) ||
        !UUID.test(parsed[1])
    ) {
        throw new IntegrationApiError('validation', 'the page cursor is not valid')
    }
    return { createdAt: parsed[0], id: parsed[1] }
}

/** Runs `fn` on every item, with at most `limit` calls in flight. */
async function forEachLimit<T>(items: readonly T[], limit: number, fn: (item: T) => Promise<void>): Promise<void> {
    let next = 0
    async function worker(): Promise<void> {
        while (next < items.length) {
            const item = items[next++] as T
            await fn(item)
        }
    }
    await Promise.all(Array.from({ length: Math.min(limit, items.length) }, worker))
}

function encryptionContext(row: { id: string; ownerId: number; kind: string }): {
    integrationId: string
    ownerId: string
    kind: string
} {
    return { integrationId: row.id, ownerId: String(row.ownerId), kind: row.kind }
}

function kmsUnavailable(): IntegrationApiError {
    return new IntegrationApiError('kms_unavailable', 'the key service is not available, retry later')
}

function unreadableSecret(details: Record<string, unknown> = {}): IntegrationApiError {
    return new IntegrationApiError('unreadable_secret', 'the stored secret cannot be read', details)
}

export class IntegrationsService {
    constructor(private readonly deps: IntegrationsDeps) {}

    async list(caller: Caller, query: ListQuery): Promise<RecordPage> {
        const authTypes = query.authTypes?.map(checkAuthType) ?? null
        const page = await listIntegrations(
            this.deps.pool,
            owner(caller),
            {
                // The middleware checked that the requested kinds are in the token. With none
                // requested, a kind-narrowed token still lists only its own kinds.
                kinds: listKinds(caller.auth, query.sourceRows, query.kinds),
                authTypes,
                externalId: query.externalId,
                sourceRows: query.sourceRows,
                where: query.where,
                whereIn: {},
                whereIexact: {},
                hasConfigKey: null,
            },
            this.pageRequest(query.limit, query.newestFirst, query.after)
        )
        return this.readPage(caller, 'list', page)
    }

    async get(caller: Caller, refText: string): Promise<IntegrationRow> {
        const row = await getIntegration(this.deps.pool, owner(caller), parseRef(refText))
        if (!row) {
            throw notFound(refText)
        }
        assertRowAllowed(caller.auth, row)
        this.auditReads(caller, 'read', [row])
        return row
    }

    async batchGet(
        caller: Caller,
        refs: readonly string[]
    ): Promise<{ records: Record<string, IntegrationRecordJson>; missing: string[] }> {
        const { found, missing } = await this.rowsByRef(caller, refs)
        const records: Record<string, IntegrationRecordJson> = {}
        for (const [ref, row] of found) {
            records[ref] = toRecordJson(row)
        }
        this.auditReads(caller, 'batch_get', uniqueRows(found))
        return { records, missing }
    }

    async create(
        caller: Caller,
        body: NewIntegrationBody,
        idempotencyKey: string | null
    ): Promise<{ row: IntegrationRow; replayed: boolean }> {
        const teamOwner = owner(caller)
        const authType = checkAuthType(body.auth_type)
        assertKindAllowed(caller.auth, body.kind, { sourceRow: body.is_source_row })
        const blob = body.sensitive_config as JsonObject
        const id = randomUUID()
        // Sealed before the transaction, so the KMS call holds no row lock or connection.
        const sealed = isEmpty(blob) ? null : await this.seal({ id, ownerId: teamOwner.id, kind: body.kind }, blob)
        // The hash covers the secret key names, not their values: an unkeyed hash of a
        // low-entropy secret stored next to the row would allow offline guessing.
        const requestHash =
            idempotencyKey === null
                ? null
                : createHash('sha256')
                      .update(
                          canonicalJson({
                              ...body,
                              sensitive_config: Object.keys(blob).sort(),
                          } as unknown as JsonValue)
                      )
                      .digest()

        const committed: AuditEntry[] = []
        const result = await withTransaction(this.deps.pool, async (tx) => {
            if (idempotencyKey !== null && requestHash !== null) {
                const claim = await claimIdempotencyKey(
                    tx,
                    caller.actor.deployment,
                    teamOwner,
                    IDEMPOTENT_CREATE,
                    idempotencyKey,
                    requestHash
                )
                if (claim.status === 'mismatch') {
                    throw new IntegrationApiError('conflict', 'the Idempotency-Key was used for another request')
                }
                if (claim.status === 'replay') {
                    const earlier =
                        claim.integrationId === null
                            ? null
                            : await getIntegration(tx, teamOwner, { id: claim.integrationId })
                    if (!earlier) {
                        throw new IntegrationApiError(
                            'conflict',
                            'the integration that this Idempotency-Key created no longer exists'
                        )
                    }
                    return { row: earlier, replayed: true }
                }
            }

            const inserted = await insertIntegration(tx, {
                id,
                owner: teamOwner,
                kind: body.kind,
                externalId: body.integration_id,
                authType,
                config: body.config,
                isSourceRow: body.is_source_row,
                createdById: body.created_by_id,
            })
            if (inserted.status === 'conflict') {
                throw new IntegrationApiError('conflict', 'an integration of this kind with this external id exists', {
                    kind: body.kind,
                    integration_id: body.integration_id,
                })
            }
            if (sealed) {
                await putSecret(tx, id, sealed)
            }
            if (idempotencyKey !== null) {
                await recordIdempotencyResult(
                    tx,
                    caller.actor.deployment,
                    teamOwner,
                    IDEMPOTENT_CREATE,
                    idempotencyKey,
                    id
                )
            }
            await this.writeAudit(tx, committed, [
                this.auditEntry(caller, 'create', inserted.row, 'ok', Object.keys(blob)),
            ])
            return { row: inserted.row, replayed: false }
        })
        logAuditEntries(committed)
        if (result.replayed) {
            this.auditReads(caller, 'create_replay', [result.row])
        }
        return result
    }

    /**
     * Creates the row, or replaces the config and the whole secret blob of the live row with the
     * same (kind, external id). `created_by_id: null` keeps the creator of an existing row.
     */
    async upsert(caller: Caller, body: NewIntegrationBody): Promise<{ row: IntegrationRow; created: boolean }> {
        const teamOwner = owner(caller)
        const authType = checkAuthType(body.auth_type)
        assertKindAllowed(caller.auth, body.kind, { sourceRow: body.is_source_row })
        const blob = body.sensitive_config as JsonObject
        const committed: AuditEntry[] = []

        const result = await withTransaction(this.deps.pool, async (tx) => {
            const existing = await lockIntegrationByKey(tx, teamOwner, body.kind, body.integration_id)
            if (!existing) {
                const id = randomUUID()
                const sealed = isEmpty(blob)
                    ? null
                    : await this.seal({ id, ownerId: teamOwner.id, kind: body.kind }, blob)
                const inserted = await insertIntegration(tx, {
                    id,
                    owner: teamOwner,
                    kind: body.kind,
                    externalId: body.integration_id,
                    authType,
                    config: body.config,
                    isSourceRow: body.is_source_row,
                    createdById: body.created_by_id,
                })
                if (inserted.status === 'conflict') {
                    throw new IntegrationApiError('conflict', 'a concurrent create took this external id')
                }
                if (sealed) {
                    await putSecret(tx, id, sealed)
                }
                await this.writeAudit(tx, committed, [
                    this.auditEntry(caller, 'upsert', inserted.row, 'created', Object.keys(blob)),
                ])
                return { row: inserted.row, created: true }
            }

            // The Python SDK raises IntegrationConflict for a row outside the caller's scope.
            if (existing.authType !== authType || existing.isSourceRow !== body.is_source_row) {
                throw new IntegrationApiError('conflict', 'the existing integration has another auth type or source', {
                    reference: existing.legacyId === null ? existing.id : String(existing.legacyId),
                })
            }
            assertIdentityUnchanged(existing.kind, existing.config as JsonObject, body.config as JsonObject)
            const changes: IntegrationChanges = { config: body.config }
            if (body.created_by_id !== null) {
                changes.createdById = body.created_by_id
            }
            const updated = await updateIntegration(tx, teamOwner, { id: existing.id }, existing.version, changes)
            if (updated.status !== 'ok') {
                throw new Error(`upsert of a locked row returned ${updated.status}`)
            }
            if (isEmpty(blob)) {
                await deleteSecret(tx, existing.id)
            } else {
                await putSecret(tx, existing.id, await this.seal(existing, blob))
            }
            await this.writeAudit(tx, committed, [
                this.auditEntry(caller, 'upsert', updated.row, 'updated', Object.keys(blob)),
            ])
            return { row: updated.row, created: false }
        })
        logAuditEntries(committed)
        return result
    }

    /** Applies an `IntegrationPatch` under a row lock. A patch that changes nothing writes nothing. */
    async patch(caller: Caller, refText: string, body: PatchBody, ifMatch: number | null): Promise<IntegrationRow> {
        const teamOwner = owner(caller)
        const ref = parseRef(refText)
        const secretPatch = body.sensitive_config_patch as JsonObject
        const touchedSecretKeys = [...new Set([...Object.keys(secretPatch), ...body.sensitive_config_remove])].sort()

        const committed: AuditEntry[] = []
        const result = await withTransaction(this.deps.pool, async (tx) => {
            const row = await lockIntegration(tx, teamOwner, ref)
            if (!row) {
                throw notFound(refText)
            }
            assertRowAllowed(caller.auth, row)
            if (ifMatch !== null && row.version !== ifMatch) {
                throw versionMismatch(row.version)
            }

            const changes: IntegrationChanges = {}
            const config = row.config as JsonObject
            const newConfig = patched(config, body.config_patch as JsonObject, body.config_remove)
            assertIdentityUnchanged(row.kind, config, newConfig)
            if (!sameJson(newConfig, config)) {
                changes.config = newConfig
            }
            if (body.errors !== null && body.errors !== row.errors) {
                changes.errors = body.errors
            }

            let newSecret: { blob: JsonObject; unreadable: string[] } | null = null
            if (touchedSecretKeys.length > 0) {
                const stored = (await getSecrets(tx, teamOwner, [row.id])).get(row.id)
                const current = stored ? await this.open(row, stored) : {}
                const unreadable = stored?.legacyUnreadableKeys ?? []
                // A key the patch writes or removes is no longer unreadable.
                const stillUnreadable = unreadable.filter((key) => !touchedSecretKeys.includes(key))
                const blob = patched(current, secretPatch, body.sensitive_config_remove)
                if (!sameJson(blob, current) || stillUnreadable.length !== unreadable.length) {
                    newSecret = { blob, unreadable: stillUnreadable }
                }
            }

            if (isEmpty(changes) && newSecret === null) {
                this.auditReads(caller, 'read', [row])
                return row
            }
            const updated = await updateIntegration(tx, teamOwner, { id: row.id }, row.version, changes)
            if (updated.status !== 'ok') {
                throw new Error(`patch of a locked row returned ${updated.status}`)
            }
            if (newSecret !== null) {
                if (isEmpty(newSecret.blob) && newSecret.unreadable.length === 0) {
                    await deleteSecret(tx, row.id)
                } else {
                    await putSecret(tx, row.id, await this.seal(row, newSecret.blob), newSecret.unreadable)
                }
            }
            await this.writeAudit(tx, committed, [
                this.auditEntry(caller, 'update', updated.row, 'ok', newSecret === null ? [] : touchedSecretKeys, {
                    changed: Object.keys(changes).sort(),
                }),
            ])
            return updated.row
        })
        logAuditEntries(committed)
        return result
    }

    /** Soft-deletes the row and removes its secret, so a deleted credential can never be resolved. */
    async delete(caller: Caller, refText: string, ifMatch: number | null): Promise<void> {
        const teamOwner = owner(caller)
        const ref = parseRef(refText)
        const committed: AuditEntry[] = []
        await withTransaction(this.deps.pool, async (tx) => {
            const row = await lockIntegration(tx, teamOwner, ref)
            if (!row) {
                throw notFound(refText)
            }
            assertRowAllowed(caller.auth, row)
            if (ifMatch !== null && row.version !== ifMatch) {
                throw versionMismatch(row.version)
            }
            const deleted = await softDeleteIntegration(tx, teamOwner, { id: row.id })
            if (deleted.status !== 'ok') {
                throw new Error(`delete of a locked row returned ${deleted.status}`)
            }
            await deleteSecret(tx, row.id)
            await this.writeAudit(tx, committed, [this.auditEntry(caller, 'delete', deleted.row, 'ok')])
        })
        logAuditEntries(committed)
    }

    async resolve(caller: Caller, refs: readonly string[]): Promise<ResolveResult> {
        const teamOwner = owner(caller)
        // One snapshot for both reads, so a write that commits between them cannot pair new
        // secrets with an old row, or a deleted row with no secret.
        const { found, missing, rows, secrets } = await withTransaction(this.deps.pool, async (tx) => {
            await tx.query('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
            const byRef = await this.rowsByRef(caller, refs, tx)
            const unique = uniqueRows(byRef.found)
            const stored = await getSecrets(
                tx,
                teamOwner,
                unique.map((row) => row.id)
            )
            return { ...byRef, rows: unique, secrets: stored }
        })

        type Outcome = { credentials: JsonObject } | { error: IntegrationApiError }
        const outcomes = new Map<string, Outcome>()
        await forEachLimit(rows, DECRYPT_CONCURRENCY, async (row) => {
            const stored = secrets.get(row.id)
            if (stored && stored.legacyUnreadableKeys.length > 0) {
                outcomes.set(row.id, { error: unreadableSecret({ keys: stored.legacyUnreadableKeys }) })
                return
            }
            try {
                const blob = stored ? await this.open(row, stored) : {}
                outcomes.set(row.id, { credentials: exposedCredentials(row.authType, blob) })
            } catch (err) {
                // A KMS outage fails the whole request below. A bad row fails only its own ref.
                if (err instanceof IntegrationApiError && err.code === 'unreadable_secret') {
                    outcomes.set(row.id, { error: err })
                    return
                }
                throw err
            }
        })

        const result: ResolveResult = { records: {}, missing, errors: {} }
        for (const [ref, row] of found) {
            const outcome = outcomes.get(row.id)
            if (!outcome) {
                continue
            }
            if ('error' in outcome) {
                result.errors[ref] = {
                    code: 'unreadable_secret',
                    message: outcome.error.message,
                    details: outcome.error.details,
                }
            } else {
                result.records[ref] = {
                    record: toRecordJson(row),
                    credentials: outcome.credentials,
                    expires_at: tokenExpiresAt(row),
                }
            }
        }
        this.deps.audit.enqueue(
            rows.map((row) => {
                const outcome = outcomes.get(row.id)
                return outcome && 'credentials' in outcome
                    ? this.auditEntry(caller, 'resolve', row, 'ok', Object.keys(outcome.credentials))
                    : this.auditEntry(caller, 'resolve', row, 'unreadable_secret')
            })
        )
        return result
    }

    async listAcrossTeams(caller: Caller, body: CrossTeamBody): Promise<RecordPage> {
        const authTypes = body.auth_types?.map(checkAuthType) ?? null
        const page = await listIntegrationsAcrossTeams(
            this.deps.pool,
            {
                kinds: listKinds(caller.auth, body.source_rows, body.kinds),
                authTypes,
                externalId: body.external_id,
                sourceRows: body.source_rows,
                where: body.where,
                whereIn: body.where_in,
                whereIexact: body.where_iexact,
                hasConfigKey: body.has_config_key,
                teamIds: body.team_ids,
                excludeTeamIds: body.exclude_team_ids,
                createdByIds: body.created_by_ids,
            },
            this.pageRequest(body.limit, body.newest_first, body.after)
        )
        return this.readPage(caller, 'list_across_teams', page)
    }

    private pageRequest(limit: number, newestFirst: boolean, after: string | null): PageRequest {
        return { limit, newestFirst, after: decodeCursor(after) }
    }

    private readPage(caller: Caller, operation: string, page: Page): RecordPage {
        this.auditReads(caller, operation, page.rows)
        return { results: page.rows.map(toRecordJson), next: encodeCursor(page.next) }
    }

    /** The owner's rows for each ref, and the refs with no live row. Fails on a kind the token does not allow. */
    private async rowsByRef(
        caller: Caller,
        refs: readonly string[],
        db: Queryable = this.deps.pool
    ): Promise<{ found: Map<string, IntegrationRow>; missing: string[] }> {
        const unique = [...new Set(refs)]
        const rows = await getIntegrationsByRefs(db, owner(caller), unique.map(parseRef))
        const byRef = new Map<string, IntegrationRow>()
        for (const row of rows) {
            byRef.set(row.id, row)
            if (row.legacyId !== null) {
                byRef.set(String(row.legacyId), row)
            }
        }
        const found = new Map<string, IntegrationRow>()
        const missing: string[] = []
        for (const ref of unique) {
            const row = byRef.get(ref)
            if (row) {
                assertRowAllowed(caller.auth, row)
                found.set(ref, row)
            } else {
                missing.push(ref)
            }
        }
        return { found, missing }
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

    private async open(row: IntegrationRow, stored: StoredSecret): Promise<JsonObject> {
        try {
            return await this.deps.envelope.open(stored.sealed, encryptionContext(row))
        } catch (err) {
            if (err instanceof KmsError && err.reason === 'unavailable') {
                throw kmsUnavailable()
            }
            if (err instanceof KmsError || err instanceof EnvelopeError) {
                logger.error('integrations:unreadable_secret', { integrationId: row.id, reason: err.reason })
                throw unreadableSecret()
            }
            throw err
        }
    }

    private auditEntry(
        caller: Caller,
        operation: string,
        row: IntegrationRow,
        outcome: string,
        fields: readonly string[] = [],
        details: Record<string, unknown> = {}
    ): AuditEntry {
        return {
            actor: caller.actor,
            operation,
            outcome,
            ownerType: row.ownerType,
            ownerId: row.ownerId,
            integrationId: row.id,
            kind: row.kind,
            fields: [...fields].sort(),
            details,
        }
    }

    /** Stores the rows in the caller's transaction. The caller logs them to stdout after the commit. */
    private async writeAudit(tx: Queryable, committed: AuditEntry[], entries: readonly AuditEntry[]): Promise<void> {
        await insertAuditRows(tx, entries)
        committed.push(...entries)
    }

    private auditReads(caller: Caller, operation: string, rows: readonly IntegrationRow[]): void {
        this.deps.audit.enqueue(rows.map((row) => this.auditEntry(caller, operation, row, 'ok')))
    }
}

function uniqueRows(found: Map<string, IntegrationRow>): IntegrationRow[] {
    return [...new Map([...found.values()].map((row) => [row.id, row])).values()]
}

function versionMismatch(currentVersion: number): IntegrationApiError {
    return new IntegrationApiError('version_mismatch', 'the integration changed since the caller read it', {
        current_version: currentVersion,
    })
}
