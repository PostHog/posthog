export type FeedbackSessionKind = 'conversation' | 'task'

/** Appends the session and trace ids to a support ticket body so support can find the run. */
export function appendTicketMetadata(
    body: string,
    { sessionId, sessionKind, traceId }: { sessionId: string; sessionKind: FeedbackSessionKind; traceId: string | null }
): string {
    const trimmedBody = body.trim()
    if (!trimmedBody) {
        return ''
    }
    const idLabel = sessionKind === 'task' ? 'Task ID' : 'Conversation ID'
    const metadataLines = [`${idLabel}: ${sessionId}`, traceId ? `Trace ID: ${traceId}` : null].filter(Boolean)
    return `${trimmedBody}\n\n----\n${metadataLines.join('\n')}`
}
