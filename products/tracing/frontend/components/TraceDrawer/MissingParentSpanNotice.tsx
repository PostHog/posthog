import { CopyableId } from './SpanSummaryHeader'

// Shown in the inspector when the waterfall's "<parent span missing>" row is selected, in place of span details.
export function MissingParentSpanNotice({
    traceId,
    parentSpanId,
}: {
    traceId: string
    parentSpanId: string
}): JSX.Element {
    return (
        <div className="flex flex-col gap-1.5 px-1 pb-2" data-attr="tracing-missing-parent-notice">
            <span className="font-semibold text-danger">Parent span missing</span>
            <p className="m-0">
                Spans in this trace have a parent span that we can't find. This can happen if the parent span is recent
                and we're still processing it, or if it comes from a separate service that doesn't send spans to
                PostHog.
            </p>
            <div className="flex items-center gap-x-3 gap-y-1 flex-wrap text-xs text-muted">
                <CopyableId label="Missing span ID" value={parentSpanId} />
                <CopyableId label="Trace ID" value={traceId} />
            </div>
        </div>
    )
}
