import { Link } from '@posthog/lemon-ui'

import { TRACING_DOCS_URL } from '../../traceLinks'
import { CopyableId } from './SpanSummaryHeader'

// Other products link here by trace ID alone, so an empty result must not read as "this request never ran".
export function TraceUnavailableNotice({ traceId }: { traceId: string }): JSX.Element {
    return (
        <div className="flex flex-col gap-1.5 p-4" data-attr="tracing-trace-unavailable-notice">
            <span className="font-semibold">Trace unavailable</span>
            <p className="m-0">
                PostHog has no spans for this trace. The service may not send spans to PostHog, sampling may have
                dropped them, or they may be older than your retention period. New spans can take a few minutes to
                appear.
            </p>
            <div className="flex items-center gap-x-3 gap-y-1 flex-wrap text-xs text-muted">
                <CopyableId label="Trace ID" value={traceId} />
                <Link to={TRACING_DOCS_URL} target="_blank" data-attr="tracing-trace-unavailable-docs">
                    Send traces to PostHog
                </Link>
            </div>
        </div>
    )
}
