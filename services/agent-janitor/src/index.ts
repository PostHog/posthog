/**
 * Janitor entrypoint. Single-process: HTTP server + periodic sweep timer.
 *
 * Two Postgres pools (matches runner + ingress):
 *   - posthogDb (POSTHOG_DB_URL): Django-owned agent_application + agent_revision.
 *     The revision store reads from here so /revisions/* HTTP endpoints
 *     can resolve revisions.
 *   - agentDb (AGENT_DB_URL): queue + sandbox-instances; janitor sweep
 *     reaps stuck rows here.
 *
 * Bundle storage: S3-backed via `S3BundleStore` (AGENT_BUNDLE_S3_BUCKET +
 * endpoint required at boot). Dev runs SeaweedFS; prod uses real S3 with the
 * pod's IRSA role for credentials. `FsBundleStore` is kept around for the
 * agent-tests harness only.
 *
 * Run via `tsx src/index.ts` (no precompile).
 */

import pg from 'pg'
const { Pool } = pg

import { S3Client } from '@aws-sdk/client-s3'

import { migrate } from '@posthog/agent-migrations'
import {
    createLogger,
    installProcessHandlers,
    MemoryStore,
    PgRevisionStore,
    PgSessionQueue,
    S3BundleStore,
    S3MemoryStore,
} from '@posthog/agent-shared'

import { loadAgentJanitorConfig } from './config'
import { cronTick, newCronTickState } from './cron-tick'
import { buildJanitorApp } from './server'
import { sweepOnce } from './sweep'

const log = createLogger('agent-janitor')

async function main(): Promise<void> {
    installProcessHandlers(log)
    const config = loadAgentJanitorConfig()

    // S3 bundle storage is required — the authoring API publishes new
    // revisions through this store. Fail-fast at boot rather than 503-ing
    // every bundle CRUD call individually. Endpoint is optional — unset
    // means "use the AWS SDK's regional default" (prod path); SeaweedFS in
    // dev sets it explicitly.
    if (!config.bundleS3Bucket) {
        throw new Error(
            'AGENT_BUNDLE_S3_BUCKET must be set — the janitor cannot serve bundle endpoints without storage.'
        )
    }
    const bundleS3 = new S3Client({
        endpoint: config.bundleS3Endpoint,
        region: config.bundleS3Region,
        forcePathStyle: config.bundleS3Endpoint ? config.bundleS3ForcePathStyle : false,
        credentials:
            config.bundleS3AccessKeyId && config.bundleS3SecretAccessKey
                ? {
                      accessKeyId: config.bundleS3AccessKeyId,
                      secretAccessKey: config.bundleS3SecretAccessKey,
                  }
                : undefined,
    })
    const bundles = new S3BundleStore({
        client: bundleS3,
        bucket: config.bundleS3Bucket,
        bucketPrefix: config.bundleS3Prefix,
    })

    const posthogDb = new Pool({ connectionString: config.posthogDbUrl })
    const agentDb = new Pool({ connectionString: config.agentDbUrl })
    // Belt-and-braces in dev; in prod this is also run as a one-shot
    // job before the service starts (bin/migrate --scope=agent_runtime).
    // Idempotent — no-op when everything is already applied.
    await migrate({ databaseUrl: config.agentDbUrl })

    const queue = new PgSessionQueue(agentDb)
    const revisions = new PgRevisionStore(posthogDb)

    const sweep = {
        queue,
        stuckRunningThresholdMs: config.stuckRunningMs,
        stuckWaitingThresholdMs: config.stuckWaitingMs,
        idleCompletedThresholdMs: config.idleCompletedMs,
        idempotencyKeyTtlMs: config.idempotencyKeyTtlMs,
        maxRetries: config.maxRetries,
        // Pull idle completed candidates past the floor TTL; the sweep then
        // checks per-agent `spec.resume.max_completed_age_ms` before closing.
        listIdleCompletedCandidates: () => queue.listIdleCompleted(config.idleCompletedMs),
        // Per-agent TTL lookup — `spec.resume.max_completed_age_ms` defers
        // close for agents that opt in via spec.
        getResumeConfig: async (s: { revision_id: string }) => {
            const rev = await revisions.getRevision(s.revision_id)
            return rev?.spec?.resume
        },
    }
    // S3-backed memory store. Unset bucket/endpoint disables the
    // /memory/* endpoints (503), keeping local dev that hasn't wired
    // SeaweedFS bootable.
    let memoryStore: MemoryStore | undefined
    if (config.memoryS3Bucket && config.memoryS3Endpoint) {
        const s3 = new S3Client({
            endpoint: config.memoryS3Endpoint,
            region: config.memoryS3Region,
            forcePathStyle: config.memoryS3ForcePathStyle,
            credentials:
                config.memoryS3AccessKeyId && config.memoryS3SecretAccessKey
                    ? {
                          accessKeyId: config.memoryS3AccessKeyId,
                          secretAccessKey: config.memoryS3SecretAccessKey,
                      }
                    : undefined,
        })
        memoryStore = new S3MemoryStore({
            client: s3,
            bucket: config.memoryS3Bucket,
            bucketPrefix: config.memoryS3Prefix,
        })
        log.info(
            { bucket: config.memoryS3Bucket, endpoint: config.memoryS3Endpoint, prefix: config.memoryS3Prefix },
            'memory.s3.enabled'
        )
    } else {
        log.warn({}, 'memory.s3.disabled — set AGENT_MEMORY_S3_BUCKET + AGENT_MEMORY_S3_ENDPOINT to enable')
    }

    const app = buildJanitorApp({
        queue,
        sweep,
        revisions,
        bundles,
        memoryStore,
        internalSecret: config.internalSecret,
    })
    app.listen(config.port, () => {
        log.info({ port: config.port }, 'listening')
    })

    // Cron tick state lives in-process — restart resets `lastTickAt`, the
    // catch-up policy handles missed firings, the unique index on
    // `(application_id, idempotency_key)` keeps two janitor replicas from
    // double-firing. See `cron-tick.ts` for the contract.
    const cronTickState = newCronTickState()
    const cronTickDeps = { revisions, queue }

    setInterval(async () => {
        // Sweep + cron tick run on the same interval but as independent
        // promises — a slow cron tick (cron-parser parsing a pathological
        // schedule, a slow listLiveCronRevisions roundtrip) doesn't starve
        // the sweep, and vice versa. Both wrap their own try/catch so a
        // single throw can't take the loop down.
        await Promise.all([
            (async () => {
                try {
                    const result = await sweepOnce(sweep)
                    log.debug({ ...result }, 'sweep.done')
                } catch (err) {
                    log.error({ err: (err as Error).message, stack: (err as Error).stack }, 'sweep.failed')
                }
            })(),
            (async () => {
                try {
                    const result = await cronTick(cronTickDeps, cronTickState)
                    if (result.fired > 0 || result.errors > 0) {
                        log.info({ ...result }, 'cron_tick.done')
                    } else {
                        log.debug({ ...result }, 'cron_tick.done')
                    }
                } catch (err) {
                    log.error({ err: (err as Error).message, stack: (err as Error).stack }, 'cron_tick.failed')
                }
            })(),
        ])
    }, config.sweepIntervalMs)
}

if (import.meta.url === `file://${process.argv[1]}`) {
    main().catch((err) => {
        log.fatal({ err: (err as Error).message, stack: (err as Error).stack }, 'fatal')
        process.exit(1)
    })
}
