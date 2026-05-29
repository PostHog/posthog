/**
 * Long-running worker: claim sessions from the queue, run turns, persist
 * progress after every turn, hand off cleanly on shutdown.
 *
 * Concurrency model — agents are largely I/O-bound (LLM HTTP, tool HTTP,
 * sandbox round-trips), so one worker process keeps up to `maxConcurrency`
 * sessions in flight at once. The loop awaits `Promise.race` on the
 * inflight set when at capacity, so a single finishing session
 * immediately frees one slot and the next claim fires — steady-state,
 * not a fill-and-drain wave. The PG queue's SELECT FOR UPDATE SKIP
 * LOCKED protects against any worker (in this process or any other)
 * double-claiming.
 *
 * Shutdown semantics — `stop()` aborts the shared `shutdownController`:
 *   - in-flight pi-ai calls receive the AbortSignal and cancel cleanly
 *   - `runSession()` returns `state: suspended` for each in-flight session
 *   - state goes back to `queued`; any sibling worker picks it up later
 *
 * pending_inputs is read by `runSession()` at turn start. /send calls land
 * there via the ingress → `queue.appendPendingInput()` path.
 */

import type { Model } from '@earendil-works/pi-ai'

import {
    AgentSession,
    AnalyticsSink,
    ApprovalStore,
    BundleStore,
    createLogger,
    LogSink,
    RevisionStore,
    SandboxInstanceStore,
    SandboxPool,
    SecretBroker,
    SessionEventBus,
    SessionQueue,
} from '@posthog/agent-shared'

import { runSession } from '../loop/run-turn'
import { PiClient, resolveModelCached } from '../models/pi-client'

const log = createLogger('worker')

export interface WorkerDeps {
    queue: SessionQueue
    revisions: RevisionStore
    bundle: BundleStore
    sandboxes: SandboxPool
    pi: PiClient
    broker: SecretBroker
    /** Resolved per-application secrets — wire from the team's encrypted env. */
    resolveSecrets: (session: AgentSession) => Promise<Record<string, string>>
    resolveIntegrations: (
        session: AgentSession
    ) => Promise<Record<string, { kind: string; access_token: string; refresh_token?: string }>>
    /**
     * Resolve a session's spec.model string to a concrete pi-ai Model. Defaults
     * to `resolveModelCached(spec.model)` which works for built-in providers.
     * Override for custom-endpoint models (llm-gateway) or test faux models.
     */
    resolveModel?: (specModel: string) => Model<string>
    /** Per-session API key resolver. Defaults to no override (uses PiAiClient's default). */
    resolveApiKey?: (session: AgentSession) => string | undefined
    /**
     * Optional lifecycle event bus. Runner publishes session_started /
     * turn_started / assistant_text / tool_call / tool_result / completed /
     * waiting / failed events here. Chat `/listen` SSE consumes these.
     */
    bus?: SessionEventBus
    /**
     * Optional structured-log sink. Mirrors the bus events into a
     * persistent store (ClickHouse via Kafka in prod).
     */
    logs?: LogSink
    /**
     * Optional LLM analytics sink. Production wires `KafkaAnalyticsSink`
     * to the dedicated `agent_ai_events` topic. Tests default to noop.
     */
    analytics?: AnalyticsSink
    /**
     * Optional durable sandbox-instance log. When present the worker
     * writes a row at acquire and updates it at release / failure, so a
     * sibling worker or the janitor can reap orphans after a crash.
     * Production wires `PgSandboxInstanceStore`; tests can leave it out.
     */
    sandboxInstances?: SandboxInstanceStore
    /**
     * Max concurrent in-flight sessions per worker process. Default 8.
     * Tune against memory / sandbox-pool size / LLM rate limits.
     */
    maxConcurrency?: number
    /**
     * Set to true when calls go through PostHog's llm-gateway. The runner
     * keeps token counts but drops pi-ai's `cost.*` accumulation — the
     * gateway tracks cost server-side; client-side estimates are unreliable.
     */
    useGatewayCost?: boolean
    /**
     * Approval-gated tools store (see
     * docs/agent-platform/plans/approval-gated-tools.md). Required for
     * `requires_approval` in spec.tools to do anything — when absent the
     * dispatcher behaves as if no tools were gated.
     */
    approvals?: ApprovalStore
    /**
     * Builds the deep link the synthetic queued tool_result surfaces to
     * the model. Wire from config so prod hits the real domain.
     */
    buildApprovalUrl?: (requestId: string) => string
}

