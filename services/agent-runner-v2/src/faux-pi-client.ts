/**
 * In-process test helper that implements PiClient with scripted responses.
 *
 * Unit-test path. End-to-end tests use pi-ai's `registerFauxProvider` so the
 * runner exercises its real provider-resolution code (see harness/faux.ts in
 * agent-tests-v2).
 */

import type { AssistantMessage, Context, TextContent, ToolCall } from '@earendil-works/pi-ai'

import { InvokeOpts, PiClient } from './pi-client'

export type ScriptedTurn =
    | AssistantMessage
    | ((ctx: Context, opts?: InvokeOpts) => AssistantMessage | Promise<AssistantMessage>)

export class FauxPiClient implements PiClient {
    private idx = 0
    public readonly calls: Array<{ context: Context; opts?: InvokeOpts }> = []

    constructor(private readonly turns: ScriptedTurn[]) {}

    async invoke(context: Context, opts?: InvokeOpts): Promise<AssistantMessage> {
        this.calls.push({ context, opts })
        if (this.idx >= this.turns.length) {
            throw new Error(`FauxPiClient ran out of scripted turns at idx=${this.idx}`)
        }
        const next = this.turns[this.idx++]
        return typeof next === 'function' ? next(context, opts) : next
    }
}

/* ---------- builders for scripting AssistantMessage responses ---------- */

const BASE_META = {
    api: 'faux' as const,
    provider: 'faux',
    model: 'faux',
    usage: {
        input: 0,
        output: 0,
        cacheRead: 0,
        cacheWrite: 0,
        totalTokens: 0,
        cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 },
    },
}

export function text(content: string): TextContent {
    return { type: 'text', text: content }
}

export function toolCall(name: string, args: Record<string, unknown>, id?: string): ToolCall {
    return { type: 'toolCall', id: id ?? `tc_${Math.random().toString(36).slice(2, 10)}`, name, arguments: args }
}

export function endTurn(content: string | (TextContent | ToolCall)[]): AssistantMessage {
    const blocks = typeof content === 'string' ? [text(content)] : content
    return {
        role: 'assistant',
        content: blocks,
        stopReason: 'stop',
        timestamp: Date.now(),
        ...BASE_META,
    }
}

export function toolUseTurn(calls: ToolCall[]): AssistantMessage {
    return {
        role: 'assistant',
        content: calls,
        stopReason: 'toolUse',
        timestamp: Date.now(),
        ...BASE_META,
    }
}

export function errorTurn(message: string): AssistantMessage {
    return {
        role: 'assistant',
        content: [],
        stopReason: 'error',
        errorMessage: message,
        timestamp: Date.now(),
        ...BASE_META,
    }
}

export function lengthCappedTurn(): AssistantMessage {
    return {
        role: 'assistant',
        content: [text('(cut off)')],
        stopReason: 'length',
        timestamp: Date.now(),
        ...BASE_META,
    }
}
