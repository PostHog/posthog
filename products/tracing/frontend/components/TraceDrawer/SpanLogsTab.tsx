import { useMemo, useState } from 'react'

import { IconExternal } from '@posthog/icons'
import { LemonButton, LemonSegmentedButton } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'

import { LogsViewer } from 'products/logs/frontend/components/LogsViewer/LogsViewer'

import { isAiEventSpan } from '../../aiEventSpans'
import { traceLookupDateRange } from '../../traceLinks'
import { buildLogScopeFilter, logsDeepLinkUrl, type TraceLogScope } from '../../traceLogScope'
import type { Span } from '../../types'

// Logs correlated to the whole trace (default) or the inspected span, via the embedded LogsViewer
// pinned to a trace_id/span_id filter. Trace scope is the default because a single span often emits
// no logs of its own; narrow to the span with the toggle when needed. The pinned filter fixes the
// scope — the viewer's own filters can only narrow within it — and this toggle is the scope control.
export function SpanLogsTab({ span }: { span: Span }): JSX.Element {
    const [scope, setScope] = useState<TraceLogScope>('trace')
    // An AI row has no OTel span id to match logs on, so it stays on the trace even when the
    // user picked "This span" on a real span. The pick comes back when they select a real span.
    const spanScopeDisabledReason = isAiEventSpan(span)
        ? "AI events don't have their own span, so logs show for the whole trace"
        : undefined
    const effectiveScope: TraceLogScope = spanScopeDisabledReason ? 'trace' : scope

    // `initialFilters` (the date range) is stable across scope changes — recompute only when the
    // span timestamp changes. Otherwise a scope toggle would mint a fresh `initialFilters` object;
    // logsViewerFiltersLogic compares it by identity and would call setFilters, resetting the date
    // range and discarding any sparkline zoom the user applied. (Memoizing also keeps resize-drag
    // re-renders from handing the viewer fresh objects and re-querying every frame.)
    const { dateRange, initialFilters } = useMemo(() => {
        const dateRange = dayjs(span.timestamp).isValid() ? traceLookupDateRange(span.timestamp) : { date_from: '-24h' }
        return { dateRange, initialFilters: { dateRange } }
    }, [span.timestamp])

    // Scope-sensitive values recompute when scope or the span identity changes.
    const ids = useMemo(() => ({ traceId: span.trace_id, spanId: span.span_id }), [span.trace_id, span.span_id])
    const { pinnedFilters, deepLink } = useMemo(
        () => ({
            pinnedFilters: buildLogScopeFilter(effectiveScope, ids),
            deepLink: logsDeepLinkUrl(effectiveScope, ids, dateRange),
        }),
        [effectiveScope, ids, dateRange]
    )

    return (
        <div className="flex flex-col gap-2 h-[60vh] min-h-80">
            <div className="flex items-center justify-between gap-2">
                <LemonSegmentedButton
                    size="xsmall"
                    value={effectiveScope}
                    onChange={setScope}
                    options={[
                        { value: 'trace', label: 'Whole trace' },
                        { value: 'span', label: 'This span', disabledReason: spanScopeDisabledReason },
                    ]}
                    data-attr="tracing-logs-scope"
                />
                <LemonButton
                    size="xsmall"
                    type="secondary"
                    icon={<IconExternal />}
                    to={deepLink}
                    data-attr="tracing-logs-open-in-logs"
                >
                    Open in Logs
                </LemonButton>
            </div>
            {/* Keyed by trace so it's one instance per trace; flipping scope or selecting another
                span changes pinnedFilters and re-queries in place. */}
            <LogsViewer
                id={`tracing-logs-${span.trace_id}`}
                pinnedFilters={pinnedFilters}
                initialFilters={initialFilters}
                showSavedViewsButton={false}
                // Start with the facet/filter rail hidden — the drawer is narrow and the pinned
                // scope already covers the common case; "Show filters" re-expands it.
                defaultFacetRailCollapsed
            />
        </div>
    )
}