export class Worker {
    private running = false
    private readonly shutdownController = new AbortController()
    private readonly maxConcurrency: number
    /** session_id → in-flight runOne promise. */
    private readonly inflight = new Map<string, Promise<void>>()

    constructor(private readonly deps: WorkerDeps) {
        this.maxConcurrency = Math.max(1, deps.maxConcurrency ?? 8)
    }

    /** Signal a graceful shutdown. In-flight sessions suspend back to PG. */
    async stop(): Promise<void> {
        this.running = false
        this.shutdownController.abort()
        // Let outstanding sessions persist their suspended state before the
        // process exits.
        await Promise.allSettled(this.inflight.values())
    }

    get shutdownSignal(): AbortSignal {
        return this.shutdownController.signal
    }

    /**
     * Main loop. Keeps up to `maxConcurrency` sessions in flight. Returns when
     * (a) `iterations` claimed sessions have been processed, (b) the shutdown
     * signal fires, or (c) `stop()` is called.
     */
    async loop(opts?: { iterations?: number; claimTimeoutMs?: number }): Promise<void> {
        this.running = true
        const targetClaims = opts?.iterations ?? Infinity
        const claimMs = opts?.claimTimeoutMs ?? 1_000
        let claimed = 0

        while (this.running && claimed < targetClaims && !this.shutdownController.signal.aborted) {
            // Wait for ONE open slot so we maintain steady-state concurrency.
            // Each promise in `inflight` is chained with `.catch()` below, so
            // it can only resolve — never reject — making Promise.race safe
            // without the all-settled drain that used to wedge utilization
            // into a wave pattern (fill to N → wait for slowest → fill again).
            // The winning promise's `.finally` has already removed it from
            // the map by the time we resume here, so size has decremented.
            while (this.inflight.size >= this.maxConcurrency) {
                await Promise.race(this.inflight.values())
            }
            if (!this.running || this.shutdownController.signal.aborted || claimed >= targetClaims) {
                break
            }
            let session: AgentSession | null
            try {
                session = await this.deps.queue.claim(claimMs)
            } catch (err) {
                // Transient PG error / malformed row mapping. Log and keep
                // spinning — the next claim attempt will likely succeed.
                // Without this guard a single bad row crashes the worker.
                log.error({ err: (err as Error).message, stack: (err as Error).stack }, 'claim.failed')
                continue
            }
            if (!session) {
                continue
            }
            const claimedSession = session
            claimed++
            const p = this.runOne(claimedSession)
                .catch((err) => {
                    // runOne already has an inner try/catch; this is a
                    // belt-and-braces guard so an unexpected rejection
                    // (e.g. queue.update failing in the catch arm) doesn't
                    // surface as an unhandledRejection on the inflight map.
                    log.error(
                        { session_id: claimedSession.id, err: (err as Error).message },
                        'runOne.unhandled_rejection'
                    )
                })
                .finally(() => {
                    this.inflight.delete(claimedSession.id)
                })
            this.inflight.set(claimedSession.id, p)
        }

        // Drain any still-in-flight sessions before returning so the caller
        // can rely on "loop() done == all my sessions persisted."
        await Promise.allSettled(this.inflight.values())
    }

