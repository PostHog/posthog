import { describe, expect, it } from 'vitest'

import { updatePushMessage } from '@/lib/push-message.js'

function acp(kind: string, text = ''): Record<string, unknown> {
    return {
        type: 'notification',
        notification: {
            method: 'session/update',
            params: { update: { sessionUpdate: kind, content: { type: 'text', text } } },
        },
    }
}

function pi(kind: string, text = '', messageId = 'message-1'): Record<string, unknown> {
    return { type: 'pi_event', event: { type: kind, messageId, content: { type: 'text', text } } }
}

describe('push message preview', () => {
    it.each([
        { events: [acp('agent_message_chunk', 'Done'), acp('agent_message', 'Done')], expected: 'Done' },
        {
            events: [
                acp('agent_message', 'Checking'),
                acp('tool_call'),
                acp('agent_thought_chunk', 'Private'),
                acp('agent_message_chunk', 'Fixed '),
                acp('agent_message_chunk', 'the chart.'),
            ],
            expected: 'Fixed the chart.',
        },
        {
            events: [pi('assistant_message_chunk', 'Checking'), pi('assistant_message_chunk', 'Fixed', 'message-2')],
            expected: 'Fixed',
        },
        {
            events: [pi('assistant_message_chunk', 'Old'), pi('turn_completed'), pi('assistant_message_chunk', 'New')],
            expected: 'New',
        },
        {
            events: [acp('agent_message', 'Old'), acp('user_message', 'Next'), acp('agent_thought_chunk', 'Private')],
            expected: '',
        },
        { events: [acp('agent_message_chunk', '🦔'.repeat(400))], expected: '🦔'.repeat(249) + '…' },
    ])('keeps only the latest reply: $expected', ({ events, expected }) => {
        let message: string | null = null
        for (const event of events) {
            message = updatePushMessage(event, message) ?? message
        }
        const preview = JSON.parse(message!).text as string
        expect(preview).toBe(expected)
        expect(Buffer.byteLength(preview, 'utf8')).toBeLessThanOrEqual(1000)
    })
})
