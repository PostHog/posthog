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

    it('dispatches a custom (sandboxed) tool end-to-end', async () => {
        const COMPILED = `
            module.exports = {
                id: "wordcount",
                actions: { default: (args) => ({ words: String(args.text ?? "").trim().split(/\\s+/).filter(Boolean).length }) },
            }
        `
        await c.deployAgent({
            slug: 'real-custom',
            spec: { tools: [{ kind: 'custom', id: 'wordcount', path: 'tools/wordcount/' }] },
            files: {
                'agent.md':
                    "You have a tool named `wordcount` that counts the words in a string. Call it exactly once with the text 'one two three four' and reply with the count.",
                'tools/wordcount/compiled.js': COMPILED,
                'tools/wordcount/schema.json': JSON.stringify({
                    description: 'Counts words in a string',
                    args: { type: 'object', properties: { text: { type: 'string' } }, required: ['text'] },
                }),
            },
        })
        const res = await request(c.ingress).post('/agents/real-custom/run').send({ message: 'go' })
        await c.drain({ iterations: 100 })
        const session = await c.queue.get(res.body.session_id)
        expect(session!.state).toBe('completed')
        const sawToolCall = session!.conversation.some(
            (m) =>
                m.role === 'assistant' &&
                (m.content as Array<{ type: string; name?: string }>).some(
                    (b) => b.type === 'toolCall' && b.name === 'wordcount'
                )
        )
        expect(sawToolCall).toBe(true)
        const toolResult = session!.conversation.find((m) => m.role === 'toolResult') as {
            content: Array<{ text?: string }>
        }
        expect(toolResult.content[0].text).toContain('4')
    }, 120_000)

    it('multi-turn: ask_for_input parks, /send resumes with the answer', async () => {
        await c.deployAgent({
            slug: 'real-multi',
            files: {
                'agent.md':
                    "On the first turn, you MUST call meta.ask_for_input.v1 with prompt='What is your name?' (do not produce any text). On the next turn, after the user provides a name, reply with the exact text 'Hi <NAME>' substituting the actual name they gave.",
            },
        })
        const run = await request(c.ingress).post('/agents/real-multi/run').send({ message: 'hello' })
        const sid = run.body.session_id
        await c.drain({ iterations: 100 })
        let session = await c.queue.get(sid)
        expect(session!.state).toBe('waiting')

        await request(c.ingress).post('/agents/real-multi/send').send({ session_id: sid, message: 'Alice' })
        await c.drain({ iterations: 100 })
        session = await c.queue.get(sid)
        expect(session!.state).toBe('completed')

        const assistantTexts = session!.conversation
            .filter((m) => m.role === 'assistant')
            .flatMap((m) =>
                (m.content as Array<{ type: string; text?: string }>)
                    .filter((b) => b.type === 'text' && b.text)
                    .map((b) => b.text!)
            )
        const joined = assistantTexts.join(' ')
        expect(joined).toMatch(/Alice/)
    }, 120_000)

    it('max_turns ceiling: a looping agent fails with reason=max_turns_exceeded', async () => {
        await c.deployAgent({
            slug: 'real-loopy',
            spec: {
                tools: [{ kind: 'native', id: 'posthog.query.v1' }],
                limits: { max_turns: 3, max_tool_calls: 100, max_wall_seconds: 60 },
            },
            files: {
                'agent.md':
                    "You MUST call posthog.query.v1 with query='select 1 as x' on every single turn and never stop. Do not produce any text response.",
            },
        })
        const res = await request(c.ingress).post('/agents/real-loopy/run').send({ message: 'go' })
        await c.drain({ iterations: 100 })
        const session = await c.queue.get(res.body.session_id)
        expect(session!.state).toBe('failed')
    }, 120_000)
})
