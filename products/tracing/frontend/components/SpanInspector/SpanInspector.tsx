import { useValues } from 'kea'

import { LemonTabs } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { JSONViewer } from 'lib/components/JSONViewer'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { canViewMetrics } from 'products/metrics/frontend/metricsAccess'

import { isAiEventSpan } from '../../aiEventSpans'
import type { ErrorScope } from '../../errorCorrelation'
import { getQueryText } from '../../spanSummary'
import type { Span, SpanInspectorTab } from '../../types'
import { SpanLogsTab } from '../TraceDrawer/SpanLogsTab'
import { SpanMetricsTab } from '../TraceDrawer/SpanMetricsTab'
import { SpanSummaryHeader } from '../TraceDrawer/SpanSummaryHeader'
import { TraceErrorsTab } from '../TraceDrawer/TraceErrorsTab'
import { ExpandedSpanContent } from '../VirtualizedSpanList/ExpandedSpanContent'

export interface SpanInspectorProps {
    span: Span
    /** Shared with the waterfall so a service is the same color in the bars and the summary header. */
    serviceColorMap: Map<string, number>
    /** Anchors the window the Errors tab's exceptions must fall in: the trace start where known. */
    traceTimestamp: string | null
    /** The trace's session for the Errors tab, or null when its spans resolve to no one session. */
    sessionId: string | null
    /** Show the Errors tab, which lists the issues connected to the trace. */
    showErrorsTab: boolean
    /** The scope the Errors tab opens on, when the caller named one. */
    errorsScope: ErrorScope | null
    /** The spans the session is resolved from are still arriving. */
    resolving: boolean
    tab: SpanInspectorTab
    onSelectTab: (tab: SpanInspectorTab) => void
    /** Offer include, exclude and column actions on each attribute. Off where no span list can use them. */
    showFilterActions?: boolean
}

export function SpanInspector({
    span,
    serviceColorMap,
    traceTimestamp,
    sessionId,
    showErrorsTab,
    errorsScope,
    resolving,
    tab,
    onSelectTab,
    showFilterActions = true,
}: SpanInspectorProps): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)

    // Metrics correlate to a trace via exemplars, so the tab only exists where the metrics
    // product does: its own flag, plus the metrics feature and view access.
    const showMetricsTab =
        !!featureFlags[FEATURE_FLAGS.TRACING_METRICS_TAB] && !!featureFlags[FEATURE_FLAGS.METRICS] && canViewMetrics()

    // Only DB spans carry a query; the Query tab appears only when one is present.
    const queryText = getQueryText(span)
    // The Query, Errors and Metrics tabs are conditional, so if the active tab disappears (a span
    // without a query, or one of the gates turning off), fall back to Attributes. Otherwise
    // activeKey would point at a tab LemonTabs has dropped and the inspector body would render
    // blank. Preference is preserved: a DB span re-shows Query.
    const activeTab: SpanInspectorTab =
        (tab === 'query' && !queryText) ||
        (tab === 'metrics' && !showMetricsTab) ||
        (tab === 'errors' && !showErrorsTab)
            ? 'attributes'
            : tab

    return (
        <>
            <SpanSummaryHeader span={span} serviceColorMap={serviceColorMap} />
            <LemonTabs
                activeKey={activeTab}
                onChange={onSelectTab}
                data-attr="tracing-inspector-tabs"
                tabs={[
                    {
                        key: 'attributes',
                        label: 'Attributes',
                        // The summary header carries the headline facts, so the tab
                        // shows only the user attributes (no duplicate details table).
                        content: (
                            <ExpandedSpanContent
                                span={span}
                                showDetails={false}
                                showFilterActions={showFilterActions}
                            />
                        ),
                    },
                    // Conditional (LemonTabs ignores falsy entries): only DB spans have a query.
                    queryText
                        ? {
                              key: 'query',
                              label: 'Query',
                              content: (
                                  <CodeSnippet language={Language.SQL} wrap maxLinesWithoutExpansion={40}>
                                      {queryText}
                                  </CodeSnippet>
                              ),
                          }
                        : null,
                    {
                        key: 'logs',
                        label: 'Logs',
                        // Keyed by trace, not span: a new trace remounts to reset the scope toggle
                        // back to whole-trace, while selecting another span within the same trace
                        // re-queries in place (the embedded viewer and memoized pinned filter handle
                        // it) so we don't churn its logics or lose scroll.
                        content: <SpanLogsTab key={span.trace_id} span={span} />,
                    },
                    // Conditional on its own flag. The tab is session-scoped, so it
                    // stays available on a trace that resolved no session and
                    // explains there what is missing.
                    showErrorsTab
                        ? {
                              key: 'errors',
                              label: 'Errors',
                              content: (
                                  <TraceErrorsTab
                                      key={span.span_id}
                                      traceId={span.trace_id}
                                      // A synthetic AI row has no OTel span id, so it scopes to the trace.
                                      spanId={isAiEventSpan(span) ? null : span.span_id}
                                      timestamp={traceTimestamp}
                                      sessionId={sessionId}
                                      initialScope={errorsScope}
                                      resolving={resolving}
                                  />
                              ),
                          }
                        : null,
                    // Conditional: needs the metrics product (flag + access) and its own flag.
                    showMetricsTab
                        ? {
                              key: 'metrics',
                              label: 'Metrics',
                              // Keyed by trace like the Logs tab: a new trace remounts to reset
                              // the scope toggle; selecting another span re-renders in place.
                              content: <SpanMetricsTab key={span.trace_id} span={span} />,
                          }
                        : null,
                    {
                        key: 'raw',
                        label: 'Raw',
                        // Interactive tree, matching the logs viewer's raw view (LogDetailsModal)
                        // for cross-pane consistency. The span as the frontend holds it.
                        content: <JSONViewer src={span} collapsed={2} sortKeys />,
                    },
                ]}
            />
        </>
    )
}
