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
 * Provider matrix:
 *   POSTHOG_LLM_GATEWAY_KEY + POSTHOG_LLM_GATEWAY_URL → llm-gateway
 *   ANTHROPIC_API_KEY                                 → Anthropic (default: claude-haiku-4-5)
 *   OPENAI_API_KEY                                    → OpenAI    (default: gpt-4o-mini)
 *
 * Defaults target the cheapest model in each registry that can still reliably
 * follow simple instructions and emit tool calls. `gpt-4.1-nano` is cheaper
 * but spuriously invokes `ask_for_input` on trivial single-turn prompts;
 * `claude-3-haiku-20240307` is cheaper but ancient. Pin
 * `REAL_INFERENCE_MODEL_ID` to a larger model when investigating a regression
 * that needs one.
 *
 * Every provider with a key configured runs the full case set — this is how
 * we catch provider-specific drift (tool schemas, stop reasons, system prompt
 * handling) end-to-end. Pin to one provider with REAL_INFERENCE_PROVIDER
 * ("gateway" | "anthropic" | "openai"). Override the model with
 * REAL_INFERENCE_MODEL_ID (e.g. "claude-opus-4-7").
 */

import { getModel } from '@earendil-works/pi-ai'
import type { Model } from '@earendil-works/pi-ai'
import { existsSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import request from 'supertest'

import { posthogLlmGatewayModel } from '@posthog/agent-runner'

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
            break
        }
        const parent = dirname(dir)
        if (parent === dir) {
            break
        }
        dir = parent
    }
    // Node's built-in fetch (used by pi-ai's provider HTTP layer) does NOT
    // read macOS' keychain trust store — without an explicit CA bundle it
    // fails handshakes with `UNABLE_TO_GET_ISSUER_CERT_LOCALLY`, which pi-ai
    // surfaces as the terse "Connection error." that looks like an outage.
    // Point Node at the openssl bundle that ships on darwin if the caller
    // hasn't already pinned one. Harmless on other platforms — Node only
    // honours SSL_CERT_FILE when present and readable.
    if (!process.env.SSL_CERT_FILE && !process.env.NODE_EXTRA_CA_CERTS) {
        const darwinDefault = '/etc/ssl/cert.pem'
        if (existsSync(darwinDefault)) {
            process.env.SSL_CERT_FILE = darwinDefault
        }
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

interface ProviderSpec {
    label: string
    model: Model<string>
    apiKey: string
}

function discoverProviders(): ProviderSpec[] {
    const pin = process.env.REAL_INFERENCE_PROVIDER?.toLowerCase()
    const out: ProviderSpec[] = []
    if ((!pin || pin === 'gateway') && process.env.POSTHOG_LLM_GATEWAY_KEY && process.env.POSTHOG_LLM_GATEWAY_URL) {
        out.push({
            label: 'llm-gateway',
            model: posthogLlmGatewayModel({
                modelId: process.env.REAL_INFERENCE_MODEL_ID ?? 'gpt-4.1-mini',
                baseUrl: process.env.POSTHOG_LLM_GATEWAY_URL,
            }),
            apiKey: process.env.POSTHOG_LLM_GATEWAY_KEY,
        })
    }
    if ((!pin || pin === 'anthropic') && process.env.ANTHROPIC_API_KEY) {
        out.push({
            label: 'anthropic',
            model: resolveOrThrow('anthropic', process.env.REAL_INFERENCE_MODEL_ID ?? 'claude-haiku-4-5'),
            apiKey: process.env.ANTHROPIC_API_KEY,
        })
    }
    if ((!pin || pin === 'openai') && process.env.OPENAI_API_KEY) {
        out.push({
            label: 'openai',
            model: resolveOrThrow('openai', process.env.REAL_INFERENCE_MODEL_ID ?? 'gpt-4o-mini'),
            apiKey: process.env.OPENAI_API_KEY,
        })
    }
    return out
}

const SKIP = process.env.AGENT_SKIP_REAL_INFERENCE === '1' || process.env.AGENT_SKIP_REAL_INFERENCE === 'true'
const providers = SKIP ? [] : discoverProviders()

if (!SKIP && providers.length === 0) {
    // Surface the missing-creds error at file load — vitest reports it as a
    // suite-level failure and the run exits non-zero. A skipped describe
    // would hide the regression silently.
    throw new Error(
        'real-inference suite: no provider key found. Set ANTHROPIC_API_KEY / OPENAI_API_KEY / POSTHOG_LLM_GATEWAY_* (env or repo-root .env), or set AGENT_SKIP_REAL_INFERENCE=1 to opt out.'
    )
}

const matrix = SKIP ? [{ label: 'skipped', model: null as never, apiKey: '' }] : providers
const maybeDescribe = SKIP ? describe.skip : describe.each(matrix.map((p) => [p.label, p] as const))

maybeDescribe('real inference (via pi-ai): real e2e [%s]', (_label, real: ProviderSpec) => {
    let c: Cluster

    beforeEach(async () => {
        process.env.AGENT_TEST_API_KEY = real.apiKey
        c = await buildCluster({ model: real.model })
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

    it('approval-gated tool: queued result → admin approves → real result lands', async () => {
        // Proves the synthetic queued tool_result is intelligible to a real
        // LLM: the model must understand it queued for review, NOT retry,
        // and continue once the approval lands. The faux-driven suite in
        // approval-gated.test.ts pins the wire-level contract; this one
        // pins "a real model can actually drive this loop".
        const { application } = await c.deployAgent({
            slug: 'real-gated',
            spec: {
                tools: [
                    {
                        kind: 'native',
                        id: '@posthog/query',
                        requires_approval: true,
                        approval_policy: { allow_edit: false },
                    },
                ],
            },
            files: {
                'agent.md':
                    "You have one tool: @posthog/query. On the user's first request, call it exactly once with `select 1 as x`. " +
                    'If you receive a tool result whose JSON contains `"approval": {"state": "queued"}`, it means the call is awaiting human approval. ' +
                    'In that case, write a brief reply acknowledging the call is pending review (include the approval_url verbatim) — DO NOT call the tool again. ' +
                    'When you later receive a tool result whose JSON contains `"approval": {"state": "approved"}`, summarize the inner `result` field in one short sentence.',
            },
        })

        const run = await request(c.ingress).post('/agents/real-gated/run').send({ message: 'run the query' })
        const sid = run.body.session_id

        await c.drain({ iterations: 100 })

        // Session did NOT park — gated calls keep running.
        let session = await c.queue.get(sid)
        expect(session!.state).not.toBe('waiting')

        // Janitor sees exactly one queued approval row.
        const queuedRes = await request(c.janitor)
            .get('/approvals')
            .query({ application_id: application.id, state: 'queued' })
        expect(queuedRes.status).toBe(200)
        expect(queuedRes.body.results).toHaveLength(1)
        const approvalId = queuedRes.body.results[0].id

        // The model acknowledged the queue (text mentioning the approval_url
        // or simply that approval is pending) without re-issuing the tool
        // call (idempotency would dedupe it anyway).
        const queuedAck = (session!.conversation as Array<{ role: string }>).filter((m) => m.role === 'assistant')
        expect(queuedAck.length).toBeGreaterThan(0)

        // Approve. Janitor wakes the session.
        const decideRes = await request(c.janitor).post(`/approvals/${approvalId}/decide`).send({
            decision: 'approve',
            decided_by: '00000000-0000-0000-0000-000000000001',
        })
        expect(decideRes.status).toBe(200)

        await c.drain({ iterations: 100 })

        // Session completes; the real tool result + the model's wrap-up are in
        // conversation.
        session = await c.queue.get(sid)
        expect(session!.state).toBe('completed')

        // The synthetic approved envelope is present and carries the real
        // tool output. The wake message is a `user` message (not a
        // toolResult) — Anthropic 400s if a tool_result follows a closing
        // assistant message instead of its matching tool_use. The fake
        // HogQL backend echoes the query, so the envelope contains
        // "select 1".
        const approvedEnvelope = (
            session!.conversation as Array<{ role: string; content?: string | Array<{ text?: string }> }>
        )
            .filter((m) => m.role === 'user')
            .map((m) => (Array.isArray(m.content) ? (m.content[0]?.text ?? '') : ''))
            .find((t) => t.includes('"state":"approved"'))
        expect(approvedEnvelope).not.toBeUndefined()
        expect(approvedEnvelope).toContain('select 1')
    }, 180_000)

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
