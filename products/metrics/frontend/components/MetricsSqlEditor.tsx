import { useActions, useMountedLogic, useValues } from 'kea'
import { useEffect } from 'react'

import { SQLEditor } from 'scenes/data-warehouse/editor/SQLEditor'
import { sqlEditorLogic } from 'scenes/data-warehouse/editor/sqlEditorLogic'
import { SQLEditorMode } from 'scenes/data-warehouse/editor/sqlEditorModes'

import { NodeKind } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

import { METRICS_SQL_EDITOR_TAB_ID, metricsSceneLogic } from '../metricsSceneLogic'
import { metricsSqlEditorTrackingLogic } from './metricsSqlEditorTrackingLogic'

// `metrics` is only registered under the `posthog.` HogQL namespace
// (posthog/hogql/database/database.py), so unlike `logs` it must be
// referenced fully qualified.
const DEFAULT_METRICS_QUERY = 'SELECT * FROM posthog.metrics LIMIT 10'

export const MetricsSqlEditor = (): JSX.Element => {
    const sqlEditorTabId = METRICS_SQL_EDITOR_TAB_ID
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
