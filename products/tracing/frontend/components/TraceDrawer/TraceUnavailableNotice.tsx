import posthog from 'posthog-js'

import { Link } from '@posthog/lemon-ui'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'

import { TRACING_DOCS_URL } from '../../traceLinks'
import { CopyableId } from './SpanSummaryHeader'

// Other products link here by trace ID alone, so an empty result must not read as "this request never ran".
export function TraceUnavailableNotice({
    traceId,
    filtersActive,
    surface,
}: {
    traceId: string
    filtersActive: boolean
    surface: 'drawer' | 'trace_dialog'
}): JSX.Element {
    // Captured on show, not on the span lookup, because AI events can still fill or fail the trace after that.
    useOnMountEffect(() => {
        posthog.capture('tracing trace unavailable', { filters_active: filtersActive, surface })
    })

    return (
        <div className="flex flex-col gap-1.5 p-4" data-attr="tracing-trace-unavailable-notice">
            <span className="font-semibold">Trace unavailable</span>
            {filtersActive ? (
                <p className="m-0">
                    PostHog has no spans for this trace that match your current filters. The service may not send spans
                    to PostHog, sampling may have dropped them, active filters may be excluding them, or they may be
                    older than your retention period. New spans can take a few minutes to appear.
                </p>
            ) : (
                <p className="m-0">
                    PostHog has no spans for this trace. The service may not send spans to PostHog, sampling may have
                    dropped them, or they may be older than your retention period. New spans can take a few minutes to
                    appear.
                </p>
            )}
            <div className="flex items-center gap-x-3 gap-y-1 flex-wrap text-xs text-muted">
                <CopyableId label="Trace ID" value={traceId} />
                <Link to={TRACING_DOCS_URL} target="_blank" data-attr="tracing-trace-unavailable-docs">
                    Send traces to PostHog
                </Link>
            </div>
        </div>
    )
}
