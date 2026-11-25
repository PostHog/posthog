import { combineUrl } from 'kea-router'

import { preflightLogic } from 'lib/logic/preflightLogic'
import { urls } from 'scenes/urls'

export type FeedbackSessionKind = 'conversation' | 'task'

// On Cloud, the LLM gateway captures PostHog AI generations in this project; the EU gateway mirrors them here too.
const CLOUD_TELEMETRY_PROJECT_URL = 'https://us.posthog.com/project/2'

function answerTraceUrl(traceId: string): string {
    if (preflightLogic.findMounted()?.values.isCloud) {
        return `${CLOUD_TELEMETRY_PROJECT_URL}${urls.aiObservabilityTrace(traceId)}`
    }
    return urls.absolute(urls.currentProject(urls.aiObservabilityTrace(traceId)))
}

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
    if (traceId) {
        return answerTraceUrl(traceId)
    }
    const path =
        run?.taskId || sessionKind === 'task'
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
