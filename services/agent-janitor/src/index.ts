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

import { S3Client } from '@aws-sdk/client-s3'

import {
    createAgentPool,
    createLogger,
    createModalSandboxTerminator,
    installProcessHandlers,
    MemoryStore,
    MultiBackendSandboxTerminator,
    PgApprovalStore,
    PgRevisionStore,
    PgSandboxInstanceStore,
    PgSessionQueue,
    S3BundleStore,
    S3JsonlTabularStore,
    S3MemoryStore,
    TabularStore,
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

    const posthogDb = createAgentPool(config.posthogDbUrl)
    const agentDb = createAgentPool(config.agentDbUrl)
    // Schema is owned by `agent-migrator`; the chart runs a one-shot Job
    // (`charts/agent-migrator/`) on every sync. Runtime no longer calls
    // migrate() — runtime roles don't have DDL anyway.

    const queue = new PgSessionQueue(agentDb)
    const revisions = new PgRevisionStore(posthogDb)
    // Approvals: backs both the /approvals/* HTTP surface (decide / list /
    // get for the authoring UI + MCP) and the sweep's expireQueued path.
    // Without it both 503 / silently no-op.
    const approvals = new PgApprovalStore(agentDb)
    // Sandbox-instance log + terminator for the reaper sweep. The
    // terminator's Modal client is constructed lazily inside the multi-
    // backend wrapper — janitors that never see a Modal row pay zero gRPC
    // startup cost. Requires MODAL_TOKEN_ID + MODAL_TOKEN_SECRET in env
    // (same secret_env entries the runner reads).
    const sandboxInstances = new PgSandboxInstanceStore(agentDb)
    const sandboxTerminator = new MultiBackendSandboxTerminator(createModalSandboxTerminator())

    const sweep = {
        queue,
        approvals,
        sandboxInstances,
        sandboxTerminator,
        stuckRunningThresholdMs: config.stuckRunningMs,
        stuckWaitingThresholdMs: config.stuckWaitingMs,
        idleCompletedThresholdMs: config.idleCompletedMs,
        idempotencyKeyTtlMs: config.idempotencyKeyTtlMs,
        maxRetries: config.maxRetries,
        sandboxStaleThresholdMs: config.sandboxStaleMs,
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
    // S3-backed memory store. Required everywhere — no optional fallback that
    // returns 503. Dev wires SeaweedFS via `hogli start` and the platform
    // config dev defaults; prod must set bucket + endpoint explicitly.
    if (!config.memoryS3Bucket || !config.memoryS3Endpoint) {
        throw new Error(
            'AGENT_MEMORY_S3_BUCKET and AGENT_MEMORY_S3_ENDPOINT must both be set — janitor refuses to start without memory storage. Dev: SeaweedFS via `hogli start`. Prod: real S3 / equivalent.'
        )
    }
    const memoryS3 = new S3Client({
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
    const memoryStore: MemoryStore = new S3MemoryStore({
        client: memoryS3,
        bucket: config.memoryS3Bucket,
        bucketPrefix: config.memoryS3Prefix,
    })
    const tabularStore: TabularStore = new S3JsonlTabularStore({
        client: memoryS3,
        bucket: config.memoryS3Bucket,
        bucketPrefix: 'agent_tables',
    })
    log.info(
        { bucket: config.memoryS3Bucket, endpoint: config.memoryS3Endpoint, prefix: config.memoryS3Prefix },
        'memory.s3.enabled'
    )

    const app = buildJanitorApp({
        queue,
        sweep,
        approvals,
        revisions,
        bundles,
        memoryStore,
        tabularStore,
        internalSigningKey: config.internalSigningKey,
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
