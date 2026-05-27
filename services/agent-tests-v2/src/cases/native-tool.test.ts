/**
 * Native tool dispatch: agent's spec references posthog.query.v1, the model
 * emits a toolCall, the runner routes through the native registry and back.
 */

import request from 'supertest'

import { buildCluster, closeSharedPool, Cluster, fauxCallTool, fauxText } from '../harness'

describe('native tool dispatch: real e2e', () => {
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

    it('agent calling posthog.query.v1 routes through the native registry', async () => {
        c.setScript([fauxCallTool('posthog.query.v1', { query: 'select 1' }), fauxText('query ran')])
        await c.deployAgent({
            slug: 'analyst',
            spec: { tools: [{ kind: 'native', id: 'posthog.query.v1' }] },
        })
        const res = await request(c.ingress).post('/agents/analyst/run').send({ message: 'run query' })
        await c.drain()
        const session = await c.queue.get(res.body.session_id)
        expect(session!.state).toBe('completed')
        // user + assistant(toolCall) + toolResult + assistant(text)
        expect(session!.conversation).toHaveLength(4)
        const toolResult = session!.conversation[2] as { role: 'toolResult' }
        expect(toolResult.role).toBe('toolResult')
    })

    it('multi-tool dispatch: agent calls posthog.query then end_session', async () => {
        c.setScript([
            fauxCallTool('posthog.query.v1', { query: 'select 1' }),
            fauxCallTool('meta.end_session.v1', { summary: 'done' }),
        ])
        await c.deployAgent({
            slug: 'compound',
            spec: {
                tools: [
                    { kind: 'native', id: 'posthog.query.v1' },
                    { kind: 'native', id: 'meta.end_session.v1' },
                ],
            },
        })
        const res = await request(c.ingress).post('/agents/compound/run').send({ message: 'go' })
        await c.drain()
        const session = await c.queue.get(res.body.session_id)
        expect(session!.state).toBe('completed')
    })

    it('rejects tools not declared in the revision spec', async () => {
        // Model tries to call a tool the agent didn't declare.
        c.setScript([fauxCallTool('posthog.query.v1', { query: 'x' }), fauxText('recovered')])
        await c.deployAgent({ slug: 'no-tools' }) // no tools declared
        const res = await request(c.ingress).post('/agents/no-tools/run').send({ message: 'x' })
        await c.drain()
        const session = await c.queue.get(res.body.session_id)
        // The runner records an error toolResult; agent recovers via the
        // follow-up text response.
        const toolResult = session!.conversation.find((m) => m.role === 'toolResult') as
            | { role: 'toolResult'; isError: boolean }
            | undefined
        expect(toolResult?.isError).toBe(true)
    })
})
