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
    content?: { type?: string; text?: string }
    toolCallId?: string
    title?: string
    rawInput?: unknown
    _meta?: { claudeCode?: { toolName?: string; bashCommand?: string } }
    used?: { inputTokens?: number; outputTokens?: number }
    cost?: { amount?: number } | null
}

function num(value: unknown): number {
    return typeof value === 'number' ? value : 0
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
            const used = (p.used ?? {}) as { inputTokens?: number; outputTokens?: number }
            const cost = (p.cost ?? null) as { amount?: number } | null
            return {
                kind: 'usage',
                inputTokens: num(used.inputTokens),
                outputTokens: num(used.outputTokens),
                costUsd: cost ? num(cost.amount) : undefined,
            }
        }
        case 'session/update': {
            const u = (p.update ?? {}) as SessionUpdate
            switch (u.sessionUpdate) {
                case 'agent_message_chunk':
                    return { kind: 'assistant_text', text: u.content?.text ?? '' }
                case 'agent_thought_chunk':
                    return { kind: 'thought', text: u.content?.text ?? '' }
                case 'tool_call':
                case 'tool_call_update':
                    return {
                        kind: 'tool_call',
                        toolCallId: u.toolCallId ?? '',
                        tool: u._meta?.claudeCode?.toolName,
                        command: u._meta?.claudeCode?.bashCommand,
                        title: u.title,
                    }
                case 'usage_update':
                    return {
                        kind: 'usage',
                        inputTokens: num(u.used?.inputTokens),
                        outputTokens: num(u.used?.outputTokens),
                        costUsd: u.cost ? num(u.cost.amount) : undefined,
                    }
                default:
                    return null // user_message_chunk echo, available_commands_update, …
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
