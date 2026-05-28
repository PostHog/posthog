/**
 * Long-running worker: claim sessions from the queue, run turns, persist
 * progress after every turn, hand off cleanly on shutdown.
 *
 * Concurrency model — agents are largely I/O-bound (LLM HTTP, tool HTTP,
 * sandbox round-trips), so one worker process keeps up to `maxConcurrency`
 * sessions in flight at once. Whenever a slot frees, the next session is
 * claimed. The PG queue's SELECT FOR UPDATE SKIP LOCKED protects against
 * any worker (in this process or any other) double-claiming.
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
    BundleStore,
    createLogger,
    LogSink,
    RevisionStore,
    SandboxInstanceStore,
    SandboxPool,
    SecretBroker,
    SessionEventBus,
    SessionQueue,
} from '@posthog/agent-shared-v2'

import { PiClient, resolveModelCached } from './pi-client'
import { runSession } from './run-turn'

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
            // Wait for an open slot.
            while (this.inflight.size >= this.maxConcurrency) {
                await Promise.race(this.inflight.values())
            }
            if (!this.running || this.shutdownController.signal.aborted || claimed >= targetClaims) {
                break
            }
            const session = await this.deps.queue.claim(claimMs)
            if (!session) {
                continue
            }
            claimed++
            const p = this.runOne(session).finally(() => {
                this.inflight.delete(session.id)
            })
            this.inflight.set(session.id, p)
        }

        // Drain any still-in-flight sessions before returning so the caller
        // can rely on "loop() done == all my sessions persisted."
        await Promise.allSettled(this.inflight.values())
    }

    async runOne(session: AgentSession): Promise<void> {
        const sLog = log.child({ session_id: session.id, application_id: session.application_id })
        sLog.debug({ revision_id: session.revision_id }, 'session.claim')
        const rev = await this.deps.revisions.getRevision(session.revision_id)
        if (!rev) {
            sLog.warn({}, 'session.revision_missing — marking failed')
            await this.deps.queue.update(session.id, { state: 'failed' })
            return
        }
        const integrations = await this.deps.resolveIntegrations(session)
        const secrets = await this.deps.resolveSecrets(session)
        const customTools = rev.spec.tools.filter((t) => t.kind === 'custom')
        let sandbox = null
        let sandboxInstanceId: string | null = null
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
        try {
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
                shutdownSignal: this.shutdownController.signal,
                onTurnPersist: async (s) => {
                    // Persist progress after every turn so a crash mid-loop
                    // leaves valid conversation state on disk. pending_inputs
                    // is also flushed in case the runSession drained any.
                    await this.deps.queue.update(s.id, {
                        conversation: s.conversation,
                        pending_inputs: s.pending_inputs,
                    })
                },
            })

            const newState: AgentSession['state'] = (() => {
                switch (outcome.state) {
                    case 'completed':
                        return 'completed'
                    case 'waiting':
                        return 'waiting'
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
            })
        } catch (err) {
            sLog.error({ err: (err as Error).message, stack: (err as Error).stack }, 'session.crashed')
            await this.deps.queue.update(session.id, {
                state: 'failed',
                conversation: session.conversation,
                pending_inputs: session.pending_inputs,
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
