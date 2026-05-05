import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { SQLEditor } from 'scenes/data-warehouse/editor/SQLEditor'
import { sqlEditorLogic } from 'scenes/data-warehouse/editor/sqlEditorLogic'
import { SQLEditorMode } from 'scenes/data-warehouse/editor/sqlEditorModes'

import { NodeKind } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

import { logsSceneLogic } from 'products/logs/frontend/logsSceneLogic'

const DEFAULT_LOGS_QUERY = 'SELECT * FROM logs LIMIT 10'

export interface LogsSqlEditorProps {
    id: string
}

export const LogsSqlEditor = ({ id }: LogsSqlEditorProps): JSX.Element => {
    const sqlEditorTabId = `logs-sql-editor-${id}`
    const { keepSqlEditorMounted } = useActions(logsSceneLogic)
    const logic = sqlEditorLogic({ tabId: sqlEditorTabId, mode: SQLEditorMode.Embedded })
    const { queryInput } = useValues(logic)
    const { setQueryInput, setSourceQuery, runQuery } = useActions(logic)

    useEffect(() => {
        keepSqlEditorMounted(sqlEditorTabId)
    }, [sqlEditorTabId]) // eslint-disable-line react-hooks/exhaustive-deps

    useEffect(() => {
        if (queryInput === null) {
            setQueryInput(DEFAULT_LOGS_QUERY)
            setSourceQuery({
                kind: NodeKind.DataVisualizationNode,
                source: {
                    kind: NodeKind.HogQLQuery,
                    query: DEFAULT_LOGS_QUERY,
                },
                display: ChartDisplayType.ActionsLineGraph,
            })
            runQuery(DEFAULT_LOGS_QUERY)
        }
    }, [queryInput]) // eslint-disable-line react-hooks/exhaustive-deps

    return (
        <div className="flex flex-col flex-1 min-h-0 min-w-0 border rounded overflow-hidden">
            <SQLEditor tabId={sqlEditorTabId} mode={SQLEditorMode.Embedded} defaultShowDatabaseTree={false} />
        </div>
    )
}
