/**
 * Translate raw harness SSE frames into normalized `CodingEvent`s. Pure +
 * synchronous so it's unit-testable against captured real frames with no
 * container — which is exactly where the integration risk lives (the ACP
 * `session/update` shapes).
 *
 * Frame shapes are from the real `@posthog/agent` server (`agent-server.ts`
 * broadcast + ACP `session/update`). Unhandled frames return `null`.
 */

import type { CodingEvent, HarnessFrame, PermissionOption } from './contract'

interface SessionUpdate {
    sessionUpdate?: string
    // `{text}` for message/thought chunks; `[{content:{text}}]` for tool results.
    content?: unknown
    toolCallId?: string
    title?: string
    status?: string
    rawInput?: unknown
    rawOutput?: { stdout?: string; stderr?: string; isError?: boolean }
    _meta?: { claudeCode?: { toolName?: string; bashCommand?: string } }
}

interface UsageParams {
    used?: { inputTokens?: number; outputTokens?: number; cachedReadTokens?: number; cachedWriteTokens?: number }
    cost?: number | null
}

function num(value: unknown): number {
    return typeof value === 'number' ? value : 0
}

function chunkText(content: unknown): string {
    return (content as { text?: string } | undefined)?.text ?? ''
}

/** Tool output: prefer the raw stdout/stderr, fall back to the ACP content blocks. */
function toolResultText(u: SessionUpdate): string | undefined {
    if (u.rawOutput) {
        const parts = [u.rawOutput.stdout, u.rawOutput.isError ? u.rawOutput.stderr : ''].filter(Boolean)
        if (parts.length) {
            return parts.join('\n')
        }
    }
    if (Array.isArray(u.content)) {
        const texts = (u.content as Array<{ content?: { text?: string } }>)
            .map((c) => c.content?.text)
            .filter((t): t is string => Boolean(t))
        if (texts.length) {
            return texts.join('\n')
        }
    }
    return undefined
}

export function parseFrame(frame: HarnessFrame): CodingEvent | null {
    if (frame.type === 'connected') {
        return { kind: 'connected' }
    }

    if (frame.type === 'permission_request') {
        return {
            kind: 'permission_request',
            requestId: frame.requestId,
            options: frame.options as PermissionOption[],
            tool: (frame.toolCall?._meta as { claudeCode?: { toolName?: string } })?.claudeCode?.toolName,
        }
    }

    const { method, params } = frame.notification
    const p = (params ?? {}) as Record<string, unknown>

    switch (method) {
        case '_posthog/run_started':
            return { kind: 'run_started' }
        case '_posthog/turn_complete':
            return { kind: 'turn_complete' }
        case '_posthog/task_complete':
            return { kind: 'task_complete', result: p }
        case '_posthog/console':
            return { kind: 'log', level: String(p.level ?? 'info'), message: String(p.message ?? '') }
        case '_posthog/usage_update': {
            const u = p as UsageParams
            const used = u.used ?? {}
            return {
                kind: 'usage',
                inputTokens: num(used.inputTokens),
                outputTokens: num(used.outputTokens),
                cacheRead: num(used.cachedReadTokens),
                cacheWrite: num(used.cachedWriteTokens),
                costUsd: num(u.cost),
            }
        }
        case 'session/update': {
            const u = (p.update ?? {}) as SessionUpdate
            switch (u.sessionUpdate) {
                case 'agent_message_chunk':
                    return { kind: 'assistant_text', text: chunkText(u.content) }
                case 'agent_thought_chunk':
                    return { kind: 'thought', text: chunkText(u.content) }
                case 'tool_call':
                    return {
                        kind: 'tool_call',
                        toolCallId: u.toolCallId ?? '',
                        tool: u._meta?.claudeCode?.toolName,
                        command: u._meta?.claudeCode?.bashCommand,
                        title: u.title,
                    }
                case 'tool_call_update': {
                    // The tool finished — surface its result.
                    if (u.status === 'completed' || u.status === 'failed' || u.rawOutput) {
                        return {
                            kind: 'tool_result',
                            toolCallId: u.toolCallId ?? '',
                            ok: u.status !== 'failed' && !u.rawOutput?.isError,
                            output: toolResultText(u),
                        }
                    }
                    // The resolved command landed (after streaming the args).
                    if (u._meta?.claudeCode?.bashCommand) {
                        return {
                            kind: 'tool_call',
                            toolCallId: u.toolCallId ?? '',
                            tool: u._meta.claudeCode.toolName,
                            command: u._meta.claudeCode.bashCommand,
                            title: u.title,
                        }
                    }
                    return null // intermediate rawInput streaming — noise
                }
                // ACP usage_update carries `used: 0` placeholders; the rich
                // numbers come on `_posthog/usage_update`. Ignore this one.
                default:
                    return null // usage_update, user_message_chunk echo, available_commands_update, …
            }
        }
        default:
            // Surface notification-level errors so the supervisor can fail fast.
            if (frame.notification.error) {
                const err = frame.notification.error as { message?: string }
                return { kind: 'error', message: err.message ?? 'harness error' }
            }
            return null
    }
}
