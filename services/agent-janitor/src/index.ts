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

import { migrate } from '@posthog/agent-migrations'
import {
    createLogger,
    FsBundleStore,
    HttpGatewayClient,
    installProcessHandlers,
    PgRevisionStore,
    PgSessionQueue,
    PgTeamApiKeyResolver,
} from '@posthog/agent-shared'

import { loadAgentJanitorConfig } from './config'
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
    // walletProxy resolves the agent's owner team to a phc_ and forwards
    // to the llm-gateway's GET /v1/wallet/balance. The route on the
    // janitor (/applications/:id/wallet) lights up only when the URL is
    // configured; unset → 503 with `wallet_proxy_not_configured`.
    let walletProxy:
        | ((teamId: number) => Promise<{ available_usd: string; pending_usd: string; currency: string }>)
        | undefined
    if (config.llmGatewayUrl) {
        const teamApiKeys = new PgTeamApiKeyResolver(posthogDb)
        const gateway = new HttpGatewayClient({ baseUrl: config.llmGatewayUrl })
        walletProxy = async (teamId) => {
            const phc = await teamApiKeys.resolve(teamId)
            const bal = await gateway.getWalletBalance({ phc })
            return { available_usd: bal.available_usd, pending_usd: bal.pending_usd, currency: bal.currency }
        }
    }

    const app = buildJanitorApp({
        queue,
        sweep,
        revisions,
        bundles,
        walletProxy,
        internalSecret: config.internalSecret,
    })
    app.listen(config.port, () => {
        log.info({ port: config.port }, 'listening')
    })

    setInterval(async () => {
        try {
            const result = await sweepOnce(sweep)
            log.debug({ ...result }, 'sweep.done')
        } catch (err) {
            log.error({ err: (err as Error).message, stack: (err as Error).stack }, 'sweep.failed')
        }
    }, config.sweepIntervalMs)
}

if (import.meta.url === `file://${process.argv[1]}`) {
    main().catch((err) => {
        log.fatal({ err: (err as Error).message, stack: (err as Error).stack }, 'fatal')
        process.exit(1)
    })
}
