export interface PushMessage {
    text: string
    message_id: string | null
    finished: boolean
}

function record(value: unknown): Record<string, unknown> {
    return typeof value === 'object' && value !== null ? (value as Record<string, unknown>) : {}
}

export function updatePushMessage(event: Record<string, unknown>, previous: string | null = null): string | null {
    const message: PushMessage = previous
        ? (JSON.parse(previous) as PushMessage)
        : { text: '', message_id: null, finished: false }
    const notification = record(event['notification'])
    const params = record(notification['params'])
    const update = event['type'] === 'pi_event' ? record(event['event']) : record(params['update'])
    const kind = event['type'] === 'pi_event' ? update['type'] : update['sessionUpdate']
    const meta = record(update['_meta'])
    for (const metadataKey of ['posthog', 'claudeCode']) {
        const parent = record(meta[metadataKey])['parentToolCallId']
        if (typeof parent === 'string' && parent.length > 0) {
            return null
        }
    }
    const result = record(notification['result'])

    if (
        kind === 'turn_completed' ||
        notification['method'] === '_posthog/turn_complete' ||
        result['stopReason'] === 'end_turn'
    ) {
        return JSON.stringify({ ...message, finished: true })
    }
    if (
        notification['method'] === '_posthog/user_message' ||
        ['user_message', 'user_message_chunk', 'tool_call', 'tool_call_started'].includes(String(kind))
    ) {
        return JSON.stringify({ text: '', message_id: null, finished: false })
    }
    if (!['agent_message', 'agent_message_chunk', 'assistant_message_chunk'].includes(String(kind))) {
        return null
    }
    const content = record(update['content'])
    if (content['type'] !== 'text' || typeof content['text'] !== 'string') {
        return null
    }
    const messageId = typeof update['messageId'] === 'string' ? update['messageId'] : null
    const replace =
        kind === 'agent_message' || message.finished || (messageId !== null && messageId !== message.message_id)
    let text = (replace ? '' : message.text) + content['text']
    const encoded = Buffer.from(text, 'utf8')
    text = encoded.toString('utf8')
    if (encoded.length > 1000) {
        text = new TextDecoder('utf-8', { fatal: false }).decode(encoded.subarray(0, 997), { stream: true }) + '…'
    }
    return JSON.stringify({ text, message_id: messageId, finished: false })
}