    async runOne(session: AgentSession): Promise<void> {
        const sLog = log.child({ session_id: session.id, application_id: session.application_id })
        sLog.debug({ revision_id: session.revision_id }, 'session.claim')
        let sandbox = null
        let sandboxInstanceId: string | null = null
        try {
            // Pre-flight (revision load, secrets, sandbox acquire) lives INSIDE
            // the try so a malformed revision.spec (ZodError out of PgRevisionStore),
            // a missing tool file, a decryption failure, or a sandbox-pool exhaustion
            // doesn't escape this method and crash the outer worker loop.
            // The single session gets marked failed; siblings keep running.
            const rev = await this.deps.revisions.getRevision(session.revision_id)
            if (!rev) {
                sLog.warn({}, 'session.revision_missing — marking failed')
                await this.deps.queue.update(session.id, { state: 'failed' })
                return
            }
            const integrations = await this.deps.resolveIntegrations(session)
            const secrets = await this.deps.resolveSecrets(session)
            const customTools = rev.spec.tools.filter((t) => t.kind === 'custom')
            if (customTools.length > 0) {
                const loads = await Promise.all(
                    customTools.map(async (t) => ({
                        id: t.id,
                        compiledJs: await this.deps.bundle.readText(rev.id, `${t.path.replace(/\/$/, '')}/compiled.js`),
                        schemaJson: JSON.parse(
                            await this.deps.bundle
                                .readText(rev.id, `${t.path.replace(/\/$/, '')}/schema.json`)
                                .catch(() => '{}')
                        ),
                    }))
                )
                const nonces = this.deps.broker.mintSessionMap(session.id, secrets)
                // Insert a provisioning row BEFORE we ask the pool — if acquireForSession
                // hangs / crashes we still have a row to reap.
                if (this.deps.sandboxInstances) {
                    const created = await this.deps.sandboxInstances.create({
                        team_id: session.team_id,
                        application_id: session.application_id,
                        revision_id: rev.id,
                        session_id: session.id,
                        provider_kind: this.deps.sandboxes.kind,
                    })
                    sandboxInstanceId = created.id
                }
                try {
                    sandbox = await this.deps.sandboxes.acquireForSession({
                        sessionId: session.id,
                        teamId: session.team_id,
                        tools: loads,
                        nonces,
                        sessionTimeoutMs: rev.spec.limits.max_wall_seconds * 1000,
                    })
                    if (sandboxInstanceId) {
                        // In-process pool doesn't carry a provider-side id — use the
                        // sandbox's sessionId so the row's `provider_sandbox_id` is
                        // never empty.
                        await this.deps.sandboxInstances!.markReady(sandboxInstanceId, sandbox.sessionId)
                    }
                } catch (err) {
                    if (sandboxInstanceId) {
                        await this.deps.sandboxInstances!.markFailed(sandboxInstanceId, (err as Error).message)
                    }
                    throw err
                }
            }
            const resolveModel = this.deps.resolveModel ?? resolveModelCached
            const model = resolveModel(rev.spec.model)
            const apiKey = this.deps.resolveApiKey?.(session)
            const outcome = await runSession(rev, session, {
                pi: this.deps.pi,
                model,
                apiKey,
                bundle: this.deps.bundle,
                sandbox,
                integrations,
                secrets,
                broker: this.deps.broker,
                bus: this.deps.bus,
                logs: this.deps.logs,
                analytics: this.deps.analytics,
                shutdownSignal: this.shutdownController.signal,
                useGatewayCost: this.deps.useGatewayCost,
                approvals: this.deps.approvals,
                buildApprovalUrl: this.deps.buildApprovalUrl,
                onTurnPersist: async (s) => {
                    // Persist progress after every turn so a crash mid-loop
                    // leaves valid conversation state on disk. pending_inputs
                    // is also flushed in case the runSession drained any.
                    await this.deps.queue.update(s.id, {
                        conversation: s.conversation,
                        pending_inputs: s.pending_inputs,
                        usage_total: s.usage_total,
                    })
                },
            })

            const newState: AgentSession['state'] = (() => {
                switch (outcome.state) {
                    case 'completed':
                        return 'completed'
                    case 'closed':
                        return 'closed'
                    case 'suspended':
                        // Re-queue: a sibling worker will resume from PG.
                        return 'queued'
                    case 'failed':
                        return 'failed'
                }
            })()
            sLog.debug({ outcome: outcome.state, turns: outcome.turns, newState }, 'session.done')
            await this.deps.queue.update(session.id, {
                state: newState,
                conversation: session.conversation,
                pending_inputs: session.pending_inputs,
                usage_total: session.usage_total,
            })
        } catch (err) {
            sLog.error({ err: (err as Error).message, stack: (err as Error).stack }, 'session.crashed')
            await this.deps.queue.update(session.id, {
                state: 'failed',
                conversation: session.conversation,
                pending_inputs: session.pending_inputs,
                usage_total: session.usage_total,
            })
        } finally {
            if (sandbox) {
                await this.deps.sandboxes.release(session.id)
                if (sandboxInstanceId && this.deps.sandboxInstances) {
                    await this.deps.sandboxInstances.markTerminated(sandboxInstanceId).catch(() => undefined)
                }
            }
            this.deps.broker.release(session.id)
        }
    }
}
