import { useValues } from 'kea'
import { useMemo } from 'react'

import { IconExternal } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { insightLogic } from 'scenes/insights/insightLogic'

import { Query } from '~/queries/Query/Query'
import { DataVisualizationNode, InsightVizNode, Node, SavedInsightNode } from '~/queries/schema/schema-general'
import { isDataVisualizationNode, isInsightVizNode, isSavedInsightNode } from '~/queries/utils'
import { ChartDisplayType, InsightLogicProps } from '~/types'

import type { ReportChartApi, SizeEnumApi } from 'products/signals/frontend/generated/api.schemas'

import { inboxReportDetailLogic } from '../../logics/inboxReportDetailLogic'
import { chartOpenTarget } from '../../utils/chartOpenTarget'

/**
 * Strip the chrome a query node carries for the insight scene (filter bar, header, results table)
 * so the report shows the chart alone. A scout writes the query against the insight schema, so it
 * can arrive with any of these turned on. Mirrors what `NotebookNodeQuery` does for the same reason.
 */
function asEmbeddedChart(query: Record<string, any>): Node {
    const node = { ...query, full: false } as any
    if (isInsightVizNode(node) || isSavedInsightNode(node)) {
        node.showFilters = false
        node.showHeader = false
        node.showTable = false
        node.showCorrelationTable = false
        node.embedded = true
        // Forced on rather than left alone: an explicit `false` (which the notebook query node sets,
        // and a scout can copy from one) makes `InsightVizDisplay` omit the result body entirely, so
        // the report would draw a titled card with nothing in it.
        node.showResults = true
    }
    return node as Node
}

/**
 * A SQL node draws a table unless it was given a graphical display, and only a graph needs a box.
 *
 * `Auto` is not one: it defers to the data visualization, which reads the result and draws a table
 * for nonnumeric columns or a bold number for a single numeric one. Neither wants a graph's fixed
 * height — the table ends up clipped into a scrolling region and the number sits in an oversized
 * card — and nothing here can tell which it will be before the query returns. So it sizes to its
 * content, like the table an absent display already produces.
 */
function isGraphicalSqlNode(query: Node): boolean {
    if (!isDataVisualizationNode(query)) {
        return false
    }
    const { display } = query as DataVisualizationNode
    return !!display && display !== ChartDisplayType.ActionsTable && display !== ChartDisplayType.Auto
}

// Written out per size rather than built from one map: Tailwind only emits classes it can read
// literally in the source, so a height assembled at runtime would compile to nothing.
const SIZE_HEIGHTS: Record<SizeEnumApi, string> = {
    small: 'h-[9rem]',
    medium: 'h-[18rem]',
    large: 'h-[28rem]',
}
const SIZE_MAX_HEIGHTS: Record<SizeEnumApi, string> = {
    small: 'max-h-[9rem]',
    medium: 'max-h-[18rem]',
    large: 'max-h-[28rem]',
}

/**
 * The height a chart gets when its author didn't pick one. A single fixed height suits an ordinary
 * time series and little else — a big single number is then mostly empty box, and a retention grid
 * is cut off — so the node decides, and `size` on the artefact overrides it.
 */
export function inferChartSize(query: Node): SizeEnumApi {
    if (!isInsightVizNode(query)) {
        // A SQL node draws its own display, and a bold number is one line of text — the same case the
        // insight branch below treats as small, reached by a different route.
        if (
            isDataVisualizationNode(query) &&
            (query as DataVisualizationNode).display === ChartDisplayType.BoldNumber
        ) {
            return 'small'
        }
        return 'medium'
    }
    const source = (query as InsightVizNode).source as any
    // Retention draws a grid and paths a fan of rows; both read as clipped at the default height.
    if (source?.kind === 'RetentionQuery' || source?.kind === 'PathsQuery') {
        return 'large'
    }
    const display = source?.trendsFilter?.display ?? source?.stickinessFilter?.display
    if (display === ChartDisplayType.BoldNumber) {
        return 'small'
    }
    if (display === ChartDisplayType.WorldMap) {
        return 'large'
    }
    return 'medium'
}

/**
 * A chart pointed at a saved insight, refused when that insight does not resolve.
 *
 * `insightDataLogic` falls back to a default trends query for an insight it could not load, so
 * handing a dangling reference straight to `Query` would draw unrelated project data under the
 * scout's title and caption, which a reader has no way to tell is not the scout's evidence.
 */
function ChartLoadError(): JSX.Element {
    return (
        <p className="m-auto text-xs text-tertiary text-center">
            Can't load the insight behind this chart. Refresh the page. If it still doesn't load, the insight may have
            been deleted.
        </p>
    )
}

/**
 * Whether a saved-insight reference is one `insightLogic` can be mounted against. The query is stored
 * unparsed and the backend checks only its `kind`, so `shortId` can be any JSON value — and the logic
 * calls `startsWith` on whatever it is given, which throws on a number before the body below can
 * degrade to its load-error state.
 */
