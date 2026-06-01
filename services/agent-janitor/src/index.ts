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
 * Bundle storage: filesystem at AGENT_BUNDLE_ROOT in dev, swappable to S3
 * in prod once the S3 BundleStore impl is wired.
 *
 * Run via `tsx src/index.ts` (no precompile).
 */

import { mkdir } from 'node:fs/promises'
import pg from 'pg'
const { Pool } = pg

import { S3Client } from '@aws-sdk/client-s3'

import { migrate } from '@posthog/agent-migrations'
import {
    createLogger,
    FsBundleStore,
    installProcessHandlers,
    MemoryStore,
    PgRevisionStore,
    PgSessionQueue,
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
    await mkdir(config.bundleRoot, { recursive: true })

    const posthogDb = new Pool({ connectionString: config.posthogDbUrl })
    const agentDb = new Pool({ connectionString: config.agentDbUrl })
    // Belt-and-braces in dev; in prod this is also run as a one-shot
    // job before the service starts (bin/migrate --scope=agent_runtime).
    // Idempotent — no-op when everything is already applied.
    await migrate({ databaseUrl: config.agentDbUrl })

    const queue = new PgSessionQueue(agentDb)
    const revisions = new PgRevisionStore(posthogDb)
    const bundles = new FsBundleStore(config.bundleRoot)

    const sweep = {
        queue,
        stuckRunningThresholdMs: config.stuckRunningMs,
        stuckWaitingThresholdMs: config.stuckWaitingMs,
        idleCompletedThresholdMs: config.idleCompletedMs,
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
    // MinIO bootable.
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
