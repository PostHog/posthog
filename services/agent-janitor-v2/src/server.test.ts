import request from 'supertest'

import { AgentSession, MemorySessionQueue } from '@posthog/agent-shared-v2'

import { buildJanitorApp } from './server'

function session(id: string): AgentSession {
    return {
        id,
        application_id: 'app',
        revision_id: 'rev',
        team_id: 1,
        external_key: null,
        state: 'running',
        conversation: [{ role: 'user', content: 'hi', timestamp: Date.now() }],
        pending_inputs: [],
        principal: null,
        created_at: '2026-05-27',
        updated_at: '2026-05-27',
    }
}

describe('janitor HTTP', () => {
    function mk(): { queue: MemorySessionQueue; app: ReturnType<typeof buildJanitorApp> } {
        const queue = new MemorySessionQueue()
        const app = buildJanitorApp({
            queue,
            sweep: { queue, stuckRunningThresholdMs: 60_000 },
        })
        return { queue, app }
    }

    it('GET /healthz returns ok', async () => {
        const { app } = mk()
        const res = await request(app).get('/healthz')
        expect(res.status).toBe(200)
    })

    it('GET /sessions/:id returns session, 404 if missing', async () => {
        const { queue, app } = mk()
        await queue.enqueue(session('s1'))
        const ok = await request(app).get('/sessions/s1')
        expect(ok.status).toBe(200)
        expect(ok.body.id).toBe('s1')
        const miss = await request(app).get('/sessions/nope')
        expect(miss.status).toBe(404)
    })

    it('POST /sessions/:id/cancel marks failed', async () => {
        const { queue, app } = mk()
        await queue.enqueue(session('s2'))
        const res = await request(app).post('/sessions/s2/cancel')
        expect(res.status).toBe(200)
        expect((await queue.get('s2'))!.state).toBe('failed')
    })

    it('POST /sweep returns counts', async () => {
        const { app } = mk()
        const res = await request(app).post('/sweep')
        expect(res.status).toBe(200)
        expect(res.body).toEqual({ requeued: 0, failed: 0 })
    })

    it('enforces internal secret when configured', async () => {
        const queue = new MemorySessionQueue()
        const app = buildJanitorApp({
            queue,
            sweep: { queue, stuckRunningThresholdMs: 60_000 },
            internalSecret: 'topsecret',
        })
        const noAuth = await request(app).get('/sessions/x')
        expect(noAuth.status).toBe(401)
        const withAuth = await request(app).get('/sessions/x').set('x-internal-secret', 'topsecret')
        expect(withAuth.status).toBe(404) // session not found, but auth passed
    })
})
