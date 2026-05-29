/**
 * Periodic sweep with two distinct policies:
 *
 *   1. Stuck `running` sessions → **re-queue** so a sibling worker can resume.
 *      Mid-turn worker crash leaves the row in `running` with a stale
 *      claimed_at; a healthy worker should be able to pick it back up. The
 *      conversation state persisted by the runner survives.
 *
 *   2. Idle `completed` (open) sessions → **close** after the configured
 *      threshold. Under the new state machine `completed` is open by
 *      default — the user can still /send. Long-idle ones never get a
 *      follow-up; we don't want them lingering forever, so the sweep
 *      eventually transitions them to `closed` (the proper terminal).
 *
 * Production wires this against the PgSessionQueue, whose `reapStuckRunning`
 * does the work in one SQL statement. Tests can inject their own candidate
 * lister to exercise the policy logic without PG.
 */

import { AgentSession, ApprovalStore, ConversationMessage, ResumeConfig, SessionQueue } from '@posthog/agent-shared'

export interface SweepDeps {
    queue: SessionQueue
    /** running sessions older than this are re-queued for handoff. Default 5min. */
    stuckRunningThresholdMs?: number
    /** completed sessions idle for longer than this are auto-closed. Default 24h. */
    idleCompletedThresholdMs?: number
    /**
     * Poison-pill threshold: a stuck-running session that has been re-queued
     * this many times is failed instead. Catches sessions that consistently
     * crash the worker. Default 3 (matches v1's `maxTouchCount`).
     */
    maxRetries?: number
    /**
     * Candidate lister for the idle-completed policy. Production passes a
     * function that selects `completed` sessions older than the threshold
     * from PG. Tests inject any AgentSession[].
     */
    listIdleCompletedCandidates?: () => Promise<AgentSession[]>
    /**
     * Per-agent resumability lookup. When provided, the idle-completed
     * policy defers closing a candidate whose agent opted into a longer
     * TTL via `spec.resume.max_completed_age_ms`. Absent (or returning
     * `undefined`) means use the platform-wide `idleCompletedThresholdMs`.
     * Production reads this from the revision store; tests inject inline.
     */
    getResumeConfig?: (session: AgentSession) => Promise<ResumeConfig | undefined>
    /**
     * Approval-gated tools store (see plan
     * docs/agent-platform/plans/approval-gated-tools.md). When wired, the
     * sweep also expires queued approval rows past `expires_at`, injects
     * the synthetic `expired` tool_result into the session's
     * pending_inputs, and wakes the session.
     */
    approvals?: ApprovalStore
    now?: () => Date
}

export interface SweepResult {
    requeued: number
    /** Stuck running sessions that exceeded the retry threshold and were failed. */
    poisoned: number
    /** Idle completed sessions that aged out past `idleCompletedThresholdMs` and were closed. */
    closed: number
    /** Queued approval requests aged past `expires_at` that were terminated this sweep. */
    expired_approvals: number
}

export async function sweepOnce(deps: SweepDeps): Promise<SweepResult> {
    const now = (deps.now ?? (() => new Date()))()
    const runningTtl = deps.stuckRunningThresholdMs ?? 5 * 60_000
    const idleCompletedTtl = deps.idleCompletedThresholdMs ?? 24 * 60 * 60_000
    const maxRetries = deps.maxRetries ?? 3

    // Policy 1: re-queue stuck running OR poison-pill if past retry budget.
    const { requeued, poisoned } = await deps.queue.reapStuckRunning(runningTtl, maxRetries)

    // Policy 2: auto-close idle completed sessions. Under the new state
    // machine `completed` is open by default — the user can still /send.
    // Long-idle ones never get a follow-up and we don't want them lingering
    // forever, so the sweep eventually transitions them to `closed` (the
    // proper terminal).
    //
    // Per-agent TTL: an agent can opt into `spec.resume.max_completed_age_ms`
    // to extend the idle window. The candidate lister returns rows past the
    // platform-wide floor; we then check the per-agent override before
    // closing each one. Rows whose agent says "longer please" are left
    // alone until the next sweep tick.
    let closed = 0
    if (deps.listIdleCompletedCandidates) {
        const candidates = await deps.listIdleCompletedCandidates()
        for (const s of candidates) {
            if (s.state !== 'completed') {
                continue
            }
            const updated = Date.parse(s.updated_at)
            if (!Number.isFinite(updated)) {
                continue
            }
            const age = now.getTime() - updated
            const effectiveTtl = await resolveCompletedTtl(s, deps.getResumeConfig, idleCompletedTtl)
            if (age > effectiveTtl) {
                await deps.queue.update(s.id, { state: 'closed' })
                closed++
            }
        }
    }

    // Policy 3: expire queued approval requests past their TTL and wake the
    // associated sessions so the model sees a synthetic expired envelope.
    // The wake message is a `user` message (not a tool_result) — see
    // dispatch-one's dispatchApproved for the reasoning.
    let expiredApprovals = 0
    if (deps.approvals) {
        const expired = await deps.approvals.expireQueued(now.toISOString())
        for (const row of expired) {
            const msg: ConversationMessage = {
                role: 'user',
                content: [
                    {
                        type: 'text',
                        text: JSON.stringify({
                            approval: { request_id: row.id, state: 'expired' },
                        }),
                    },
                ],
                timestamp: now.getTime(),
            }
            await deps.queue.appendPendingInput(row.session_id, msg)
            await deps.queue.update(row.session_id, { state: 'queued' })
            expiredApprovals++
        }
    }

    return { requeued, poisoned, closed, expired_approvals: expiredApprovals }
}

/**
 * Resolve the effective `completed → closed` TTL for a single session. The
 * platform-wide floor applies unless the agent's spec opts in via
 * `resume.enabled` + `resume.max_completed_age_ms`. Lookup failures fall
 * back to the floor so a missing revision doesn't keep a row open forever.
 */
async function resolveCompletedTtl(
    session: AgentSession,
    getResumeConfig: SweepDeps['getResumeConfig'],
    floor: number
): Promise<number> {
    if (!getResumeConfig) {
        return floor
    }
    try {
        const resume = await getResumeConfig(session)
        if (!resume || !resume.enabled) {
            return floor
        }
        return Math.max(floor, resume.max_completed_age_ms)
    } catch {
        return floor
    }
}
