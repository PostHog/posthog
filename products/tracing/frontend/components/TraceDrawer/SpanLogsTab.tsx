import { useMemo, useState } from 'react'

import { IconExternal } from '@posthog/icons'
import { LemonButton, LemonSegmentedButton } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'

import { LogsViewer } from 'products/logs/frontend/components/LogsViewer/LogsViewer'

import { traceLookupDateRange } from '../../traceLinks'
import { buildLogScopeFilter, logsDeepLinkUrl, type TraceLogScope } from '../../traceLogScope'
import type { Span } from '../../types'

// Logs correlated to the inspected span (default) or the whole trace, via the embedded LogsViewer
// pinned to a trace_id/span_id filter. Span scope keeps the tab coherent with the rest of the
// inspector; the toggle rescues the common case where a span emitted no logs of its own. The
// viewer's own filter bar is hidden (showFilterBar={false}) — the scope is fixed by the pinned
// filter, and this toggle is the visible scope control.
export function SpanLogsTab({ span }: { span: Span }): JSX.Element {
    const [scope, setScope] = useState<TraceLogScope>('span')

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
            pinnedFilters: buildLogScopeFilter(scope, ids),
            deepLink: logsDeepLinkUrl(scope, ids, dateRange),
        }),
        [scope, ids, dateRange]
    )

    return (
        <div className="flex flex-col gap-2 h-[60vh] min-h-80">
            <div className="flex items-center justify-between gap-2">
                <LemonSegmentedButton
                    size="xsmall"
                    value={scope}
                    onChange={setScope}
                    options={[
                        { value: 'span', label: 'This span' },
                        { value: 'trace', label: 'Whole trace' },
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
                showFilterBar={false}
                // Full-screen is off (like PersonLogsTab): the shared modal can't carry pinnedFilters,
                // so it would open unscoped and clear this viewer's scope. "Open in Logs" preserves
                // the scope via the URL filterGroup instead.
                showFullScreenButton={false}
                showSavedViewsButton={false}
            />
        </div>
    )
}
