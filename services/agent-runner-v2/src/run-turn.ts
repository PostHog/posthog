/**
 * One turn through the agent. Driven by `runSession` which loops turns until
 * the model returns stopReason=stop (or a meta tool ends/suspends, or limits
 * are hit, or shutdown is requested).
 *
 * Turn boundary discipline:
 *   - At turn start we drain `session.pending_inputs` into `conversation`.
 *     This is the recovery point for the "queued follow-ups during in-flight
 *     turn" case — /send appends to pending_inputs; the next turn picks it up.
 *   - After each turn we check the shutdown signal. If aborted, we persist
 *     and return `state=suspended` so a sibling worker can resume from PG.
 *   - pi-ai's `complete(model, context, { signal })` propagates the abort
 *     into the in-flight provider call too, so a SIGTERM during an LLM
 *     request cuts cleanly.
 */

import type { AssistantMessage, Context, Tool, ToolCall } from '@earendil-works/pi-ai'

import {
    AgentRevision,
    AgentSession,
    AssistantMessageRecord,
    BundleStore,
    IntegrationCredentials,
    LogLevel,
    LogSink,
    NoopLogSink,
    NoopSessionEventBus,
    Sandbox,
    SecretBroker,
    SessionEvent,
    SessionEventBus,
    SessionEventKind,
    ToolResultMessage,
} from '@posthog/agent-shared-v2'
import { listNativeTools } from '@posthog/agent-tools'

import { PiClient } from './pi-client'
import { buildSystemPrompt } from './system-prompt'
import { dispatchTool } from './tool-dispatch'

export interface RunSessionDeps {
    pi: PiClient
    /** The pi-ai Model to invoke for this session (resolved from rev.spec.model). */
    model: import('@earendil-works/pi-ai').Model<string>
    /** Per-call API key (provider-specific). Optional — PiAiClient has a default. */
    apiKey?: string
    bundle: BundleStore
    sandbox: Sandbox | null
    integrations: Record<string, IntegrationCredentials>
    /** Resolved plaintext secrets keyed by name. */
    secrets: Record<string, string>
    broker?: SecretBroker
    /** Aborting this signal mid-turn cancels the LLM call and stops the loop. */
    shutdownSignal?: AbortSignal
    /**
     * Called once per turn after a fresh assistant message is appended. The
     * worker uses it to persist progress so a crash mid-loop leaves valid state.
     */
    onTurnPersist?: (session: AgentSession) => Promise<void>
    /**
     * Lifecycle event sink. Defaults to NoopSessionEventBus.
     * Chat `/listen` SSE subscribes through this bus.
     */
    bus?: SessionEventBus
    /**
     * Structured log sink. Defaults to NoopLogSink.
     * Production writes to ClickHouse via Kafka.
     */
    logs?: LogSink
}

export type RunOutcome =
    | { state: 'completed'; summary?: string; turns: number }
    | { state: 'waiting'; prompt: string; turns: number }
    | { state: 'suspended'; reason: 'shutdown'; turns: number }
    | { state: 'failed'; reason: string; turns: number }

