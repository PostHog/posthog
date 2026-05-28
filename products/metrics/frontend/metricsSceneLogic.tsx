import { actions, kea, listeners, path, props, selectors } from 'kea'

import { tabAwareScene } from 'lib/logic/scenes/tabAwareScene'
import { sqlEditorLogic } from 'scenes/data-warehouse/editor/sqlEditorLogic'
import { SQLEditorMode } from 'scenes/data-warehouse/editor/sqlEditorModes'

import type { metricsSceneLogicType } from './metricsSceneLogicType'

export const getMetricsSqlEditorTabId = (id: string): string => `metrics-sql-editor-${id}`

export interface MetricsLogicProps {
    tabId: string
}

export const metricsSceneLogic = kea<metricsSceneLogicType>([
    props({} as MetricsLogicProps),
    path(['products', 'metrics', 'frontend', 'metricsSceneLogic']),
    tabAwareScene(),
    actions({
        keepSqlEditorMounted: (editorTabId: string) => ({ editorTabId }),
    }),
    selectors({
        tabId: [(_, p) => [p.tabId], (tabId: string) => tabId],
    }),
    listeners(({ cache }) => ({
        keepSqlEditorMounted: ({ editorTabId }) => {
            if (cache.sqlEditorTabId === editorTabId) {
                return
            }
            cache.unmountSqlEditor?.()
            cache.sqlEditorTabId = editorTabId
            // Intentionally not cleaned up in beforeUnmount: keeps the embedded sqlEditorLogic
            // alive across navigation so the user's query survives leaving and re-entering /metrics.
            cache.unmountSqlEditor = sqlEditorLogic({ tabId: editorTabId, mode: SQLEditorMode.Embedded }).mount()
        },
    })),
])
