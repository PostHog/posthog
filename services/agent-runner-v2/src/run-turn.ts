/**
 * One turn through the agent. Driven by `runSession` which loops turns until
 * pi.dev's stop_reason is "end_turn" (or a meta tool ends/suspends, or limits
 * are hit). See docs/native-refactor.md §4.2.
 */

import {
    AgentRevision,
    AgentSession,
    AssistantContentBlock,
    BundleStore,
    ConversationMessage,
    IntegrationCredentials,
    Sandbox,
    SecretBroker,
    UserContentBlock,
} from '@posthog/agent-shared-v2'
import { listNativeTools } from '@posthog/agent-tools'

import { PiClient, PiInvokeRequest, PiToolDeclaration, PiUserContentBlock } from './pi-client'
import { buildSystemPrompt } from './system-prompt'
import { dispatchTool } from './tool-dispatch'
import { zodToJsonSchema } from './zod-to-jsonschema'

export interface RunSessionDeps {
    pi: PiClient
    bundle: BundleStore
    sandbox: Sandbox | null
    integrations: Record<string, IntegrationCredentials>
    /** Resolved plaintext secrets keyed by name. */
    secrets: Record<string, string>
    broker?: SecretBroker
}

export type RunOutcome =
    | { state: 'completed'; summary?: string; turns: number }
    | { state: 'waiting'; prompt: string; turns: number }
    | { state: 'failed'; reason: string; turns: number }

export async function runSession(rev: AgentRevision, session: AgentSession, deps: RunSessionDeps): Promise<RunOutcome> {
    const system = await buildSystemPrompt(rev, deps.bundle)
    const tools = await buildToolDeclarations(rev, deps.bundle)
    let turns = 0
    const log = (level: 'info' | 'warn' | 'error', msg: string, meta?: Record<string, unknown>): void => {
        // eslint-disable-next-line no-console
        console.log(`[runner] ${level} ${msg}`, meta ?? '')
    }

    while (turns < rev.spec.limits.max_turns) {
        turns++

        const req: PiInvokeRequest = {
            model: rev.spec.model,
            system,
            tools,
            messages: session.conversation as unknown as PiInvokeRequest['messages'],
        }
        const result = await deps.pi.invoke(req)

        const assistantBlocks: AssistantContentBlock[] = result.content
        session.conversation.push({ role: 'assistant', content: assistantBlocks })

        if (result.stop_reason === 'error') {
            return { state: 'failed', reason: 'pi.dev returned error', turns }
        }
        if (result.stop_reason === 'max_tokens') {
            return { state: 'failed', reason: 'max_tokens', turns }
        }
        if (result.stop_reason === 'end_turn') {
            return { state: 'completed', turns }
        }

        // tool_use — dispatch every tool_use block, append a single user message
        // with the tool_result blocks, then loop for the follow-up turn.
        const toolUseBlocks = assistantBlocks.filter((b) => b.type === 'tool_use')
        if (toolUseBlocks.length === 0) {
            return { state: 'completed', turns }
        }

        const userContent: PiUserContentBlock[] = []
        let suspend: { prompt: string } | null = null
        let end: { summary?: string } | null = null

        for (const block of toolUseBlocks) {
            if (block.type !== 'tool_use') {
                continue
            }
            const outcome = await dispatchTool(
                {
                    teamId: session.team_id,
                    sessionId: session.id,
                    rev,
                    sandbox: deps.sandbox,
                    integrations: deps.integrations,
                    secret: (name) => deps.secrets[name],
                    log,
                },
                block.name,
                block.input
            )
            if (outcome.kind === 'ok') {
                userContent.push({
                    type: 'tool_result',
                    tool_use_id: block.id,
                    content: JSON.stringify(outcome.result),
                })
            } else if (outcome.kind === 'error') {
                userContent.push({
                    type: 'tool_result',
                    tool_use_id: block.id,
                    content: outcome.message,
                    is_error: true,
                })
            } else if (outcome.kind === 'suspend') {
                suspend = { prompt: outcome.prompt }
                userContent.push({
                    type: 'tool_result',
                    tool_use_id: block.id,
                    content: JSON.stringify({ suspended: true }),
                })
                break
            } else if (outcome.kind === 'end') {
                end = { summary: outcome.summary }
                userContent.push({
                    type: 'tool_result',
                    tool_use_id: block.id,
                    content: JSON.stringify({ ended: true }),
                })
                break
            }
        }

        const followUp: ConversationMessage = {
            role: 'user',
            content: userContent as UserContentBlock[],
        }
        session.conversation.push(followUp)

        if (end) {
            return { state: 'completed', summary: end.summary, turns }
        }
        if (suspend) {
            return { state: 'waiting', prompt: suspend.prompt, turns }
        }
    }
    return { state: 'failed', reason: 'max_turns_exceeded', turns }
}

async function buildToolDeclarations(rev: AgentRevision, bundle: BundleStore): Promise<PiToolDeclaration[]> {
    const decls: PiToolDeclaration[] = []
    const seen = new Set<string>()
    for (const t of rev.spec.tools) {
        if (seen.has(t.id)) {
            continue
        }
        seen.add(t.id)
        if (t.kind === 'native') {
            const native = listNativeTools().find((n) => n.id === t.id)
            if (!native) {
                continue
            }
            decls.push({
                name: native.id,
                description: native.schema.description,
                input_schema: zodToJsonSchema(native.schema.args),
            })
        } else {
            const schemaPath = `${t.path.replace(/\/$/, '')}/schema.json`
            try {
                const raw = await bundle.readText(rev.id, schemaPath)
                const schema = JSON.parse(raw) as { description?: string; args?: Record<string, unknown> }
                decls.push({
                    name: t.id,
                    description: schema.description ?? `custom tool ${t.id}`,
                    input_schema: schema.args ?? { type: 'object' },
                })
            } catch {
                decls.push({
                    name: t.id,
                    description: `custom tool ${t.id}`,
                    input_schema: { type: 'object' },
                })
            }
        }
    }
    return decls
}
