// What each `/v1/integrations/*` route does. The routes parse and authorize; this class reads and
// writes rows, seals and opens secrets, and writes the audit trail. Every owner here comes from
// the caller's token.

import { createHash, randomUUID } from 'node:crypto'
import type { Pool, PoolClient } from 'pg'

import { type IntegrationAuth, assertKindAllowed } from '../auth/integrations'
import { type JsonObject, type JsonValue, canonicalJson } from '../crypto/canonical'
import type { Envelope, SealedSecret } from '../crypto/envelope'
import { EnvelopeError, KmsError } from '../crypto/types'
import { claimIdempotencyKey, recordIdempotencyResult } from '../db/idempotency'
import {
    type ChangeCursor,
    type ListCursor,
    type Page,
    type PageRequest,
    getIntegrationsByRefs,
    listChangedIntegrations,
    listIntegrations,
    listIntegrationsAcrossTeams,
    lockIntegration,
    lockIntegrationByKey,
    lockIntegrationsByExternalId,
    softDeleteOwnerBatch,
    type SourceRows,
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
import { type StoredSecret, deleteSecret, deleteSecrets, getSecrets, getSecretsOf, putSecret } from '../db/secrets'
import { withTransaction } from '../db/transaction'
import { logger } from '../lib/logging'
import { type AuditActor, type AuditEntry, type AuditQueue, insertAuditRows, logAuditEntries } from './audit'
import { IntegrationApiError, notFound } from './errors'
import { assertIdentityUnchanged } from './identity'
import { type IntegrationRecordJson, exposedCredentials, toRecordJson, tokenExpiresAt } from './record'
import {
    type ChangesQuery,
    type CrossTeamBody,
    type ExternalIdListQuery,
    type ExternalIdTarget,
    type ListQuery,
    type NewIntegrationBody,
    type PatchBody,
    checkAuthType,
    parseRef,
} from './validation'

const DECRYPT_CONCURRENCY = 16
const OWNER_DELETE_BATCH = 500
// See `listChangedIntegrations`: the longest write transaction the change feed can wait out.
const DEFAULT_CHANGES_SETTLE_SECONDS = 30
// A write may wait for locks and call KMS. It rolls back once it runs this long, so it commits
// well inside the settle window and the change feed cannot skip it.
const WRITE_DEADLINE_MS = 20_000
const IDEMPOTENT_CREATE = 'create'
// The text form Postgres prints for a timestamptz, as the list cursor carries it.
const CURSOR_TIMESTAMP = /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(\.\d{1,6})?[+-]\d{2}(:\d{2}){0,2}$/
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/

export interface IntegrationsDeps {
    pool: Pool
    envelope: Envelope
    audit: AuditQueue
    /** How old a change must be before the change feed returns it. Tests shorten it. */
    changesSettleSeconds?: number
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

/** One row of the change feed. `secret` is the whole blob, refresh token included. */
export interface ChangeItem {
    record: IntegrationRecordJson
    deleted: boolean
    updated_at: string
    /** The current blob. `{}` when the row has no secret or is deleted. Null only with `secret_error`. */
    secret: JsonObject | null
    /** Keys of a migrated blob that could not be decrypted. They are not in `secret`. */
    secret_unreadable_keys: string[]
    /** Set when the secret cannot be opened. */
    secret_error: 'unreadable_secret' | null
}

export interface ChangePage {
    results: ChangeItem[]
    /** The `since` of the next call. It equals the request's `since` when nothing changed. */
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

function writeDeadline(): () => void {
    const deadline = Date.now() + WRITE_DEADLINE_MS
    return () => {
        if (Date.now() > deadline) {
            throw new Error(`write ran past ${WRITE_DEADLINE_MS} ms and was rolled back`)
        }
    }
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
    const cursor = decodeKeyset(value)
    return cursor === null ? null : { createdAt: cursor.timestamp, id: cursor.id }
}

function decodeKeyset(value: string | null): { timestamp: string; id: string } | null {
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
    return { timestamp: parsed[0], id: parsed[1] }
}

function encodeChangeCursor(cursor: ChangeCursor): string {
    return Buffer.from(JSON.stringify([cursor.updatedAt, cursor.id])).toString('base64url')
}

function decodeChangeCursor(value: string | null): ChangeCursor | null {
    const cursor = decodeKeyset(value)
    return cursor === null ? null : { updatedAt: cursor.timestamp, id: cursor.id }
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
        const result = await this.writeTransaction(async (tx) => {
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

        const result = await this.writeTransaction(async (tx) => {
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

        const committed: AuditEntry[] = []
        const result = await this.writeTransaction(async (tx) => {
            const row = await lockIntegration(tx, teamOwner, ref)
            if (!row) {
                throw notFound(refText)
            }
            assertRowAllowed(caller.auth, row)
            if (ifMatch !== null && row.version !== ifMatch) {
                throw versionMismatch(row.version)
            }
            const applied = await this.applyPatch(tx, row, body)
            if (applied === null) {
                this.auditReads(caller, 'read', [row])
                return row
            }
            await this.writeAudit(tx, committed, [
                this.auditEntry(caller, 'update', applied.row, 'ok', applied.secretKeys, { changed: applied.changed }),
            ])
            return applied.row
        })
        logAuditEntries(committed)
        return result
    }

    /**
     * Applies the patch to a locked row, in the caller's transaction. Returns null when the patch
     * changes nothing, and then writes nothing.
     */
    private async applyPatch(
        tx: PoolClient,
        row: IntegrationRow,
        body: PatchBody
    ): Promise<{ row: IntegrationRow; changed: string[]; secretKeys: string[] } | null> {
        const rowOwner: IntegrationOwner = { type: row.ownerType, id: row.ownerId }
        const secretPatch = body.sensitive_config_patch as JsonObject
        const touchedSecretKeys = [...new Set([...Object.keys(secretPatch), ...body.sensitive_config_remove])].sort()

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
            const stored = (await getSecrets(tx, rowOwner, [row.id])).get(row.id)
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
            return null
        }
        const updated = await updateIntegration(tx, rowOwner, { id: row.id }, row.version, changes)
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
        return {
            row: updated.row,
            changed: Object.keys(changes).sort(),
            secretKeys: newSecret === null ? [] : touchedSecretKeys,
        }
    }

    /** Soft-deletes the row and removes its secret, so a deleted credential can never be resolved. */
    async delete(caller: Caller, refText: string, ifMatch: number | null): Promise<void> {
        const teamOwner = owner(caller)
        const ref = parseRef(refText)
        const committed: AuditEntry[] = []
        await this.writeTransaction(async (tx) => {
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

    /** The rows of every team with this kind and external id. Needs the `read_by_external_id` op. */
    async listByExternalId(caller: Caller, target: ExternalIdTarget, query: ExternalIdListQuery): Promise<RecordPage> {
        const page = await listIntegrationsAcrossTeams(
            this.deps.pool,
            {
                kinds: listKinds(caller.auth, query.sourceRows, [target.kind]),
                authTypes: null,
                externalId: target.externalId,
                sourceRows: query.sourceRows,
                where: {},
                whereIn: {},
                whereIexact: {},
                hasConfigKey: null,
                teamIds: query.teamIds,
                excludeTeamIds: [],
                createdByIds: null,
            },
            this.pageRequest(query.limit, false, query.after)
        )
        return this.readPage(caller, 'read_by_external_id', page)
    }

    /**
     * Applies the patch to the rows of every team with this kind and external id, in one
     * transaction. Audits every matched row: `ok` when it changed, `unchanged` when it did not.
     */
    async patchByExternalId(
        caller: Caller,
        target: ExternalIdTarget,
        body: PatchBody,
        sourceRows: SourceRows
    ): Promise<{ matched: number; updated: number }> {
        // Throws when the token has no grant for the source rows this call selects.
        listKinds(caller.auth, sourceRows, [target.kind])
        const committed: AuditEntry[] = []
        const result = await this.writeTransaction(async (tx, checkDeadline) => {
            const rows = await lockIntegrationsByExternalId(tx, target.kind, target.externalId, sourceRows)
            const entries: AuditEntry[] = []
            let updated = 0
            for (const row of rows) {
                checkDeadline()
                const applied = await this.applyPatch(tx, row, body)
                if (applied === null) {
                    entries.push(this.auditEntry(caller, 'write_by_external_id', row, 'unchanged'))
                    continue
                }
                updated += 1
                entries.push(
                    this.auditEntry(caller, 'write_by_external_id', applied.row, 'ok', applied.secretKeys, {
                        changed: applied.changed,
                    })
                )
            }
            await this.writeAudit(tx, committed, entries)
            return { matched: rows.length, updated }
        })
        logAuditEntries(committed)
        return result
    }

    /** Soft-deletes the rows of every team with this kind and external id, and their secrets, in one transaction. */
    async deleteByExternalId(
        caller: Caller,
        target: ExternalIdTarget,
        sourceRows: SourceRows
    ): Promise<{ deleted: number }> {
        // Throws when the token has no grant for the source rows this call selects.
        listKinds(caller.auth, sourceRows, [target.kind])
        const committed: AuditEntry[] = []
        const result = await this.writeTransaction(async (tx, checkDeadline) => {
            const rows = await lockIntegrationsByExternalId(tx, target.kind, target.externalId, sourceRows)
            const entries: AuditEntry[] = []
            for (const row of rows) {
                checkDeadline()
                const deleted = await softDeleteIntegration(
                    tx,
                    { type: row.ownerType, id: row.ownerId },
                    { id: row.id }
                )
                if (deleted.status !== 'ok') {
                    throw new Error(`delete of a locked row returned ${deleted.status}`)
                }
                entries.push(this.auditEntry(caller, 'delete_by_external_id', deleted.row, 'ok'))
            }
            await deleteSecrets(
                tx,
                rows.map((row) => row.id)
            )
            await this.writeAudit(tx, committed, entries)
            return { deleted: rows.length }
        })
        logAuditEntries(committed)
        return result
    }

    /**
     * Soft-deletes every live row of the token's owner and removes their secrets, `OWNER_DELETE_BATCH`
     * rows per transaction. A second call finds nothing and returns zero, so a retry after a failure
     * is safe. The token must not narrow by kind or ref, because the delete takes the whole owner.
     */
    async deleteOwner(caller: Caller, ownerId: number): Promise<{ deleted: number }> {
        const teamOwner = owner(caller)
        if (teamOwner.id !== ownerId) {
            throw new IntegrationApiError('forbidden_op', 'the owner of the request is not the owner of the token')
        }
        if (caller.auth.kinds !== null) {
            throw new IntegrationApiError('forbidden_kind', 'a token that narrows by kind cannot delete an owner')
        }

        let deleted = 0
        for (;;) {
            const committed: AuditEntry[] = []
            const batch = await this.writeTransaction(async (tx) => {
                const rows = await softDeleteOwnerBatch(tx, teamOwner, OWNER_DELETE_BATCH)
                await deleteSecrets(
                    tx,
                    rows.map((row) => row.id)
                )
                await this.writeAudit(
                    tx,
                    committed,
                    rows.map((row) => this.auditEntry(caller, 'delete_owner', row, 'ok'))
                )
                return rows.length
            })
            logAuditEntries(committed)
            deleted += batch
            if (batch < OWNER_DELETE_BATCH) {
                break
            }
        }
        await this.deps.pool.query(`DELETE FROM idempotency_keys WHERE owner_type = $1 AND owner_id = $2`, [
            teamOwner.type,
            teamOwner.id,
        ])
        return { deleted }
    }

    /**
     * The rows of every team that changed after `since`, oldest change first, deleted rows included.
     * Unlike every other read, it returns decrypted secrets: the whole blob, `refresh_token` and
     * `client_secret` too, for each live row on the page. The Django reverse sync
     * needs the refreshed tokens, and only it may call this (the web deployment). The audit rows
     * are written before the response is built, so a page that cannot be audited is not returned.
     */
    async changes(caller: Caller, query: ChangesQuery): Promise<ChangePage> {
        const after = decodeChangeCursor(query.since)
        // One snapshot for both reads, so a write that commits between them cannot pair a new
        // secret with an old record, or a deleted row with no secret.
        const { changed, secrets } = await withTransaction(this.deps.pool, async (tx) => {
            await tx.query('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
            const rows = await listChangedIntegrations(tx, {
                // A token that names kinds sees only those, even when the request names none.
                kinds: query.kinds ?? caller.auth.kinds,
                after,
                limit: query.limit,
                settleSeconds: this.deps.changesSettleSeconds ?? DEFAULT_CHANGES_SETTLE_SECONDS,
            })
            const live = rows.filter(({ row }) => row.deletedAt === null).map(({ row }) => row.id)
            // Every live row carries its current secret. A secret that changed before the cursor can
            // sit on a row that changed again after it, so the reader cannot tell from the cursor alone.
            return { changed: rows, secrets: await getSecretsOf(tx, live) }
        })

        const outcomes = new Map<string, Awaited<ReturnType<IntegrationsService['changeSecret']>>>()
        await forEachLimit(changed, DECRYPT_CONCURRENCY, async ({ row }) => {
            outcomes.set(row.id, await this.changeSecret(row, secrets))
        })

        const items: ChangeItem[] = []
        const entries: AuditEntry[] = []
        for (const { row } of changed) {
            const outcome = outcomes.get(row.id)!
            items.push({
                record: toRecordJson(row),
                deleted: row.deletedAt !== null,
                updated_at: row.updatedAt.toISOString(),
                ...outcome,
            })
            entries.push(
                this.auditEntry(
                    caller,
                    'reverse_sync',
                    row,
                    outcome.secret_error ?? 'ok',
                    outcome.secret === null ? [] : Object.keys(outcome.secret),
                    { deleted: row.deletedAt !== null }
                )
            )
        }
        await insertAuditRows(this.deps.pool, entries)
        logAuditEntries(entries)

        const last = changed[changed.length - 1]
        return {
            results: items,
            next: last ? encodeChangeCursor(last.cursor) : query.since,
        }
    }

    private async changeSecret(
        row: IntegrationRow,
        secrets: Map<string, StoredSecret>
    ): Promise<Pick<ChangeItem, 'secret' | 'secret_unreadable_keys' | 'secret_error'>> {
        const stored = row.deletedAt === null ? secrets.get(row.id) : undefined
        if (!stored) {
            return { secret: {}, secret_unreadable_keys: [], secret_error: null }
        }
        try {
            return {
                secret: await this.open(row, stored),
                secret_unreadable_keys: stored.legacyUnreadableKeys,
                secret_error: null,
            }
        } catch (err) {
            // A KMS outage fails the page, so the poller retries. A bad row must not stop the feed.
            if (err instanceof IntegrationApiError && err.code === 'unreadable_secret') {
                return {
                    secret: null,
                    secret_unreadable_keys: stored.legacyUnreadableKeys,
                    secret_error: 'unreadable_secret',
                }
            }
            throw err
        }
    }

    /** A write transaction that rolls back once it runs past `WRITE_DEADLINE_MS`. See `listChangedIntegrations`. */
    private writeTransaction<T>(fn: (tx: PoolClient, checkDeadline: () => void) => Promise<T>): Promise<T> {
        const checkDeadline = writeDeadline()
        return withTransaction(this.deps.pool, async (tx) => {
            const result = await fn(tx, checkDeadline)
            checkDeadline()
            return result
        })
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
