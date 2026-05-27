/**
 * Real inference variant. Only runs when a provider key is set. The harness
 * accepts a real pi-ai Model via `buildCluster({ model })`, swapping out the
 * faux model — everything else stays identical.
 *
 * Set one of:
 *   ANTHROPIC_API_KEY     → Anthropic (default model: claude-sonnet-4-7)
 *   OPENAI_API_KEY        → OpenAI (default model: gpt-4o-mini)
 *   POSTHOG_LLM_GATEWAY_KEY + POSTHOG_LLM_GATEWAY_URL → llm-gateway
 *
 * Override the model with REAL_INFERENCE_MODEL_ID (e.g. "claude-opus-4-7").
 */

import { getModel } from '@earendil-works/pi-ai'
import type { Model } from '@earendil-works/pi-ai'
import request from 'supertest'

import { posthogLlmGatewayModel } from '@posthog/agent-runner-v2'

import { buildCluster, closeSharedPool, Cluster } from '../harness'

function pickRealModel(): { model: Model<string>; apiKey: string } | null {
    if (process.env.POSTHOG_LLM_GATEWAY_KEY && process.env.POSTHOG_LLM_GATEWAY_URL) {
        return {
            model: posthogLlmGatewayModel({
                modelId: process.env.REAL_INFERENCE_MODEL_ID ?? 'gpt-4.1-mini',
                baseUrl: process.env.POSTHOG_LLM_GATEWAY_URL,
            }),
            apiKey: process.env.POSTHOG_LLM_GATEWAY_KEY,
        }
    }
    if (process.env.ANTHROPIC_API_KEY) {
        return {
            model: getModel(
                'anthropic',
                (process.env.REAL_INFERENCE_MODEL_ID ?? 'claude-sonnet-4-7') as never
            ) as Model<string>,
            apiKey: process.env.ANTHROPIC_API_KEY,
        }
    }
    if (process.env.OPENAI_API_KEY) {
        return {
            model: getModel('openai', (process.env.REAL_INFERENCE_MODEL_ID ?? 'gpt-4o-mini') as never) as Model<string>,
            apiKey: process.env.OPENAI_API_KEY,
        }
    }
    return null
}

const real = pickRealModel()
const maybeDescribe = real ? describe : describe.skip

maybeDescribe('real inference (via pi-ai): real e2e', () => {
    let c: Cluster

    beforeEach(async () => {
        process.env.AGENT_TEST_API_KEY = real!.apiKey
        c = await buildCluster({ model: real!.model })
    })

    afterEach(async () => {
        await c.teardown()
    })

    afterAll(async () => {
        await closeSharedPool()
    })

    it('completes a single turn via real provider', async () => {
        await c.deployAgent({
            slug: 'real-1',
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

    it('dispatches a native tool (posthog.query.v1) end-to-end', async () => {
        await c.deployAgent({
            slug: 'real-tool',
            spec: { tools: [{ kind: 'native', id: 'posthog.query.v1' }] },
            files: {
                'agent.md':
                    "You must call posthog.query.v1 with query='select 1 as x' exactly once, then summarize the result in a brief sentence.",
            },
        })
        const res = await request(c.ingress).post('/agents/real-tool/run').send({ message: 'run it' })
        await c.drain({ iterations: 100 })
        const session = await c.queue.get(res.body.session_id)
        expect(session!.state).toBe('completed')
        const sawToolCall = session!.conversation.some((m) => {
            if (m.role !== 'assistant') {
                return false
            }
            return (m.content as Array<{ type: string; name?: string }>).some(
                (b) => b.type === 'toolCall' && b.name === 'posthog.query.v1'
            )
        })
        expect(sawToolCall).toBe(true)
    }, 90_000)
})
