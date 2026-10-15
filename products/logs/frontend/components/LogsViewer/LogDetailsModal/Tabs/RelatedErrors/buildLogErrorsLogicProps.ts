import { ParsedLogMessage } from 'products/logs/frontend/types'
import { parseLogTimestamp } from 'products/logs/frontend/utils'
import { TraceErrorsLogicProps } from 'products/tracing/frontend/components/TraceDrawer/traceErrorsLogic'

// Every logs surface that counts or lists a log's errors builds its props here, so they all bind
// the same keyed logic instance and share one query. The initial scope stays null because it is
// not part of the logic key: two callers that disagreed on it would overwrite each other's props.
export function buildLogErrorsLogicProps(log: ParsedLogMessage, sessionId: string | null): TraceErrorsLogicProps {
    // Some pipelines send epoch timestamps, which the logic's window would read as an invalid date.
    const timestamp = parseLogTimestamp(log.timestamp)
    return {
        traceId: log.trace_id,
        spanId: log.span_id || null,
        timestamp: timestamp.isValid() ? timestamp.toISOString() : null,
        sessionId,
        initialScope: null,
    }
}
