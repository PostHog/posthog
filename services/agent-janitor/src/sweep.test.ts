import { AgentSession, EMPTY_USAGE_TOTAL, MemorySessionQueue } from '@posthog/agent-shared'

import { sweepOnce } from './sweep'

function session(id: string, state: AgentSession['state'], updatedAt: string): AgentSession {
    return {
        id,
        application_id: 'app',
        revision_id: 'rev',
        team_id: 1,
        external_key: null,
        idempotency_key: null,
        trigger_metadata: null,
        state,
        conversation: [],
        pending_inputs: [],
        principal: null,
        retry_count: 0,
        usage_total: { ...EMPTY_USAGE_TOTAL },
        acl: [],
        pending_elevation_requests: [],
        created_at: updatedAt,
        updated_at: updatedAt,
    }
}

describe('sweepOnce', () => {
    it('re-queues stuck running sessions for handoff (no fail)', async () => {
        const queue = new MemorySessionQueue()
        // 'updated_at' is far in the past — beyond running threshold.
        const stuck = session('a', 'running', new Date(Date.now() - 60 * 60_000).toISOString())
        await queue.enqueue(stuck)
        const result = await sweepOnce({ queue, stuckRunningThresholdMs: 60_000 })
        expect(result.requeued).toBe(1)
        expect(result.closed).toBe(0)
        expect((await queue.get('a'))!.state).toBe('queued')
    })

    it('does NOT reap running sessions younger than threshold', async () => {
        const queue = new MemorySessionQueue()
        const fresh = session('b', 'running', new Date().toISOString())
        await queue.enqueue(fresh)
        const result = await sweepOnce({ queue, stuckRunningThresholdMs: 60_000 })
        expect(result.requeued).toBe(0)
        expect((await queue.get('b'))!.state).toBe('running')
    })

    it('closes idle `completed` (open) sessions past their TTL', async () => {
        const queue = new MemorySessionQueue()
        // An idle `completed` session under the new state machine — the
        // user never followed up. The sweep transitions it to `closed`
        // (proper terminal) after the threshold so it doesn't linger.
        const idle = session('w', 'completed', '2026-01-01T00:00:00Z')
        await queue.enqueue(idle)
        const result = await sweepOnce({
            queue,
            stuckRunningThresholdMs: 60_000,
            idleCompletedThresholdMs: 60_000,
            listIdleCompletedCandidates: async () => [idle],
            now: () => new Date('2026-05-27T00:00:00Z'),
        })
        expect(result.closed).toBe(1)
        expect((await queue.get('w'))!.state).toBe('closed')
    })

    it('respects per-agent TTL: a resume-enabled session past the floor is NOT closed', async () => {
        // The agent's spec.resume.max_completed_age_ms (7d) extends the
        // platform floor (24h). A session idle for 36h is past the floor
        // but well within the agent TTL — it should stay open until next sweep.
        const queue = new MemorySessionQueue()
        const longLived = session('lr', 'completed', new Date(Date.now() - 36 * 60 * 60_000).toISOString())
        await queue.enqueue(longLived)
        const result = await sweepOnce({
            queue,
            idleCompletedThresholdMs: 24 * 60 * 60_000,
            listIdleCompletedCandidates: async () => [longLived],
            getResumeConfig: async () => ({ enabled: true, max_completed_age_ms: 7 * 24 * 60 * 60_000 }),
        })
        expect(result.closed).toBe(0)
        expect((await queue.get('lr'))!.state).toBe('completed')
    })

    it('per-agent TTL: resume-enabled session past its own TTL IS closed', async () => {
        const queue = new MemorySessionQueue()
        const expired = session('lr2', 'completed', new Date(Date.now() - 14 * 24 * 60 * 60_000).toISOString())
        await queue.enqueue(expired)
        const result = await sweepOnce({
            queue,
            idleCompletedThresholdMs: 24 * 60 * 60_000,
            listIdleCompletedCandidates: async () => [expired],
            getResumeConfig: async () => ({ enabled: true, max_completed_age_ms: 7 * 24 * 60 * 60_000 }),
        })
        expect(result.closed).toBe(1)
        expect((await queue.get('lr2'))!.state).toBe('closed')
    })

    it('resume-disabled or missing config falls back to the platform floor', async () => {
        const queue = new MemorySessionQueue()
        const idle = session('lr3', 'completed', new Date(Date.now() - 36 * 60 * 60_000).toISOString())
        await queue.enqueue(idle)
        const result = await sweepOnce({
            queue,
            idleCompletedThresholdMs: 24 * 60 * 60_000,
            listIdleCompletedCandidates: async () => [idle],
            getResumeConfig: async () => undefined,
        })
        expect(result.closed).toBe(1)
        expect((await queue.get('lr3'))!.state).toBe('closed')
    })

    it('falls back to the floor when getResumeConfig throws', async () => {
        // Don't let a transient lookup failure pin sessions open indefinitely —
        // err on the side of closing.
        const queue = new MemorySessionQueue()
        const idle = session('lr4', 'completed', new Date(Date.now() - 36 * 60 * 60_000).toISOString())
        await queue.enqueue(idle)
        const result = await sweepOnce({
            queue,
            idleCompletedThresholdMs: 24 * 60 * 60_000,
            listIdleCompletedCandidates: async () => [idle],
            getResumeConfig: async () => {
                throw new Error('revision store unreachable')
            },
        })
        expect(result.closed).toBe(1)
    })

    it('ignores fresh `completed` sessions still within the idle TTL', async () => {
        const queue = new MemorySessionQueue()
        const fresh = session('c', 'completed', new Date().toISOString())
        await queue.enqueue(fresh)
        const result = await sweepOnce({
            queue,
            stuckRunningThresholdMs: 1,
            idleCompletedThresholdMs: 24 * 60 * 60_000,
            listIdleCompletedCandidates: async () => [fresh],
        })
        expect(result.closed).toBe(0)
        expect((await queue.get('c'))!.state).toBe('completed')
    })

    it('poison-pills a stuck running session after maxRetries re-queues', async () => {
        const queue = new MemorySessionQueue()
        const stuck = session('p', 'running', new Date(Date.now() - 60 * 60_000).toISOString())
        await queue.enqueue(stuck)
        const opts = { queue, stuckRunningThresholdMs: 60_000, maxRetries: 2 }

        // Reap 1 → retry_count: 0 → 1, requeued.
        // Helper to put the session back in 'running' with a stale updated_at
        // so the next sweep sees it again.
        const setStale = async (): Promise<void> => {
            await queue.update('p', { state: 'running' })
            const s = await queue.get('p')
            // Force a stale updated_at — MemorySessionQueue uses updated_at as
            // the staleness signal (PG uses claimed_at; same shape).
            ;(s as AgentSession).updated_at = new Date(Date.now() - 60 * 60_000).toISOString()
        }

        let r = await sweepOnce(opts)
        expect(r).toEqual({ requeued: 1, poisoned: 0, closed: 0, expired_approvals: 0 })
        expect((await queue.get('p'))!.retry_count).toBe(1)

        await setStale()
        r = await sweepOnce(opts)
        expect(r).toEqual({ requeued: 1, poisoned: 0, closed: 0, expired_approvals: 0 })
        expect((await queue.get('p'))!.retry_count).toBe(2)

        // Third reap: retry_count would go to 3, exceeds maxRetries=2 → poisoned.
        await setStale()
        r = await sweepOnce(opts)
        expect(r).toEqual({ requeued: 0, poisoned: 1, closed: 0, expired_approvals: 0 })
        expect((await queue.get('p'))!.state).toBe('failed')
        expect((await queue.get('p'))!.retry_count).toBe(3)
    })
})
