/**
 * Periodic sweep with two distinct policies:
 *
 *   1. Stuck `running` sessions → **re-queue** so a sibling worker can resume.
 *      Mid-turn worker crash leaves the row in `running` with a stale
 *      claimed_at; a healthy worker should be able to pick it back up. The
 *      conversation state persisted by the runner survives.
 *
 *   2. Stuck `waiting` sessions → **fail** (no user reply ever came). Uses a
 *      separate threshold since waiting is normal for parked sessions.
 *
 * Production wires this against the PgSessionQueue, whose `reapStuckRunning`
 * does the work in one SQL statement. Tests can inject their own candidate
 * lister to exercise the policy logic without PG.
 */

import { AgentSession, SessionQueue } from '@posthog/agent-shared-v2'

export interface SweepDeps {
    queue: SessionQueue
    /** running sessions older than this are re-queued for handoff. Default 5min. */
    stuckRunningThresholdMs?: number
    /** waiting sessions older than this are marked failed. Default 24h. */
    stuckWaitingThresholdMs?: number
    /**
     * Candidate lister for the `waiting` policy. Production passes a function
     * that selects waiting sessions older than the threshold from PG. Tests
     * inject any AgentSession[].
     */
    listWaitingCandidates?: () => Promise<AgentSession[]>
    now?: () => Date
}

export interface SweepResult {
    requeued: number
    failed: number
}

export async function sweepOnce(deps: SweepDeps): Promise<SweepResult> {
    const now = (deps.now ?? (() => new Date()))()
    const runningTtl = deps.stuckRunningThresholdMs ?? 5 * 60_000
    const waitingTtl = deps.stuckWaitingThresholdMs ?? 24 * 60 * 60_000

    // Policy 1: re-queue stuck running.
    const requeued = await deps.queue.reapStuckRunning(runningTtl)

    // Policy 2: fail stuck waiting.
    let failed = 0
    if (deps.listWaitingCandidates) {
        const candidates = await deps.listWaitingCandidates()
        for (const s of candidates) {
            if (s.state !== 'waiting') {
                continue
            }
            const updated = Date.parse(s.updated_at)
            if (Number.isFinite(updated) && now.getTime() - updated > waitingTtl) {
                await deps.queue.update(s.id, { state: 'failed' })
                failed++
            }
        }
    }
    return { requeued, failed }
}
