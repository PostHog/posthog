/**
 * Periodic sweep: find sessions stuck in "running" or "waiting" beyond a
 * threshold, mark them failed. The runner is the source of truth for live
 * sessions; the janitor only handles ones that lost their runner.
 */

import { AgentSession, SessionQueue } from '@posthog/agent-shared-v2'

export interface SweepDeps {
    queue: SessionQueue
    /** All sessions older than this in "running"/"waiting" without progress get failed. */
    stuckThresholdMs: number
    /** How the janitor finds candidates. Production reads PG; tests inject. */
    listCandidates: () => Promise<AgentSession[]>
    now?: () => Date
}

export interface SweepResult {
    inspected: number
    reaped: number
    sessions: string[]
}

export async function sweepOnce(deps: SweepDeps): Promise<SweepResult> {
    const now = (deps.now ?? (() => new Date()))()
    const candidates = await deps.listCandidates()
    const reaped: string[] = []
    for (const s of candidates) {
        if (s.state !== 'running' && s.state !== 'waiting') {
            continue
        }
        const updated = Date.parse(s.updated_at)
        if (isNaN(updated)) {
            continue
        }
        if (now.getTime() - updated > deps.stuckThresholdMs) {
            await deps.queue.update(s.id, { state: 'failed' })
            reaped.push(s.id)
        }
    }
    return { inspected: candidates.length, reaped: reaped.length, sessions: reaped }
}
