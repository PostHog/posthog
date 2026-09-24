import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { SQLEditor } from 'scenes/data-warehouse/editor/SQLEditor'
import { sqlEditorLogic } from 'scenes/data-warehouse/editor/sqlEditorLogic'
import { SQLEditorMode } from 'scenes/data-warehouse/editor/sqlEditorModes'

import { NodeKind } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

import { getTracingSqlEditorTabId, tracingSceneLogic } from '../../tracingSceneLogic'

// Spans are only registered under the `posthog.` namespace, so the table name must stay qualified.
const DEFAULT_TRACING_QUERY = `SELECT timestamp, service_name, name, duration_nano / 1000000 AS duration_ms, status_code, trace_id, span_id
FROM posthog.trace_spans
WHERE timestamp > now() - INTERVAL 1 HOUR
ORDER BY timestamp DESC
LIMIT 100`

export interface TracingSqlEditorProps {
    id: string
}

export const TracingSqlEditor = ({ id }: TracingSqlEditorProps): JSX.Element => {
    const sqlEditorTabId = getTracingSqlEditorTabId(id)
    const { keepSqlEditorMounted } = useActions(tracingSceneLogic)
    const logic = sqlEditorLogic({ tabId: sqlEditorTabId, mode: SQLEditorMode.Embedded })
    const { queryInput } = useValues(logic)
    const { setQueryInput, setSourceQuery, runQuery } = useActions(logic)

    useEffect(() => {
        keepSqlEditorMounted(sqlEditorTabId)
    }, [sqlEditorTabId]) // eslint-disable-line react-hooks/exhaustive-deps

    useEffect(() => {
        if (queryInput === null) {
            setQueryInput(DEFAULT_TRACING_QUERY)
            setSourceQuery({
                kind: NodeKind.DataVisualizationNode,
                source: {
                    kind: NodeKind.HogQLQuery,
                    query: DEFAULT_TRACING_QUERY,
                },
                display: ChartDisplayType.ActionsTable,
            })
            runQuery(DEFAULT_TRACING_QUERY)
        }
    }, [queryInput]) // eslint-disable-line react-hooks/exhaustive-deps

    return (
        <div className="flex flex-col flex-1 min-h-0 min-w-0 border rounded overflow-hidden">
            <SQLEditor tabId={sqlEditorTabId} mode={SQLEditorMode.Embedded} defaultShowDatabaseTree={false} />
        </div>
    )
}
