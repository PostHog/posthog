import { Counter } from 'prom-client'

import { logger } from '../logger'
import { SandboxInstancesRepository, StaleSandboxRow } from './sandbox-instances'

const sandboxReapedCounter = new Counter({
    name: 'agent_core_sandbox_janitor_reaped',
    help: 'Number of orphaned tool-sandbox rows the janitor terminated',
    labelNames: ['provider'],
})

const sandboxReapErrorCounter = new Counter({
    name: 'agent_core_sandbox_janitor_errors',
    help: 'Number of sandbox-janitor reap attempts that errored',
    labelNames: ['provider', 'reason'],
})

/**
 * Provider-specific terminator. Receives the durable row's provider id and
 * is responsible for asking the provider to terminate that sandbox (idempotent).
 * The janitor's sweep loop drives this for every stale row.
 */
export type SandboxTerminator = (row: StaleSandboxRow) => Promise<void>

export interface SandboxInstanceJanitorOptions {
    repo: SandboxInstancesRepository
    /**
     * Provider dispatch — the runner injects one with both Docker and (when
     * configured) Modal arms. Throwing from this function counts as an error
     * and leaves the row in place for the next sweep.
     */
    terminate: SandboxTerminator
    /** Sweep cadence. */
    intervalMs: number
    /**
     * A row whose `COALESCE(last_used_at, created_at)` is older than this
     * counts as stale. Must comfortably exceed the per-tool wall-clock cap
     * (currently 30s) so we don't reap a sandbox mid-call.
     */
    staleMs: number
    /** Max rows reaped per sweep. */
    batchSize?: number
}

/**
 * Periodically walks `agent_stack_agentapplicationsandboxinstance` for rows
 * still claiming to be `provisioning`/`ready`/`terminating` past the staleness
 * threshold and calls the provider's terminator. The agent-runner sets these
 * rows up; this janitor's job is to keep them from leaking when a worker
 * crashes mid-session.
 *
 * Two safety properties:
 *  - **Idempotent termination**: a provider that already cleaned the sandbox
 *    up (e.g. Docker's in-process labels reaper) returns a no-op success;
 *    we still mark the row terminated.
 *  - **Per-row failures don't abort the sweep**: error counter ticks, row
 *    stays in place, next sweep retries. A consistently-failing provider
 *    surfaces in metrics rather than wedging the loop.
 */
export class SandboxInstanceJanitor {
    private intervalHandle: ReturnType<typeof setInterval> | null = null

    constructor(private readonly options: SandboxInstanceJanitorOptions) {}

    async start(): Promise<void> {
        if (this.intervalHandle) {
            return
        }
        this.intervalHandle = setInterval(() => {
            this.runOnce().catch((err) => {
                logger.error('SandboxInstanceJanitor sweep error', { error: String(err) })
            })
        }, this.options.intervalMs)
        // Immediate first run — picks up anything from a previous process's
        // crash without waiting `intervalMs`.
        await this.runOnce()
    }

    async stop(): Promise<void> {
        if (this.intervalHandle) {
            clearInterval(this.intervalHandle)
            this.intervalHandle = null
        }
    }

    async runOnce(): Promise<{ reaped: number; errors: number }> {
        const { repo, terminate, staleMs, batchSize = 100 } = this.options
        const rows = await repo.findStale(staleMs, batchSize)
        let reaped = 0
        let errors = 0
        for (const row of rows) {
            try {
                await terminate(row)
                await repo.markTerminated(row.id)
                sandboxReapedCounter.inc({ provider: row.providerKind })
                reaped += 1
            } catch (err) {
                sandboxReapErrorCounter.inc({ provider: row.providerKind, reason: 'terminate' })
                errors += 1
                logger.warn('sandbox janitor reap failed', {
                    id: row.id,
                    provider: row.providerKind,
                    error: String(err),
                })
            }
        }
        if (reaped > 0 || errors > 0) {
            logger.info('sandbox janitor swept', { reaped, errors, considered: rows.length })
        }
        return { reaped, errors }
    }
}
