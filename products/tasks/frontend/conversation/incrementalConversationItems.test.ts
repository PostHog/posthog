import type { AcpMessage } from './acp-types'
import { buildConversationItems, type ConversationItem } from './buildConversationItems'
import { createIncrementalConversationBuilder } from './incrementalConversationItems'

function promptRequest(id: number, text: string, ts: number): AcpMessage {
    return {
        type: 'acp_message',
        ts,
        message: { jsonrpc: '2.0', id, method: 'session/prompt', params: { prompt: [{ type: 'text', text }] } },
    }
}

function promptResponse(id: number, ts: number): AcpMessage {
    return { type: 'acp_message', ts, message: { jsonrpc: '2.0', id, result: { stopReason: 'end_turn' } } }
}

function progress(group: string, step: string, status: string, label: string, ts: number): AcpMessage {
    return {
        type: 'acp_message',
        ts,
        message: { jsonrpc: '2.0', method: '_posthog/progress', params: { group, step, status, label } },
    }
}

function agentChunk(text: string, ts: number): AcpMessage {
    return {
        type: 'acp_message',
        ts,
        message: {
            jsonrpc: '2.0',
            method: 'session/update',
            params: {
                sessionId: 's1',
                update: { sessionUpdate: 'agent_message_chunk', content: { type: 'text', text } },
            },
        },
    }
}

function summarize(items: ConversationItem[]): unknown[] {
    return items.map((item) => {
        if (item.type !== 'session_update') {
            return { type: item.type }
        }
        const update = item.update
        if (update.sessionUpdate === 'progress_group') {
            return { type: 'progress_group', steps: update.steps, isActive: update.isActive }
        }
        if ('content' in update) {
            const content = update.content as { type?: string; text?: string }
            if (content?.type === 'text') {
                return { type: update.sessionUpdate, text: content.text }
            }
        }
        return { type: update.sessionUpdate }
    })
}

function progressGroups(items: ConversationItem[]): { steps: unknown[]; isActive: boolean }[] {
    const groups: { steps: unknown[]; isActive: boolean }[] = []
    for (const item of items) {
        if (item.type === 'session_update' && item.update.sessionUpdate === 'progress_group') {
            groups.push({ steps: item.update.steps, isActive: item.update.isActive })
        }
    }
    return groups
}

describe('createIncrementalConversationBuilder', () => {
    function makeStream(): {
        update: (event: AcpMessage) => ReturnType<typeof buildConversationItems>
        events: AcpMessage[]
    } {
        const builder = createIncrementalConversationBuilder()
        const events: AcpMessage[] = []
        return {
            events,
            update: (event: AcpMessage) => {
                events.push(event)
                return builder.update([...events], true)
            },
        }
    }

    it('matches a full rebuild when a progress event mutates a card in a frozen turn', () => {
        const { update, events } = makeStream()

        update(promptRequest(1, 'first prompt', 1000))
        update(progress('g1', 's1', 'in_progress', 'Working', 1001))
        update(promptResponse(1, 1002))
        update(promptRequest(2, 'second prompt', 2000))
        // Reaches back across the turn boundary into the frozen turn's card.
        const result = update(progress('g1', 's1', 'completed', 'Working', 2001))

        expect(summarize(result.items)).toEqual(summarize(buildConversationItems([...events], true).items))
        expect(progressGroups(result.items)).toEqual([
            { steps: [{ key: 's1', status: 'completed', label: 'Working', detail: undefined }], isActive: false },
        ])
    })

    it('stays equivalent to a full rebuild on fast-path appends after a frozen-card mutation', () => {
        const { update, events } = makeStream()

        update(promptRequest(1, 'first prompt', 1000))
        update(progress('g1', 's1', 'in_progress', 'Working', 1001))
        update(promptResponse(1, 1002))
        update(promptRequest(2, 'second prompt', 2000))
        update(progress('g1', 's1', 'completed', 'Working', 2001))
        update(agentChunk('hello', 2002))
        const result = update(agentChunk(' world', 2003))

        expect(summarize(result.items)).toEqual(summarize(buildConversationItems([...events], true).items))
        expect(progressGroups(result.items)).toEqual([
            { steps: [{ key: 's1', status: 'completed', label: 'Working', detail: undefined }], isActive: false },
        ])
    })

    it('does not duplicate steps when a frozen card gains a new step and is mutated repeatedly', () => {
        const { update, events } = makeStream()

        update(promptRequest(1, 'first prompt', 1000))
        update(progress('g1', 's1', 'in_progress', 'Working', 1001))
        update(promptResponse(1, 1002))
        update(promptRequest(2, 'second prompt', 2000))
        update(progress('g1', 's2', 'in_progress', 'Verifying', 2001))
        const result = update(progress('g1', 's2', 'completed', 'Verifying', 2002))

        expect(summarize(result.items)).toEqual(summarize(buildConversationItems([...events], true).items))
        expect(progressGroups(result.items)).toEqual([
            {
                steps: [
                    { key: 's1', status: 'in_progress', label: 'Working', detail: undefined },
                    { key: 's2', status: 'completed', label: 'Verifying', detail: undefined },
                ],
                isActive: true,
            },
        ])
    })
})
