import { asRecord, isRecord } from '@/lib/records'

import type { SessionThreadItem, SessionToolInvocation } from '../session/types'
import type { ClassicMessage, ClassicState } from './classicMessages'

const toolInvocations = new WeakMap<Record<string, unknown>, SessionToolInvocation>()

export function classicToolCalls(data: Record<string, unknown>): Record<string, unknown>[] {
    return Array.isArray(data.tool_calls)
        ? data.tool_calls.filter(
              (call) => isRecord(call) && typeof call.id === 'string' && typeof call.name === 'string'
          )
        : []
}

function thinkingBlocks(data: Record<string, unknown>): Record<string, unknown>[] {
    const thinking = asRecord(data.meta)?.thinking
    return Array.isArray(thinking) ? thinking.filter(isRecord) : []
}

export function classicThinkingItems(
    message: ClassicMessage,
    complete: boolean,
    projectUrl?: string
): SessionThreadItem[] {
    return thinkingBlocks(message.data).flatMap((block, index): SessionThreadItem[] => {
        const id = `${message.id}-thinking-${index}`
        if (block.type === 'server_tool_use' && typeof block.id === 'string' && typeof block.name === 'string') {
            return [{ kind: 'tool', id, toolCallId: block.id }]
        }
        const text =
            block.type === 'thinking'
                ? block.thinking
                : block.type === 'reasoning' && Array.isArray(block.summary)
                  ? block.summary
                        .filter(isRecord)
                        .map((part) => (typeof part.text === 'string' ? part.text : ''))
                        .filter(Boolean)
                        .join('\n\n')
                  : null
        return typeof text === 'string' && text
            ? [{ kind: 'thought', id, text, complete, ...(projectUrl ? { projectUrl } : {}) }]
            : []
    })
}

export function classicIntermediateIds(messages: readonly ClassicMessage[]): Set<string> {
    const ids = new Set<string>()
    let candidates: string[] = []
    for (const message of messages) {
        if (message.data.type === 'human') candidates = []
        if (
            thinkingBlocks(message.data).some(
                (block) =>
                    block.type === 'server_tool_use' && typeof block.id === 'string' && typeof block.name === 'string'
            )
        ) {
            for (const id of candidates) ids.add(id)
            candidates = []
        }
        if (message.data.type === 'ai') candidates.push(message.id)
        if (classicToolCalls(message.data).length > 0 || message.data.type === 'tool') {
            for (const id of candidates) ids.add(id)
            candidates = []
        }
    }
    return ids
}

export function classicToolInvocations(state: ClassicState, working: boolean): Map<string, SessionToolInvocation> {
    const invocations = new Map<string, SessionToolInvocation>()
    const results = new Map<string, Record<string, unknown>>()
    const searchResults = new Set<string>()
    let lastHuman = -1
    for (const [index, message] of state.messages.entries()) {
        if (message.data.type === 'human') lastHuman = index
        if (message.data.type === 'tool' && typeof message.data.tool_call_id === 'string') {
            results.set(message.data.tool_call_id, message.data)
        }
        for (const block of thinkingBlocks(message.data)) {
            if (block.type === 'web_search_tool_result' && typeof block.tool_use_id === 'string') {
                searchResults.add(block.tool_use_id)
            }
        }
    }
    for (const [index, message] of state.messages.entries()) {
        const serverCalls = thinkingBlocks(message.data).filter((block) => block.type === 'server_tool_use')
        for (const call of [...classicToolCalls(message.data), ...serverCalls]) {
            if (typeof call.id !== 'string' || typeof call.name !== 'string') continue
            const result = results.get(call.id)
            const awaitingResponse = state.form?.id === call.id || state.approval?.toolCallId === call.id
            const active = working && index > lastHuman
            const context = asRecord(call.args)?.context
            const detail = state.toolUpdates?.[call.id] ?? (typeof context === 'string' ? context : undefined)
            // Tool results confirm execution ended, but the wire contract has no outcome status.
            const status =
                result || searchResults.has(call.id)
                    ? 'completed'
                    : awaitingResponse
                      ? 'pending'
                      : active
                        ? 'in_progress'
                        : 'failed'
            const previous = toolInvocations.get(call)
            if (previous?.status === status && previous.detail === detail) {
                invocations.set(call.id, previous)
                continue
            }
            const invocation: SessionToolInvocation = {
                toolCallId: call.id,
                toolName: call.name,
                title: call.name.replace(/_/g, ' '),
                detail,
                status,
            }
            toolInvocations.set(call, invocation)
            invocations.set(call.id, invocation)
        }
    }
    return invocations
}
