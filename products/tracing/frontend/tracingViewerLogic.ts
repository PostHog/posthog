import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import posthog from 'posthog-js'

import { PREFETCH_SPANS, tracingDataLogic } from './tracingDataLogic'
import { TRACING_SCENE_VIEWER_ID, tracingFiltersLogic } from './tracingFiltersLogic'
import type { tracingViewerLogicType } from './tracingViewerLogicType'
import type { Span } from './types'

export interface TracingViewerLogicProps {
    id: string
}

// Per-instance viewer UI state: the trace drawer and the compare-flame modal. URL-free by
// design — the /tracing scene logic reads and writes this instance's state to sync the URL;
// an embedded viewer just never wires it up. Mirrors the logsViewerLogic boundary.
export const tracingViewerLogic = kea<tracingViewerLogicType>([
    props({ id: TRACING_SCENE_VIEWER_ID } as TracingViewerLogicProps),
    key((props) => props.id),
    path((key) => ['products', 'tracing', 'frontend', 'tracingViewerLogic', key]),

    connect(({ id }: TracingViewerLogicProps) => ({
        values: [
            tracingDataLogic({ id }),
            ['spans', 'traceSpans', 'traceSpansLoading', 'traceSpansLoadingMore', 'traceSpansHasMore'],
        ],
        actions: [
            tracingDataLogic({ id }),
            ['loadTraceSpans', 'fetchSpanTree', 'fetchAggregation'],
            tracingFiltersLogic({ id }),
            ['updateComparisonWindows'],
        ],
    })),

    actions({
        openTrace: (traceId: string, options?: { spanId?: string | null; ts?: string | null }) => ({
            traceId,
            spanId: options?.spanId ?? null,
            ts: options?.ts ?? null,
        }),
        selectSpan: (spanId: string | null) => ({ spanId }),
        closeTrace: true,
        openCompareFlame: (spanName: string, serviceName: string) => ({ spanName, serviceName }),
        closeCompareFlame: true,
    }),

    reducers({
        selectedTraceId: [
            null as string | null,
            {
                openTrace: (_, { traceId }) => traceId,
                closeTrace: () => null,
            },
        ],
        selectedSpanId: [
            null as string | null,
            {
                openTrace: (_, { spanId }) => spanId,
                selectSpan: (_, { spanId }) => spanId,
                closeTrace: () => null,
            },
        ],
        // Timestamp hint for the open trace — echoed into copy-links so cold loads can bound the
        // ClickHouse lookup (the spans table is time-keyed; OTel ids embed no timestamp).
        selectedTraceTs: [
            null as string | null,
            {
                openTrace: (_, { ts }) => ts,
                closeTrace: () => null,
            },
        ],
        compareFlameSpanName: [
            null as string | null,
            {
                openCompareFlame: (_, { spanName }) => spanName,
                closeCompareFlame: () => null,
            },
        ],
        compareFlameServiceName: [
            null as string | null,
            {
                openCompareFlame: (_, { serviceName }) => serviceName,
                closeCompareFlame: () => null,
            },
        ],
    }),

    selectors({
        isTraceOpen: [
            (s) => [s.selectedTraceId],
            (selectedTraceId: string | null): boolean => selectedTraceId !== null,
        ],
        openTraceSpans: [
            (s) => [s.selectedTraceId, s.spans, s.traceSpans],
            (selectedTraceId: string | null, spans: Span[], traceSpans: Span[]): Span[] => {
                if (!selectedTraceId) {
                    return []
                }
                const filteredTraceSpans = traceSpans.filter((s) => s.trace_id === selectedTraceId)
                if (filteredTraceSpans.length > 0) {
                    return filteredTraceSpans
                }
                return spans.filter((s) => s.trace_id === selectedTraceId)
            },
        ],
        // The drawer's full-trace overlay should only show on the initial fetch — paging in more
        // spans (loadMoreTraceSpans) keeps the waterfall visible with its own bottom spinner.
        isLoadingFullTrace: [
            (s) => [s.traceSpansLoading, s.traceSpansLoadingMore],
            (traceSpansLoading: boolean, traceSpansLoadingMore: boolean): boolean =>
                traceSpansLoading && !traceSpansLoadingMore,
        ],
        // Only offer "load more" when the full-fetched spans for the open trace are what's displayed
        // — never for the small prefetch fallback, which is already the trace's complete span set.
        canLoadMoreTraceSpans: [
            (s) => [s.traceSpansHasMore, s.traceSpans, s.selectedTraceId],
            (traceSpansHasMore: boolean, traceSpans: Span[], selectedTraceId: string | null): boolean =>
                traceSpansHasMore &&
                !!selectedTraceId &&
                traceSpans.some((span: Span) => span.trace_id === selectedTraceId),
        ],
    }),

    listeners(({ actions, values }) => ({
        openTrace: ({ traceId, ts }) => {
            posthog.capture('tracing trace opened')
            const prefetchedSpans = values.spans.filter((s: Span) => s.trace_id === traceId)
            // Zero prefetched spans = the trace isn't in the loaded list (cold link) — fetch it by
            // id. A full prefetch batch (>= PREFETCH_SPANS) may be truncated — fetch the rest.
            if (prefetchedSpans.length === 0 || prefetchedSpans.length >= PREFETCH_SPANS) {
                actions.loadTraceSpans({ traceId, ts })
            }
        },
        openCompareFlame: ({ spanName, serviceName }) => {
            actions.fetchSpanTree({ spanName, serviceName })
        },
        updateComparisonWindows: () => {
            // The aggregation refetch on an overlay drag lives in tracingDataLogic; here we only
            // refresh the compare-flame modal (viewer UI) so it doesn't display stale windows.
            if (values.compareFlameSpanName && values.compareFlameServiceName) {
                actions.fetchSpanTree({
                    spanName: values.compareFlameSpanName,
                    serviceName: values.compareFlameServiceName,
                })
            }
        },
    })),
])
