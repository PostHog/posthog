import { AgentSession, MemorySessionQueue } from '@posthog/agent-shared-v2'

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
        created_at: updatedAt,
        updated_at: updatedAt,
    }
}

describe('sweepOnce', () => {
    it('reaps running sessions older than threshold', async () => {
        const queue = new MemorySessionQueue()
        const stuck = session('a', 'running', '2026-05-27T00:00:00Z')
        const fresh = session('b', 'running', '2026-05-27T10:00:00Z')
        await queue.enqueue(stuck)
        await queue.enqueue(fresh)
        const result = await sweepOnce({
            queue,
            stuckThresholdMs: 60 * 60 * 1000,
            listCandidates: async () => [stuck, fresh],
            now: () => new Date('2026-05-27T10:30:00Z'),
        })
        expect(result.reaped).toBe(1)
        expect((await queue.get('a'))!.state).toBe('failed')
        expect((await queue.get('b'))!.state).toBe('running')
    })

    it('ignores completed sessions', async () => {
        const queue = new MemorySessionQueue()
        const done = session('c', 'completed', '2026-05-27T00:00:00Z')
        await queue.enqueue(done)
        const result = await sweepOnce({
            queue,
            stuckThresholdMs: 60 * 1000,
            listCandidates: async () => [done],
            now: () => new Date('2026-05-27T10:00:00Z'),
        })
        expect(result.reaped).toBe(0)
    })

    it('reaps waiting sessions stuck for too long', async () => {
        const queue = new MemorySessionQueue()
        const stuck = session('d', 'waiting', '2026-05-27T00:00:00Z')
        await queue.enqueue(stuck)
        await sweepOnce({
            queue,
            stuckThresholdMs: 60 * 1000,
            listCandidates: async () => [stuck],
            now: () => new Date('2026-05-27T10:00:00Z'),
        })
        expect((await queue.get('d'))!.state).toBe('failed')
    })
})
