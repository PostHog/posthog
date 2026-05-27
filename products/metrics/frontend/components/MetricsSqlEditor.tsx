import { useActions, useMountedLogic, useValues } from 'kea'
import { useEffect } from 'react'

import { SQLEditor } from 'scenes/data-warehouse/editor/SQLEditor'
import { sqlEditorLogic } from 'scenes/data-warehouse/editor/sqlEditorLogic'
import { SQLEditorMode } from 'scenes/data-warehouse/editor/sqlEditorModes'

import { NodeKind } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

import { getMetricsSqlEditorTabId, metricsSceneLogic } from '../metricsSceneLogic'
import { metricsSqlEditorTrackingLogic } from './metricsSqlEditorTrackingLogic'

// `metrics` is only registered under the `posthog.` HogQL namespace (see
// posthog/hogql/database/database.py). The WHERE bound lets ClickHouse prune
// daily partitions instead of cross-partition merging to satisfy the ORDER BY.
const DEFAULT_METRICS_QUERY =
    'SELECT timestamp, metric_name, value FROM posthog.metrics WHERE timestamp > now() - INTERVAL 1 DAY ORDER BY timestamp DESC LIMIT 100'

export interface MetricsSqlEditorProps {
    id: string
}

export const MetricsSqlEditor = ({ id }: MetricsSqlEditorProps): JSX.Element => {
    const sqlEditorTabId = getMetricsSqlEditorTabId(id)
    const { keepSqlEditorMounted } = useActions(metricsSceneLogic)
    const logic = sqlEditorLogic({ tabId: sqlEditorTabId, mode: SQLEditorMode.Embedded })
    const { queryInput } = useValues(logic)
    const { setQueryInput, setSourceQuery, runQuery } = useActions(logic)
    useMountedLogic(metricsSqlEditorTrackingLogic({ sqlEditorTabId }))

    useEffect(() => {
        keepSqlEditorMounted(sqlEditorTabId)
    }, [sqlEditorTabId]) // eslint-disable-line react-hooks/exhaustive-deps

    useEffect(() => {
        if (queryInput === null) {
            setQueryInput(DEFAULT_METRICS_QUERY)
            setSourceQuery({
                kind: NodeKind.DataVisualizationNode,
                source: {
                    kind: NodeKind.HogQLQuery,
                    query: DEFAULT_METRICS_QUERY,
                },
                display: ChartDisplayType.ActionsLineGraph,
            })
            runQuery(DEFAULT_METRICS_QUERY)
        }
    }, [queryInput]) // eslint-disable-line react-hooks/exhaustive-deps

    return (
        <div className="flex flex-col flex-1 min-h-0 min-w-0 border rounded overflow-hidden">
            <SQLEditor tabId={sqlEditorTabId} mode={SQLEditorMode.Embedded} defaultShowDatabaseTree={false} />
        </div>
    )
}
