// `POST /v1/integrations/mirror/digests`: a salted content digest of each mirrored row, so the
// Django reconcile job can compare its rows with the copies here. The response carries digests
// and row metadata only. No plaintext, config or secret, leaves the service.

import type { Pool } from 'pg'

import { assertKindAllowed } from '../auth/integrations'
import type { JsonObject } from '../crypto/canonical'
import type { Envelope } from '../crypto/envelope'
import { type MirrorRow, listMirroredForDigest } from '../db/mirror'
import { type StoredSecret, getSecretsOf } from '../db/secrets'
import { withTransaction } from '../db/transaction'
import { type AuditEntry, insertAuditRows, logAuditEntries } from './audit'
import { contentDigest } from './digest'
import { IntegrationApiError } from './errors'
import { mirrorDigestRowsTotal } from './metrics'
import { type Caller, DECRYPT_CONCURRENCY, forEachLimit, openSecret } from './service'
import type { MirrorDigestsBody } from './validation'

export interface DigestResult {
    legacy_id: number
    team_id: number
    kind: string
    deleted: boolean
    source_version: number
    created_by_id: number | null
    /** Lowercase hex. Null for a deleted row and for a secret that cannot be read. */
    digest: string | null
    digest_error: 'unreadable_secret' | null
}

export interface DigestPage {
    results: DigestResult[]
    /** The `after_legacy_id` of the next page. Null on the last page and in `legacy_ids` mode. */
    next_after_legacy_id: number | null
}

type DigestOutcome = { digest: string; keys: readonly string[] } | { digest: null; error: 'unreadable_secret' | null }

export interface MirrorDigestDeps {
    pool: Pool
    envelope: Envelope
}

export async function mirrorDigests(
    deps: MirrorDigestDeps,
    caller: Caller,
    body: MirrorDigestsBody
): Promise<DigestPage> {
    // One snapshot for both reads, so a write that commits between them cannot pair a new secret
    // with an old row.
    const { rows, hasMore, secrets } = await withTransaction(deps.pool, async (tx) => {
        await tx.query('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        const found = await listMirroredForDigest(tx, {
            kind: body.kind,
            afterLegacyId: body.after_legacy_id,
            // One extra row tells whether another page follows.
            limit: body.limit + 1,
            legacyIds: body.legacy_ids,
        })
        const more = body.legacy_ids === null && found.length > body.limit
        const page = more ? found.slice(0, body.limit) : found
        for (const row of page) {
            assertKindAllowed(caller.auth, row.kind, { sourceRow: row.isSourceRow })
        }
        const live = page.filter((row) => row.deletedAt === null).map((row) => row.id)
        return { rows: page, hasMore: more, secrets: await getSecretsOf(tx, live) }
    })

    const outcomes = new Map<string, DigestOutcome>()
    await forEachLimit(rows, DECRYPT_CONCURRENCY, async (row) => {
        outcomes.set(row.id, await digestRow(deps.envelope, body.salt, row, secrets.get(row.id)))
    })

    const results: DigestResult[] = []
    const fields = new Set<string>()
    for (const row of rows) {
        const outcome = outcomes.get(row.id)!
        if (outcome.digest !== null) {
            outcome.keys.forEach((key) => fields.add(key))
        }
        mirrorDigestRowsTotal
            .labels({ outcome: outcome.digest !== null ? 'digest' : (outcome.error ?? 'deleted') })
            .inc()
        results.push({
            legacy_id: row.legacyId!,
            team_id: row.ownerId,
            kind: row.kind,
            deleted: row.deletedAt !== null,
            source_version: row.sourceVersion!,
            created_by_id: row.createdById,
            digest: outcome.digest,
            digest_error: outcome.digest === null ? outcome.error : null,
        })
    }

    // One audit row per page, not per row: the page reads many teams, and a reconcile pass reads
    // every mirrored row. The row names the kind and the legacy id range, so the rows it read can be
    // found again. It is written before the response is built, so a page that cannot be audited is
    // not returned.
    const entry: AuditEntry = {
        actor: caller.actor,
        occurredAt: new Date(),
        operation: 'reconcile',
        outcome: 'ok',
        ownerType: null,
        ownerId: null,
        integrationId: null,
        kind: body.kind,
        fields: [...fields].sort(),
        details: {
            kind: body.kind,
            mode: body.legacy_ids === null ? 'page' : 'legacy_ids',
            rows: results.length,
            first_legacy_id: results[0]?.legacy_id ?? null,
            last_legacy_id: results[results.length - 1]?.legacy_id ?? null,
        },
    }
    await insertAuditRows(deps.pool, [entry])
    logAuditEntries([entry])

    return {
        results,
        next_after_legacy_id: hasMore ? (results[results.length - 1]?.legacy_id ?? null) : null,
    }
}

async function digestRow(
    envelope: Envelope,
    salt: Buffer,
    row: MirrorRow,
    stored: StoredSecret | undefined
): Promise<DigestOutcome> {
    if (row.deletedAt !== null) {
        return { digest: null, error: null }
    }
    let sensitiveConfig: JsonObject = {}
    if (stored) {
        try {
            sensitiveConfig = await openSecret(envelope, row, stored)
        } catch (err) {
            // A KMS outage fails the page, so the caller retries. A bad row must not stop the pass.
            if (err instanceof IntegrationApiError && err.code === 'unreadable_secret') {
                return { digest: null, error: 'unreadable_secret' }
            }
            throw err
        }
    }
    const unreadableKeys = stored?.legacyUnreadableKeys ?? []
    const digest = contentDigest(salt, {
        config: row.config as JsonObject,
        errors: row.errors,
        externalId: row.externalId,
        sensitiveConfig,
        unreadableKeys,
    })
    return { digest, keys: [...Object.keys(sensitiveConfig), ...unreadableKeys] }
}
