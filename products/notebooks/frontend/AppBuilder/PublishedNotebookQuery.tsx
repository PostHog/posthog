import { LemonBanner } from '@posthog/lemon-ui'

import type { NotebookComponentBlockNode, NotebookComponentProps } from 'lib/components/MarkdownNotebook/types'
import { type NotebookNodeSQLV2Result, toCachedResults } from 'scenes/notebooks/Nodes/NotebookNodeSQLV2'
import { getSqlV2PropsFromQueryProp } from 'scenes/notebooks/Notebook/markdownNotebookV2'

import { applyVisualizationType, columnsFromResponse } from '~/queries/nodes/DataVisualization/dataVisualizationLogic'
import { Query } from '~/queries/Query/Query'
import { DataVisualizationNode, HogQLQueryResponse, NodeKind } from '~/queries/schema/schema-general'
import type { QueryContext } from '~/queries/types'
import { ChartDisplayType } from '~/types'

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

export function PublishedNotebookQuery({
    cell,
    current,
    sessionId,
    chartInputFilters,
}: {
    cell: NotebookComponentBlockNode
    current?: ViewerOutput
    sessionId: string
    chartInputFilters: QueryContext['chartInputFilters']
}): JSX.Element {
    const attributes = { ...cell.props, ...getSqlV2PropsFromQueryProp(cell.props) }
    const snapshot = attributes.result as NotebookNodeSQLV2Result | undefined
    const result = current?.result ?? (snapshot ? toCachedResults(snapshot) : undefined)
    if (!result) {
        return <LemonBanner type="info">No published result for this cell.</LemonBanner>
    }
    const viz = publishedVisualization(attributes, result, current?.query)
    const key = sessionId + '-' + cell.id + '-' + (current?.generation ?? 'published')
    const compact = viz.display === ChartDisplayType.BoldNumber || viz.display === ChartDisplayType.Metric
    const height = compact ? undefined : Math.max(160, Math.min(Number(attributes.height) || 320, 1000))
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
            {!current && (
                <small className="text-secondary">
                    {snapshot?.previewOnly ? 'Published preview' : 'Published result'}
                </small>
            )}
        </div>
    )
}
