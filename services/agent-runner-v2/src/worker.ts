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

import {
    AgentSession,
    BundleStore,
    RevisionStore,
    SandboxPool,
    SecretBroker,
    SessionQueue,
} from '@posthog/agent-shared-v2'

import { PiClient } from './pi-client'
import { runSession } from './run-turn'

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
        const rev = await this.deps.revisions.getRevision(session.revision_id)
        if (!rev) {
            await this.deps.queue.update(session.id, { state: 'failed' })
            return
        }
        const integrations = await this.deps.resolveIntegrations(session)
        const secrets = await this.deps.resolveSecrets(session)
        const customTools = rev.spec.tools.filter((t) => t.kind === 'custom')
        let sandbox = null
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
            sandbox = await this.deps.sandboxes.acquireForSession({
                sessionId: session.id,
                teamId: session.team_id,
                tools: loads,
                nonces,
                sessionTimeoutMs: rev.spec.limits.max_wall_seconds * 1000,
            })
        }
        try {
            const outcome = await runSession(rev, session, {
                pi: this.deps.pi,
                bundle: this.deps.bundle,
                sandbox,
                integrations,
                secrets,
                broker: this.deps.broker,
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
            await this.deps.queue.update(session.id, {
                state: newState,
                conversation: session.conversation,
                pending_inputs: session.pending_inputs,
            })
        } catch (err) {
            // eslint-disable-next-line no-console
            console.error(`[runner-v2] session ${session.id} crashed:`, (err as Error).message)
            await this.deps.queue.update(session.id, {
                state: 'failed',
                conversation: session.conversation,
                pending_inputs: session.pending_inputs,
            })
        } finally {
            if (sandbox) {
                await this.deps.sandboxes.release(session.id)
            }
            this.deps.broker.release(session.id)
        }
    }
}
