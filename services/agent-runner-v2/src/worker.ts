/**
 * Long-running worker process: claim sessions from the queue, run a turn, persist.
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
}

export class Worker {
    private running = false

    constructor(private readonly deps: WorkerDeps) {}

    async stop(): Promise<void> {
        this.running = false
    }

    async loop(opts?: { iterations?: number; claimTimeoutMs?: number }): Promise<void> {
        this.running = true
        const max = opts?.iterations ?? Infinity
        const claimMs = opts?.claimTimeoutMs ?? 1_000
        let i = 0
        while (this.running && i < max) {
            i++
            const session = await this.deps.queue.claim(claimMs)
            if (!session) {
                continue
            }
            await this.runOne(session)
        }
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
            })
            const newState: AgentSession['state'] =
                outcome.state === 'completed' ? 'completed' : outcome.state === 'waiting' ? 'waiting' : 'failed'
            await this.deps.queue.update(session.id, { state: newState, conversation: session.conversation })
        } catch (err) {
            // Any uncaught error (pi.dev HTTP failure, sandbox crash, bundle
            // read error) lands the session in failed. The loop keeps running
            // — sibling sessions are independent.
            // eslint-disable-next-line no-console
            console.error(`[runner-v2] session ${session.id} crashed:`, (err as Error).message)
            await this.deps.queue.update(session.id, { state: 'failed', conversation: session.conversation })
        } finally {
            if (sandbox) {
                await this.deps.sandboxes.release(session.id)
            }
            this.deps.broker.release(session.id)
        }
    }
}
