import { AgentSession, MemorySessionQueue } from '@posthog/agent-shared'

import { sweepOnce } from './sweep'

function session(id: string, state: AgentSession['state'], updatedAt: string): AgentSession {
    return {
        id,
        application_id: 'app',
        revision_id: 'rev',
        team_id: 1,
        external_key: null,
        state,
        conversation: [],
        pending_inputs: [],
        principal: null,
        retry_count: 0,
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
        expect(result.failed).toBe(0)
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

    it('fails waiting sessions stuck beyond their (longer) threshold', async () => {
        const queue = new MemorySessionQueue()
        const stuck = session('w', 'waiting', '2026-01-01T00:00:00Z')
        await queue.enqueue(stuck)
        const result = await sweepOnce({
            queue,
            stuckRunningThresholdMs: 60_000,
            stuckWaitingThresholdMs: 60_000,
            listWaitingCandidates: async () => [stuck],
            now: () => new Date('2026-05-27T00:00:00Z'),
        })
        expect(result.failed).toBe(1)
        expect((await queue.get('w'))!.state).toBe('failed')
    })

    it('ignores completed sessions', async () => {
        const queue = new MemorySessionQueue()
        const done = session('c', 'completed', '2026-01-01T00:00:00Z')
        await queue.enqueue(done)
        const result = await sweepOnce({ queue, stuckRunningThresholdMs: 1, listWaitingCandidates: async () => [done] })
        expect(result.requeued + result.failed).toBe(0)
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
        expect(r).toEqual({ requeued: 1, poisoned: 0, failed: 0 })
        expect((await queue.get('p'))!.retry_count).toBe(1)

        await setStale()
        r = await sweepOnce(opts)
        expect(r).toEqual({ requeued: 1, poisoned: 0, failed: 0 })
        expect((await queue.get('p'))!.retry_count).toBe(2)

        // Third reap: retry_count would go to 3, exceeds maxRetries=2 → poisoned.
        await setStale()
        r = await sweepOnce(opts)
        expect(r).toEqual({ requeued: 0, poisoned: 1, failed: 0 })
        expect((await queue.get('p'))!.state).toBe('failed')
        expect((await queue.get('p'))!.retry_count).toBe(3)
    })
})