function hasMountableShortId(query: SavedInsightNode): boolean {
    return typeof query.shortId === 'string' && query.shortId.length > 0
}

function SavedInsightChartBody({ query, uniqueKey }: { query: SavedInsightNode; uniqueKey: string }): JSX.Element {
    const insightProps: InsightLogicProps = { dashboardItemId: query.shortId }
    const { insight, insightLoading } = useValues(insightLogic(insightProps))

    if (insightLoading) {
        return <Spinner className="self-center m-auto" />
    }
    // A load failure leaves the empty insight the logic starts from, so an absent query covers both
    // a deleted insight and one this reader cannot see.
    if (!insight?.query) {
        return <ChartLoadError />
    }
    return <Query query={query} uniqueKey={uniqueKey} readOnly embedded />
}

/**
 * One chart attached to a report, drawn from the query its author supplied.
 *
 * Addressed by id and read from the logic rather than passed down, so that the callback `LemonMarkdown`
 * turns into its anchor component depends on where the charts go and not on what they contain. A
 * refresh that appends a new version of one chart would otherwise hand `LemonMarkdown` a new component
 * type, and React unmounts every inline chart on the report to honor it.
 *
 * The query is persisted unparsed (the backend checks only `kind` and a size bound), so `Query` can
 * be handed something it cannot draw. That degrades to `Query`'s own error boundary rather than
 * taking the report down with it.
 */
export function ReportChart({ chartId }: { chartId: string }): JSX.Element | null {
    const { chartsById } = useValues(inboxReportDetailLogic)
    const chart: ReportChartApi | undefined = chartsById.get(chartId)
    // `query` is `unknown` on the serializer, and the rows behind it are older stored JSON, so this is
    // where it becomes a node: anything that isn't an object has no `kind` for `Query` to draw.
    const authoredQuery = useMemo(
        () => (chart?.query && typeof chart.query === 'object' ? (chart.query as Node) : null),
        [chart?.query]
    )
    const query = useMemo(
        () => (authoredQuery ? asEmbeddedChart(authoredQuery as Record<string, any>) : null),
        [authoredQuery]
    )

    if (!chart || !query || !authoredQuery) {
        return null
    }

    // `size` arrives as stored JSON, so an unknown value falls back to the inferred height rather
    // than dropping the box altogether.
    const size = chart.size && chart.size in SIZE_HEIGHTS ? chart.size : null
    const inferredSize = size ?? inferChartSize(query)
    // A graph fills whatever box it's given and collapses without one, so it takes a fixed height. A
    // data table sizes itself to its rows, so its box is a ceiling it scrolls within rather than a
    // height it has to fill. Every chart gets a bounded box either way: a table taller than its size
    // then scrolls inside the card, instead of growing the whole report down the page with its last
    // rows left unreachable at the bottom.
    const isSelfSizing = !(isInsightVizNode(query) || isSavedInsightNode(query) || isGraphicalSqlNode(query))
    const height = isSelfSizing ? SIZE_MAX_HEIGHTS[inferredSize] : SIZE_HEIGHTS[inferredSize]
    const bodyClass = `flex flex-col overflow-y-auto ${height}`
    // The SQLEditor prefix opts into container-governed chart sizing
    // (dataVisualizationLogic.presetChartHeight). Without it a graphical SQL chart renders at 60vh
    // and swallows the report, which is why NotebookNodeSQLV2 prefixes its key the same way.
    const uniqueKey = `SQLEditor-report-chart-${chart.chart_id}`
    const openTarget = chartOpenTarget(authoredQuery)

    // Tighter than the card default: a report can carry a row of these beside prose, and `p-6` gives
    // each one more frame than chart. No hover effect, since the card isn't a click target.
    return (
        <LemonCard hoverEffect={false} className="flex flex-col gap-2 p-3" data-attr="report-chart">
            <div className="flex items-start justify-between gap-2">
                <h4 className="m-0 text-sm font-semibold text-primary">{chart.title}</h4>
                {openTarget ? (
                    <LemonButton
                        to={openTarget.url}
                        targetBlank
                        hideExternalLinkIcon
                        icon={<IconExternal />}
                        size="xsmall"
                        type="tertiary"
                        tooltip={openTarget.label}
                        aria-label={openTarget.label}
                        data-attr="report-chart-open"
                    />
                ) : null}
            </div>
            <div className={bodyClass}>
                {isSavedInsightNode(query) ? (
                    hasMountableShortId(query) ? (
                        <SavedInsightChartBody query={query} uniqueKey={uniqueKey} />
                    ) : (
                        <ChartLoadError />
                    )
                ) : (
                    <Query query={query} uniqueKey={uniqueKey} readOnly embedded />
                )}
            </div>
            {chart.caption ? <p className="m-0 text-xs text-tertiary">{chart.caption}</p> : null}
        </LemonCard>
    )
}
