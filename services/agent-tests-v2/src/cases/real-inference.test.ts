/**
 * Real inference variant. Only runs when PI_DEV_BASE_URL and PI_DEV_API_KEY
 * are set in env — otherwise the entire suite is skipped. mock-pi-dev proxies
 * unknown model names to the upstream pi.dev, so when we deploy an agent with
 * a real model id (`claude-opus-4-7`, etc.), the request flows ingress →
 * runner → HttpPiClient → mock-pi-dev → real pi.dev.
 *
 * This is the "really know it works" path. The harness setup is identical to
 * mock-only tests — the only difference is the model id in the agent spec.
 */

import request from 'supertest'

import { buildCluster, closeSharedPool, Cluster } from '../harness'

const REAL_INFERENCE_ENABLED = !!(process.env.PI_DEV_BASE_URL && process.env.PI_DEV_API_KEY)
const REAL_MODEL = process.env.PI_DEV_REAL_MODEL ?? 'claude-opus-4-7'

const maybeDescribe = REAL_INFERENCE_ENABLED ? describe : describe.skip

maybeDescribe('real inference (proxied via mock-pi-dev): real e2e', () => {
    let c: Cluster

    beforeEach(async () => {
        c = await buildCluster()
    })

    afterEach(async () => {
        await c.teardown()
    })

    afterAll(async () => {
        await closeSharedPool()
    })

    it(`agent with model=${REAL_MODEL} completes a single turn via real pi.dev`, async () => {
        await c.deployAgent({
            slug: 'real-1',
            spec: { model: REAL_MODEL },
            files: { 'agent.md': "Reply with exactly 'PONG' and nothing else." },
        })
        const res = await request(c.ingress).post('/agents/real-1/run').send({ message: 'ping' })
        expect(res.status).toBe(200)
        await c.drain({ iterations: 100 })
        const session = await c.queue.get(res.body.session_id)
        expect(session!.state).toBe('completed')
        const assistant = session!.conversation.find((m) => m.role === 'assistant') as {
            content: Array<{ type: string; text?: string }>
        }
        expect(assistant).not.toBeUndefined()
        const text = (assistant.content.find((b) => b.type === 'text') as { text: string }).text
        expect(text.length).toBeGreaterThan(0)
    }, 60_000)

    it('real model can dispatch a native tool (posthog.query.v1)', async () => {
        await c.deployAgent({
            slug: 'real-tool',
            spec: {
                model: REAL_MODEL,
                tools: [{ kind: 'native', id: 'posthog.query.v1' }],
            },
            files: {
                'agent.md':
                    "You must call posthog.query.v1 with query='select 1 as x' exactly once, then summarize what came back.",
            },
        })
        const res = await request(c.ingress).post('/agents/real-tool/run').send({ message: 'run it' })
        await c.drain({ iterations: 100 })
        const session = await c.queue.get(res.body.session_id)
        expect(session!.state).toBe('completed')
        // The conversation should contain a tool_use block for posthog.query.v1.
        const sawToolUse = session!.conversation.some((m) => {
            if (m.role !== 'assistant') {
                return false
            }
            return (m.content as Array<{ type: string; name?: string }>).some(
                (b) => b.type === 'tool_use' && b.name === 'posthog.query.v1'
            )
        })
        expect(sawToolUse).toBe(true)
    }, 90_000)
})
