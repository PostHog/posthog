import { LemonBanner, Spinner } from '@posthog/lemon-ui'

import type { NotebookComponentBlockNode, NotebookComponentProps } from 'lib/components/MarkdownNotebook/types'
import { getSqlV2PropsFromQueryProp } from 'scenes/notebooks/Notebook/markdownNotebookV2'

import { applyVisualizationType, columnsFromResponse } from '~/queries/nodes/DataVisualization/dataVisualizationLogic'
import { Query } from '~/queries/Query/Query'
import { DataVisualizationNode, HogQLQueryResponse, NodeKind } from '~/queries/schema/schema-general'
import type { QueryContext } from '~/queries/types'
import { ChartDisplayType } from '~/types'

import { type PublishedRunResult, type SavedRows, savedQueryResult } from './notebookAppPublishedResults'
import type { ViewerOutput } from './notebookAppViewerLogic'

function publishedVisualization(
    attributes: NotebookComponentProps,
    result: HogQLQueryResponse,
    sql?: string
): DataVisualizationNode {
    const viz: DataVisualizationNode = {
        kind: NodeKind.DataVisualizationNode,
        display: ChartDisplayType.Auto,
        ...(attributes.vizQuery as Partial<DataVisualizationNode>),
        source: {
            kind: NodeKind.HogQLQuery,
            query: sql || String(attributes.code || ''),
            connectionId: typeof attributes.connectionId === 'string' ? attributes.connectionId : undefined,
            sendRawQuery: attributes.sendRawQuery === true || undefined,
        },
    }
    if (attributes.outputTab === 'results') {
        viz.display = ChartDisplayType.ActionsTable
    }
    viz.chartSettings = applyVisualizationType(
        viz,
        viz.display ?? ChartDisplayType.Auto,
        columnsFromResponse(result),
        result.results.length
    ).chartSettings
    return viz
}

function rowSummary(rows: SavedRows, count: number): string {
    switch (rows) {
        case 'partial':
            return `Only the first ${count} saved rows are available.`
        case 'capped':
            return `Showing ${count} saved rows, the limit for a SQL run.`
        case 'complete':
            return 'Published result'
    }
}

function publishedQueryHeight(
    display: ChartDisplayType | undefined,
    height: NotebookComponentProps[string]
): number | undefined {
    if (display === ChartDisplayType.BoldNumber || display === ChartDisplayType.Metric) {
        return undefined
    }
    return Math.max(160, Math.min(Number(height) || 320, 1000))
}

export function PublishedNotebookQuery({
    cell,
    current,
    pinned,
    sessionId,
    chartInputFilters,
}: {
    cell: NotebookComponentBlockNode
    current?: ViewerOutput
    pinned?: PublishedRunResult
    sessionId: string
    chartInputFilters: QueryContext['chartInputFilters']
}): JSX.Element {
    const attributes = { ...cell.props, ...getSqlV2PropsFromQueryProp(cell.props) }
    const output = current
        ? { result: current.result, rows: 'complete' as const }
        : savedQueryResult(attributes, pinned)
    if (output === 'loading') {
        return <Spinner />
    }
    if (output === 'unavailable') {
        return <LemonBanner type="info">The saved result is unavailable.</LemonBanner>
    }
    if (!output) {
        return <LemonBanner type="info">No published result for this cell.</LemonBanner>
    }
    const { result, rows } = output
    const viz = publishedVisualization(
        rows === 'partial' ? { ...attributes, outputTab: 'results' } : attributes,
        result,
        current?.query
    )
    const key = sessionId + '-' + cell.id + '-' + (current?.generation ?? 'published')
    const height = publishedQueryHeight(viz.display, attributes.height)
    return (
        <div className="min-w-0">
            <div className="flex min-h-0 flex-col overflow-auto" style={{ height }}>
                <Query
                    key={key}
                    uniqueKey={'SQLEditor-notebook-app-' + key}
                    query={viz}
                    cachedResults={result}
                    context={{ chartInputFilters }}
                    readOnly
                    embedded
                />
            </div>
            {!current && <small className="text-secondary">{rowSummary(rows, result.results.length)}</small>}
        </div>
    )
}