export async function runSession(rev: AgentRevision, session: AgentSession, deps: RunSessionDeps): Promise<RunOutcome> {
    const system = await buildSystemPrompt(rev, deps.bundle)
    const tools = await buildToolList(rev, deps.bundle)
    const bus: SessionEventBus = deps.bus ?? new NoopSessionEventBus()
    const logs: LogSink = deps.logs ?? new NoopLogSink()
    let turns = 0
    const log = (level: 'info' | 'warn' | 'error', msg: string, meta?: Record<string, unknown>): void => {
        // eslint-disable-next-line no-console
        console.log(`[runner] ${level} ${msg}`, meta ?? '')
    }
    const emit = async (kind: SessionEventKind, data: Record<string, unknown> = {}): Promise<void> => {
        const ts = new Date().toISOString()
        await bus.publish({ session_id: session.id, kind, data, ts } satisfies SessionEvent)
        // Mirror lifecycle events into the structured log sink. Levels:
        // failed → error; waiting → info; everything else → info.
        const level: LogLevel = kind === 'failed' ? 'error' : 'info'
        await logs.write([
            {
                ts,
                team_id: session.team_id,
                application_id: session.application_id,
                session_id: session.id,
                level,
                event: kind,
                data,
            },
        ])
    }

    await emit('session_started', { team_id: session.team_id, agent: rev.application_id, rev: rev.id })

    while (turns < rev.spec.limits.max_turns) {
        // Shutdown check at the top of every turn — clean suspension point.
        if (deps.shutdownSignal?.aborted) {
            return { state: 'suspended', reason: 'shutdown', turns }
        }

        // Drain pending_inputs into the active conversation BEFORE invoking
        // the model. This is the merge point for /send during an in-flight
        // turn: those messages land here for the next pi-ai call to see.
        if (session.pending_inputs.length > 0) {
            session.conversation.push(...session.pending_inputs)
            session.pending_inputs = []
        }

        turns++
        await emit('turn_started', { turn: turns })

        const context: Context = {
            systemPrompt: system,
            messages: session.conversation as unknown as Context['messages'],
            tools,
        }
        let result: AssistantMessage
        try {
            result = await deps.pi.invoke(deps.model, context, {
                apiKey: deps.apiKey,
                maxTokens: 4096,
                signal: deps.shutdownSignal,
            })
        } catch (err) {
            const e = err as Error & { name?: string }
            if (e.name === 'AbortError' || deps.shutdownSignal?.aborted) {
                return { state: 'suspended', reason: 'shutdown', turns }
            }
            return { state: 'failed', reason: e.message ?? 'pi-ai_error', turns }
        }

        // Persist the assistant message into the conversation. We store the
        // full AssistantMessage including api/provider/model/usage/stopReason
        // — pi-ai accepts these back as context for the next turn.
        const assistantRecord: AssistantMessageRecord = {
            role: 'assistant',
            content: result.content,
            api: result.api,
            provider: result.provider,
            model: result.model,
            usage: result.usage,
            stopReason: result.stopReason,
            errorMessage: result.errorMessage,
            timestamp: result.timestamp,
        }
        session.conversation.push(assistantRecord)
        await deps.onTurnPersist?.(session)

        // Emit assistant text events for SSE listeners. One event per text
        // block (streaming will subdivide later).
        for (const block of result.content) {
            if (block.type === 'text' && block.text) {
                await emit('assistant_text', { text: block.text })
            }
        }

        if (result.stopReason === 'error') {
            await emit('failed', { reason: result.errorMessage ?? 'model_error', turns })
            return { state: 'failed', reason: result.errorMessage ?? 'model_error', turns }
        }
        if (result.stopReason === 'aborted') {
            return { state: 'suspended', reason: 'shutdown', turns }
        }
        if (result.stopReason === 'length') {
            await emit('failed', { reason: 'max_tokens', turns })
            return { state: 'failed', reason: 'max_tokens', turns }
        }
        if (result.stopReason === 'stop') {
            await emit('completed', { turns })
            return { state: 'completed', turns }
        }

        // stopReason === 'toolUse' — dispatch every tool call, append one
        // toolResult message per dispatch, loop for the follow-up turn.
        const toolCalls = result.content.filter((b): b is ToolCall => b.type === 'toolCall')
        if (toolCalls.length === 0) {
            return { state: 'completed', turns }
        }

        let suspend: { prompt: string } | null = null
        let end: { summary?: string } | null = null

        for (const call of toolCalls) {
            await emit('tool_call', { name: call.name, args: call.arguments, id: call.id })
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
                call.name,
                call.arguments
            )
            await emit('tool_result', {
                name: call.name,
                id: call.id,
                ok: outcome.kind === 'ok',
                error: outcome.kind === 'error' ? outcome.message : undefined,
            })
            const toolResult: ToolResultMessage = {
                role: 'toolResult',
                toolCallId: call.id,
                toolName: call.name,
                content: [
                    {
                        type: 'text',
                        text:
                            outcome.kind === 'ok'
                                ? JSON.stringify(outcome.result)
                                : outcome.kind === 'error'
                                  ? outcome.message
                                  : outcome.kind === 'suspend'
                                    ? JSON.stringify({ suspended: true })
                                    : JSON.stringify({ ended: true }),
                    },
                ],
                isError: outcome.kind === 'error',
                timestamp: Date.now(),
            }
            session.conversation.push(toolResult)
            if (outcome.kind === 'suspend') {
                suspend = { prompt: outcome.prompt }
                break
            }
            if (outcome.kind === 'end') {
                end = { summary: outcome.summary }
                break
            }
        }

        await deps.onTurnPersist?.(session)

        if (end) {
            await emit('completed', { turns, summary: end.summary })
            return { state: 'completed', summary: end.summary, turns }
        }
        if (suspend) {
            await emit('waiting', { turns, prompt: suspend.prompt })
            return { state: 'waiting', prompt: suspend.prompt, turns }
        }
    }
    await emit('failed', { reason: 'max_turns_exceeded', turns })
    return { state: 'failed', reason: 'max_turns_exceeded', turns }
}

async function buildToolList(rev: AgentRevision, bundle: BundleStore): Promise<Tool[]> {
    const decls: Tool[] = []
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
                parameters: native.schema.args,
            })
        } else {
            const schemaPath = `${t.path.replace(/\/$/, '')}/schema.json`
            try {
                const raw = await bundle.readText(rev.id, schemaPath)
                const schema = JSON.parse(raw) as { description?: string; args?: unknown }
                decls.push({
                    name: t.id,
                    description: schema.description ?? `custom tool ${t.id}`,
                    parameters: (schema.args as Tool['parameters']) ?? ({ type: 'object' } as Tool['parameters']),
                })
            } catch {
                decls.push({
                    name: t.id,
                    description: `custom tool ${t.id}`,
                    parameters: { type: 'object' } as Tool['parameters'],
                })
            }
        }
    }
    return decls
}
