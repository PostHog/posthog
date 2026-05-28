/**
 * Real inference variant. By default this suite ALWAYS runs and fails if no
 * provider key is found — that's the only way to know v2 talks to a real
 * model end-to-end. Set `AGENT_SKIP_REAL_INFERENCE=1` to opt out (CI without
 * provider creds, dev iteration on faux-only paths, etc.).
 *
 * Key discovery order:
 *   1. process.env (already exported in the shell)
 *   2. `.env` at the posthog repo root (loaded via Node's loadEnvFile)
 *
 * Provider selection (first match wins):
 *   POSTHOG_LLM_GATEWAY_KEY + POSTHOG_LLM_GATEWAY_URL → llm-gateway
 *   ANTHROPIC_API_KEY                                 → Anthropic (default: claude-sonnet-4-7)
 *   OPENAI_API_KEY                                    → OpenAI (default: gpt-4o-mini)
 *
 * Override the model with REAL_INFERENCE_MODEL_ID (e.g. "claude-opus-4-7").
 */

import { getModel } from '@earendil-works/pi-ai'
import type { Model } from '@earendil-works/pi-ai'
import { existsSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import request from 'supertest'

import { posthogLlmGatewayModel } from '@posthog/agent-runner-v2'

import { buildCluster, closeSharedPool, Cluster } from '../harness'

// Walk up from this file looking for a `.env` and load it into process.env.
// Idempotent — existing vars win (already-set shell exports always beat .env).
function loadRepoEnv(): void {
    let dir = dirname(fileURLToPath(import.meta.url))
    for (let i = 0; i < 8; i++) {
        const candidate = resolve(dir, '.env')
        if (existsSync(candidate)) {
            try {
                process.loadEnvFile(candidate)
            } catch {
                /* loadEnvFile throws on parse errors; we'd rather degrade than crash the suite */
            }
            return
        }
        const parent = dirname(dir)
        if (parent === dir) {
            return
        }
        dir = parent
    }
}
loadRepoEnv()

function resolveOrThrow(provider: 'anthropic' | 'openai', modelId: string): Model<string> {
    const m = getModel(provider, modelId as never) as Model<string> | undefined
    if (!m) {
        throw new Error(
            `pi-ai getModel('${provider}', '${modelId}') returned undefined — model id not in registry. ` +
                `Set REAL_INFERENCE_MODEL_ID to a valid id (e.g. claude-haiku-4-5, claude-sonnet-4-6, claude-opus-4-7).`
        )
    }
    return m
}

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
            model: resolveOrThrow('anthropic', process.env.REAL_INFERENCE_MODEL_ID ?? 'claude-sonnet-4-6'),
            apiKey: process.env.ANTHROPIC_API_KEY,
        }
    }
    if (process.env.OPENAI_API_KEY) {
        return {
            model: resolveOrThrow('openai', process.env.REAL_INFERENCE_MODEL_ID ?? 'gpt-4o-mini'),
            apiKey: process.env.OPENAI_API_KEY,
        }
    }
    return null
}

const SKIP = process.env.AGENT_SKIP_REAL_INFERENCE === '1' || process.env.AGENT_SKIP_REAL_INFERENCE === 'true'
const real = SKIP ? null : pickRealModel()
const maybeDescribe = SKIP ? describe.skip : describe

maybeDescribe('real inference (via pi-ai): real e2e', () => {
    let c: Cluster

    beforeAll(() => {
        if (!real) {
            throw new Error(
                'real-inference suite: no provider key found. Set ANTHROPIC_API_KEY / OPENAI_API_KEY / POSTHOG_LLM_GATEWAY_* (env or repo-root .env), or set AGENT_SKIP_REAL_INFERENCE=1 to opt out.'
            )
        }
    })

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

    it('dispatches a native tool (@posthog/query) end-to-end', async () => {
        await c.deployAgent({
            slug: 'real-tool',
            spec: { tools: [{ kind: 'native', id: '@posthog/query' }] },
            files: {
                'agent.md':
                    "You must call @posthog/query with query='select 1 as x' exactly once, then summarize the result in a brief sentence.",
            },
        })
        const res = await request(c.ingress).post('/agents/real-tool/run').send({ message: 'run it' })
        await c.drain({ iterations: 100 })
        const session = await c.queue.get(res.body.session_id)
        expect(session!.state).toBe('completed')
        // The conversation's assistant message stores the provider-safe tool
        // name (so pi-ai can round-trip it to Anthropic on subsequent turns).
        // toolResult.toolName carries the original `@posthog/query` id — that's
        // what consumers / tests should assert on.
        const sawToolCall = session!.conversation.some(
            (m) => m.role === 'toolResult' && (m as { toolName?: string }).toolName === '@posthog/query'
        )
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
                    'You have a tool available that suspends the conversation to ask the user a question. ' +
                    "On your first turn you MUST use that tool to ask 'What is your name?'. Do not write any text on the first turn — only call the tool. " +
                    'When the user responds with their name on the next turn, reply with exactly: Hi <NAME> (substituting the actual name).',
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
                tools: [{ kind: 'native', id: '@posthog/query' }],
                limits: { max_turns: 3, max_tool_calls: 100, max_wall_seconds: 60 },
            },
            files: {
                'agent.md':
                    'You are a load-testing harness. Your sole purpose is to repeatedly issue HogQL queries. ' +
                    'On every turn — without exception — call the query tool with: select 1 as x. ' +
                    'Never produce a text response. Never decide you have done enough. Never call any other tool. Keep calling the query tool over and over.',
            },
        })
        const res = await request(c.ingress).post('/agents/real-loopy/run').send({ message: 'go' })
        await c.drain({ iterations: 100 })
        const session = await c.queue.get(res.body.session_id)
        expect(session!.state).toBe('failed')
    }, 120_000)
})
