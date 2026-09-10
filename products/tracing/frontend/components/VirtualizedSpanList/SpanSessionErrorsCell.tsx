import { useActions, useValues } from 'kea'

import { resolveTraceSessionId } from '../../traceIdentity'
import { tracingCorrelationConfigLogic } from '../../tracingCorrelationConfigLogic'
import { tracingViewerLogic } from '../../tracingViewerLogic'
import type { Span } from '../../types'
import { SpanSessionErrorsBadge } from './SpanSessionErrorsBadge'

// A row carries no badge until its session has been looked up, so an absent badge is never a
// claim that the session is clean.
export function SpanSessionErrorsCell({ span }: { span: Span }): JSX.Element | null {
    const { sessionErrorCounts } = useValues(tracingViewerLogic)
    const { openTrace } = useActions(tracingViewerLogic)
    const { configuredSessionIdKeys } = useValues(tracingCorrelationConfigLogic)

    const sessionId = resolveTraceSessionId([span], configuredSessionIdKeys)
    // hasOwn, not a plain lookup: a session id that collides with an Object member would
    // otherwise read back an inherited function instead of a count.
    const errorCount = sessionId && Object.hasOwn(sessionErrorCounts, sessionId) ? sessionErrorCounts[sessionId] : 0
    if (errorCount === 0) {
        return null
    }

    return (
        <SpanSessionErrorsBadge
            errorCount={errorCount}
            // Anchor the waterfall on this span, the way a row click does, and open the drawer
            // straight onto the tab that lists the session's issues.
            onClick={() => openTrace(span.trace_id, { spanId: span.span_id, ts: span.timestamp, tab: 'errors' })}
        />
    )
}
