import { combineUrl } from 'kea-router'

import { urls } from 'scenes/urls'

export type FeedbackSessionKind = 'conversation' | 'task'

/** Returns a direct answer trace link, or the closest available AI session link. */
export function feedbackContextUrl({
    sessionId,
    sessionKind,
    traceId,
    run,
}: {
    sessionId: string
    sessionKind: FeedbackSessionKind
    traceId: string | null
    run?: { taskId?: string; runId?: string }
}): string {
    const path = traceId
        ? urls.aiObservabilityTrace(traceId)
        : run?.taskId || sessionKind === 'task'
          ? combineUrl(urls.aiTask(run?.taskId ?? sessionId), run?.runId ? { runId: run.runId } : {}).url
          : urls.ai(sessionId)

    return urls.absolute(urls.currentProject(path))
}

/** Appends identifiers and a useful PostHog link to a support ticket body. */
export function appendTicketMetadata(
    body: string,
    {
        sessionId,
        sessionKind,
        traceId,
        run,
    }: {
        sessionId: string
        sessionKind: FeedbackSessionKind
        traceId: string | null
        run?: { taskId?: string; runId?: string }
    }
): string {
    const trimmedBody = body.trim()
    if (!trimmedBody) {
        return ''
    }
    const idLabel = sessionKind === 'task' ? 'Task ID' : 'Conversation ID'
    const contextLabel = traceId
        ? 'Answer trace'
        : run?.runId
          ? 'Run'
          : sessionKind === 'task'
            ? 'Task'
            : 'Conversation'
    const metadataLines = [
        `${idLabel}: ${sessionId}`,
        traceId ? `Trace ID: ${traceId}` : null,
        run?.runId ? `Run ID: ${run.runId}` : null,
        `${contextLabel}: ${feedbackContextUrl({ sessionId, sessionKind, traceId, run })}`,
    ].filter(Boolean)
    return `${trimmedBody}\n\n----\n${metadataLines.join('\n')}`
}
